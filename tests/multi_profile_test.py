from __future__ import annotations

import http.cookiejar
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def request(self, path, method="GET", data=None, expected=200):
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Accept": "application/json", "Connection": "close"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if method != "GET" and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        req = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
        try:
            with self.opener.open(req, timeout=15) as response:
                payload = json.loads(response.read().decode() or "{}")
                assert response.status == expected, (path, response.status, payload)
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode() or "{}")
            assert exc.code == expected, (path, exc.code, payload)
        if payload.get("csrf_token"):
            self.csrf = payload["csrf_token"]
        return payload

    def login(self, email, password):
        self.request("/api/login", "POST", {"email": email, "password": password})
        boot = self.request("/api/bootstrap")
        self.csrf = boot["csrf_token"]
        return boot["user"]


def wait_server(process):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("Servidor encerrou")
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=.5).close()
            return
        except Exception:
            time.sleep(.1)
    raise RuntimeError("Servidor não iniciou")


def main():
    global BASE
    temp = Path(tempfile.mkdtemp(prefix="onecrm_profiles_"))
    port = free_port()
    BASE = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({"ONE_CRM_DATA_DIR": str(temp), "ONE_CRM_PORT": str(port), "ONE_CRM_NO_BROWSER": "1"})
    process = subprocess.Popen([sys.executable, str(ROOT / "one_crm_server.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        wait_server(process)
        owner = Client()
        owner.request("/api/setup", "POST", {"name": "Dono", "email": "owner@test.local", "password": "Owner1234"}, 201)
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        assert boot["user"]["is_platform_owner"] is True
        default_profile = boot["user"]["profile"]["id"]

        contractor_id = owner.request("/api/users", "POST", {
            "name": "Contratante Caixa", "email": "cash@test.local", "password": "Cash12345", "role_code": "manager"
        }, 201)["id"]

        created = owner.request("/api/profiles", "POST", {
            "name": "Caixa Empresa B", "business_type": "cash_control", "contractor_user_id": contractor_id
        }, 201)
        cash_profile = created["id"]
        profiles = owner.request("/api/profiles")["profiles"]
        assert {p["id"] for p in profiles} == {default_profile, cash_profile}

        owner.request("/api/profiles/switch", "POST", {"profile_id": cash_profile})
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        assert boot["user"]["profile"]["business_type"] == "cash_control"
        owner.request("/api/cash", "POST", {
            "transaction_type": "entry", "category": "Vendas", "description": "Recebimento", "amount": 1500, "transaction_date": "2026-08-04"
        }, 201)
        owner.request("/api/cash", "POST", {
            "transaction_type": "exit", "category": "Operação", "description": "Despesa", "amount": 250, "transaction_date": "2026-08-04"
        }, 201)
        cash = owner.request("/api/cash")
        assert cash["summary"]["balance"] == 1250

        contractor = Client()
        contractor_user = contractor.login("cash@test.local", "Cash12345")
        assert contractor_user["is_contractor"] is True
        assert contractor_user["role_name"] == "Contratante"
        assert contractor_user["profile"]["id"] == cash_profile
        assert "cash.view" in contractor_user["permissions"]
        assert "cash.manage" not in contractor_user["permissions"]
        assert "profile.view" in contractor_user["permissions"]
        assert "profile.configure" not in contractor_user["permissions"]
        assert len(contractor.request("/api/profiles")["profiles"]) == 1
        contractor.request("/api/profiles/switch", "POST", {"profile_id": default_profile}, expected=403)
        contractor.request("/api/sales", expected=403)
        assert contractor.request("/api/cash")["summary"]["balance"] == 1250

        # O Contratante enxerga o ambiente, mas todas as mutações são negadas.
        contractor.request(f"/api/profiles/{cash_profile}", "PUT", {"description": "Tentativa"}, expected=403)
        contractor.request("/api/cash", "POST", {
            "transaction_type": "entry", "category": "Teste", "description": "Não permitido",
            "amount": 10, "transaction_date": "2026-08-04"
        }, expected=403)
        contractor.request("/api/users", "POST", {
            "name": "Usuário indevido", "email": "blocked@test.local", "password": "Blocked123", "role_code": "seller"
        }, expected=403)
        contractor.request("/api/roles", "POST", {
            "name": "Cargo indevido", "code": "cargo_indevido", "base_role": "seller", "permissions": []
        }, expected=403)
        contractor.request("/api/integrations", "PUT", {"ai_provider": "local"}, expected=403)
        assert contractor.request("/api/roles")["roles"]
        assert contractor.request("/api/integrations")["ok"] is True

        owner.request("/api/profiles/switch", "POST", {"profile_id": default_profile})
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        assert boot["user"]["profile"]["id"] == default_profile
        assert owner.request("/api/cash", expected=200)["transactions"] == []  # Dono pode acessar, mas dados continuam isolados.
        print("MULTI PROFILE TEST: OK")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
