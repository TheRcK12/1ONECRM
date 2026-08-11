from __future__ import annotations

import http.cookiejar
import json
import os
import shutil
import socket
import sqlite3
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
            with self.opener.open(req, timeout=20) as response:
                payload = json.loads(response.read().decode() or "{}")
                assert response.status == expected, (path, response.status, payload)
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode() or "{}")
            assert exc.code == expected, (path, exc.code, payload)
        if payload.get("csrf_token"):
            self.csrf = payload["csrf_token"]
        return payload


def wait_server(process):
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError("Servidor encerrou")
        try:
            urllib.request.urlopen(BASE + "/api/health", timeout=.5).close()
            return
        except Exception:
            time.sleep(.1)
    raise RuntimeError("Servidor não iniciou")


def main() -> int:
    global BASE
    temp = Path(tempfile.mkdtemp(prefix="onecrm_profile_delete_"))
    port = free_port()
    BASE = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({"ONE_CRM_DATA_DIR": str(temp), "ONE_CRM_PORT": str(port), "ONE_CRM_NO_BROWSER": "1"})
    process = subprocess.Popen([sys.executable, str(ROOT / "one_crm_server.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        wait_server(process)
        owner = Client()
        owner.request("/api/setup", "POST", {"name": "Dono", "email": "owner@delete.local", "password": "Owner1234"}, 201)
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        default_profile = int(boot["user"]["profile"]["id"])

        # O único perfil é protegido.
        owner.request(f"/api/profiles/{default_profile}", "DELETE", expected=409)

        second = owner.request("/api/profiles", "POST", {
            "name": "Perfil para Excluir", "business_type": "cash_control"
        }, 201)["id"]
        owner.request("/api/profiles/switch", "POST", {"profile_id": second})
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        assert int(boot["user"]["profile"]["id"]) == second
        owner.request("/api/cash", "POST", {
            "transaction_type": "entry", "category": "Teste", "description": "Dado descartável",
            "amount": 77, "transaction_date": "2026-08-11"
        }, 201)

        # Um usuário não-Dono não pode excluir perfil.
        role_code = owner.request("/api/roles")["roles"][0]["code"]
        worker_id = owner.request("/api/users", "POST", {
            "name": "Operador", "email": "worker@delete.local", "password": "Worker1234", "role_code": role_code
        }, 201)["id"]
        assert worker_id > 0
        worker = Client()
        worker.request("/api/login", "POST", {"email": "worker@delete.local", "password": "Worker1234"})
        worker_boot = worker.request("/api/bootstrap")
        worker.csrf = worker_boot["csrf_token"]
        worker.request(f"/api/profiles/{second}", "DELETE", expected=403)

        result = owner.request(f"/api/profiles/{second}", "DELETE")
        assert result["deleted_profile_id"] == second
        assert result["fallback_profile_id"] == default_profile
        assert result["backup"].startswith("one_crm_pre_profile_delete_")
        assert (temp / "backups" / result["backup"]).exists()

        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        assert int(boot["user"]["profile"]["id"]) == default_profile
        profiles = owner.request("/api/profiles")["profiles"]
        assert [int(item["id"]) for item in profiles] == [default_profile]

        # Confere que nenhum dado escopado ficou órfão no banco.
        db = temp / "one_crm.db"
        with sqlite3.connect(db) as conn:
            tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
                if "profile_id" in columns:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{table}" WHERE profile_id=?', (second,)).fetchone()[0]
                    assert count == 0, (table, count)
            assert conn.execute("SELECT COUNT(*) FROM business_profiles WHERE id=?", (second,)).fetchone()[0] == 0

        print("PROFILE DELETE TEST: OK")
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
