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

    def refresh(self):
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
    temp = Path(tempfile.mkdtemp(prefix="onecrm_productivity_profiles_"))
    port = free_port()
    BASE = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({
        "ONE_CRM_DATA_DIR": str(temp),
        "ONE_CRM_PORT": str(port),
        "ONE_CRM_NO_BROWSER": "1",
        "ONE_CRM_REQUIRE_SETUP_TOKEN": "0",
        "ONE_CRM_REQUIRE_PERSISTENT_STORAGE": "0",
    })
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "one_crm_server.py")],
        env=env,
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_server(process)
        owner = Client()
        owner.request("/api/setup", "POST", {
            "name": "Dono", "email": "owner@isolation.local", "password": "Owner1234"
        }, 201)
        user = owner.refresh()
        owner_id = int(user["id"])
        profile_a = int(user["profile"]["id"])

        roles = owner.request("/api/roles")["roles"]
        seller_role = next(r["code"] for r in roles if r.get("base_role") == "seller")
        worker_id = owner.request("/api/users", "POST", {
            "name": "Funcionário Perfil A",
            "email": "worker-a@isolation.local",
            "password": "Worker1234",
            "role_code": seller_role,
        }, 201)["id"]

        task_a = owner.request("/api/tasks", "POST", {
            "title": "Tarefa exclusiva A",
            "assigned_user_id": owner_id,
            "priority": "normal",
        }, 201)["id"]
        notifications_a = owner.request("/api/notifications")
        notif_a = next(item for item in notifications_a["notifications"] if item["message"] == "Tarefa exclusiva A")
        assert notifications_a["profile_id"] == profile_a

        profile_b = owner.request("/api/profiles", "POST", {
            "name": "Perfil B", "business_type": "services"
        }, 201)["id"]
        owner.request("/api/profiles/switch", "POST", {"profile_id": profile_b})
        owner.refresh()

        task_b = owner.request("/api/tasks", "POST", {
            "title": "Tarefa exclusiva B",
            "assigned_user_id": owner_id,
            "priority": "high",
        }, 201)["id"]

        tasks_b = owner.request("/api/tasks")["tasks"]
        assert {item["id"] for item in tasks_b} == {task_b}, tasks_b
        notifications_b = owner.request("/api/notifications")
        assert notifications_b["profile_id"] == profile_b
        assert {item["message"] for item in notifications_b["notifications"]} == {"Tarefa exclusiva B"}, notifications_b

        # Um usuário que só pertence ao Perfil A não pode virar responsável no Perfil B.
        owner.request("/api/tasks", "POST", {
            "title": "Tarefa cruzada bloqueada",
            "assigned_user_id": worker_id,
        }, expected=400)

        # O mesmo bloqueio vale para destinatários embutidos em automações.
        owner.request("/api/automations", "POST", {
            "name": "Automação cruzada",
            "trigger_event": "task.created",
            "conditions": {},
            "actions": [{
                "type": "notify",
                "user_id": worker_id,
                "title": "Não pode",
                "message": "Não pode atravessar perfil",
            }],
            "active": True,
        }, expected=400)

        # Uma notificação do Perfil A não pode ser marcada como lida enquanto B está ativo.
        owner.request(f"/api/notifications/{notif_a['id']}", "PUT", {}, 200)

        owner.request("/api/profiles/switch", "POST", {"profile_id": profile_a})
        owner.refresh()
        tasks_a = owner.request("/api/tasks")["tasks"]
        assert {item["id"] for item in tasks_a} == {task_a}, tasks_a
        notifications_a_again = owner.request("/api/notifications")
        assert {item["message"] for item in notifications_a_again["notifications"]} == {"Tarefa exclusiva A"}
        restored = next(item for item in notifications_a_again["notifications"] if item["id"] == notif_a["id"])
        assert restored["read_at"] is None

        print("PRODUCTIVITY PROFILE ISOLATION TEST: OK")
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
