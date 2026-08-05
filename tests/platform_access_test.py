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

    def login(self, email: str, password: str):
        self.request("/api/login", "POST", {"email": email, "password": password})
        boot = self.request("/api/bootstrap")
        self.csrf = boot["csrf_token"]
        return boot["user"]


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
    temp = Path(tempfile.mkdtemp(prefix="onecrm_platform_access_"))
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
        owner.request("/api/setup", "POST", {
            "name": "Dono Principal", "email": "owner@platform.local", "password": "Owner1234"
        }, 201)
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        default_profile = boot["user"]["profile"]["id"]
        assert boot["user"]["is_platform_owner"] is True

        second_profile = owner.request("/api/profiles", "POST", {
            "name": "Perfil Financeiro", "business_type": "cash_control"
        }, 201)["id"]

        access = owner.request("/api/platform-access")
        assert {role["code"] for role in access["roles"]} >= {"owner", "platform_admin"}

        custom_role = owner.request("/api/platform-roles", "POST", {
            "name": "Administrador Regional",
            "code": "admin_regional",
            "description": "Administra pessoas e operação nos perfis atribuídos.",
            "permissions": [
                "platform.profile.read", "platform.profile.manage", "platform.people.manage",
                "platform.security.manage", "platform.audit.view"
            ],
        }, 201)["code"]
        assert custom_role == "admin_regional"

        admin_id = owner.request("/api/platform-users", "POST", {
            "name": "Admin Regional", "email": "admin@platform.local", "password": "Admin1234",
            "platform_role_code": "admin_regional", "profile_ids": [default_profile, second_profile],
        }, 201)["id"]
        assert admin_id > 0

        second_owner_id = owner.request("/api/platform-users", "POST", {
            "name": "Segundo Dono", "email": "owner2@platform.local", "password": "Owner2234",
            "platform_role_code": "owner", "profile_ids": [],
        }, 201)["id"]
        assert second_owner_id > 0

        admin = Client()
        admin_user = admin.login("admin@platform.local", "Admin1234")
        assert admin_user["is_platform_owner"] is False
        assert admin_user["is_platform_staff"] is True
        assert admin_user["platform_role_code"] == "admin_regional"
        assert len(admin_user["profiles"]) == 2
        assert "users.manage" in admin_user["permissions"]
        assert "roles.manage" in admin_user["permissions"]
        admin.request("/api/platform-access", expected=403)
        admin.request("/api/profiles", expected=200)
        admin.request("/api/profiles", "POST", {"name": "Não permitido", "business_type": "services"}, expected=403)

        admin.request("/api/profiles/switch", "POST", {"profile_id": second_profile})
        boot_admin = admin.request("/api/bootstrap")
        admin.csrf = boot_admin["csrf_token"]
        assert boot_admin["user"]["profile"]["id"] == second_profile
        cash_roles = admin.request("/api/roles")["roles"]
        operator_role = next(role["code"] for role in cash_roles if "Operador de caixa" in role["name"])
        admin.request("/api/users", "POST", {
            "name": "Funcionário Caixa", "email": "worker@platform.local", "password": "Worker1234",
            "role_code": operator_role
        }, 201)

        owner2 = Client()
        owner2_user = owner2.login("owner2@platform.local", "Owner2234")
        assert owner2_user["is_platform_owner"] is True
        assert owner2.request("/api/platform-access")["ok"] is True

        # O último Dono ativo não pode ser removido. Como há dois, o segundo pode ser bloqueado.
        owner.request(f"/api/platform-users/{second_owner_id}", "PUT", {
            "name": "Segundo Dono", "email": "owner2@platform.local", "platform_role_code": "owner",
            "active": False, "must_change_password": False, "profile_ids": []
        })

        print("PLATFORM ACCESS TEST: OK")
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
