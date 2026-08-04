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
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def request(self, path: str, method: str = "GET", data=None, expected: int = 200):
        body = json.dumps(data).encode() if data is not None else None
        headers = {"Accept": "application/json", "Connection": "close"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if method != "GET" and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=20) as response:
                payload = json.loads(response.read().decode() or "{}")
                assert response.status == expected, (path, response.status, payload)
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode() or "{}")
            assert exc.code == expected, (path, exc.code, payload)
        if payload.get("csrf_token"):
            self.csrf = payload["csrf_token"]
        return payload


def wait_server(process: subprocess.Popen) -> None:
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError("Servidor encerrou durante a inicialização")
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=.5).close()
            return
        except Exception:
            time.sleep(.1)
    raise RuntimeError("Servidor não iniciou")


def main() -> int:
    global BASE
    temp = Path(tempfile.mkdtemp(prefix="onecrm_presets_"))
    port = free_port()
    BASE = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({"ONE_CRM_DATA_DIR": str(temp), "ONE_CRM_PORT": str(port), "ONE_CRM_NO_BROWSER": "1"})
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "one_crm_server.py")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_server(process)
        owner = Client()
        owner.request("/api/setup", "POST", {"name": "Dono", "email": "owner@preset.local", "password": "Owner1234"}, 201)
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]

        templates = owner.request("/api/profiles")["templates"]
        real_estate_template = next(item for item in templates if item["code"] == "real_estate")
        assert "properties" in real_estate_template["modules"]
        assert "bko" not in real_estate_template["modules"]
        assert real_estate_template["roles_count"] >= 3
        assert real_estate_template["catalogs_count"] >= 6
        assert real_estate_template["offerings_count"] >= 3

        created = owner.request("/api/profiles", "POST", {
            "name": "Imobiliária Horizonte",
            "business_type": "real_estate",
        }, 201)
        profile_id = created["id"]
        owner.request("/api/profiles/switch", "POST", {"profile_id": profile_id})
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        profile = boot["user"]["profile"]
        modules = set(profile["modules"])
        assert profile["business_type"] == "real_estate"
        assert {"properties", "real_estate_leads", "visits", "proposals"}.issubset(modules)
        assert "sales" not in modules
        assert "bko" not in modules
        assert profile["preset"]["navigation_labels"]["properties"] == "Imóveis"

        roles = owner.request("/api/roles")["roles"]
        role_names = {item["name"].split(" · ")[0] for item in roles}
        assert {"Gerente imobiliário", "Corretor", "Assistente imobiliário"}.issubset(role_names)

        catalogs = owner.request("/api/catalogs")["catalogs"]
        assert {"property_type", "transaction_type", "property_status", "lead_interest", "visit_status", "proposal_status"}.issubset(catalogs)

        plans = owner.request("/api/plans")["plans"]
        plan_names = {item["name"] for item in plans}
        assert {"Intermediação de venda", "Administração de locação", "Avaliação imobiliária"}.issubset(plan_names)

        properties = owner.request("/api/profile-records?module=properties")
        assert properties["config"]["label"] == "Imóveis"
        assert properties["can_manage"] is True
        property_type = catalogs["property_type"][0]["code"]
        transaction_type = catalogs["transaction_type"][0]["code"]
        property_status = next(item["code"] for item in catalogs["property_status"] if item["label"] == "Disponível")
        owner.request("/api/profile-records", "POST", {
            "module": "properties",
            "title": "Apartamento no Centro",
            "subtitle": "2 quartos",
            "status": property_status,
            "amount": 350000,
            "data": {"property_type": property_type, "transaction_type": transaction_type, "location": "Centro"},
        }, 201)
        assert owner.request("/api/profile-records?module=properties")["summary"]["total"] == 1

        print("PRESET ASSETS TEST: OK")
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
