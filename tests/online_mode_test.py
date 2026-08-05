from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = "18765"
BASE_URL = f"http://127.0.0.1:{PORT}"


def request_json(path: str, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": "203.0.113.20",
            "X-Forwarded-Proto": "https",
        },
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="onecrm-online-") as data_dir:
        env = os.environ.copy()
        env.update(
            {
                "RAILWAY_ENVIRONMENT": "production",
                "RAILWAY_PROJECT_ID": "test-project",
                "RAILWAY_VOLUME_MOUNT_PATH": data_dir,
                "PORT": PORT,
                "ONE_CRM_SETUP_TOKEN": "token-de-teste-online-abcdefghijklmnopqrstuvwxyz-123456",
                "ONE_CRM_SECURE_COOKIES": "1",
                "ONE_CRM_TRUST_PROXY_HEADERS": "1",
                "ONE_CRM_NO_BROWSER": "1",
            }
        )
        process = subprocess.Popen(
            [os.environ.get("PYTHON", "python"), "one_crm_server.py"],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            for _ in range(80):
                try:
                    status, health = request_json("/api/health")
                    if status == 200:
                        break
                except Exception:
                    pass
                time.sleep(0.1)
            else:
                raise AssertionError("O servidor online não iniciou.")

            assert health["database"] == "ok"
            assert health["persistent_storage"] is True

            status, bootstrap = request_json("/api/bootstrap")
            assert status == 200
            assert bootstrap["setup_required"] is True
            assert bootstrap["setup_token_required"] is True

            status, _ = request_json(
                "/api/setup",
                {
                    "name": "Dono Online",
                    "email": "dono@example.com",
                    "password": "Senha123",
                    "setup_token": "incorreto",
                },
            )
            assert status == 403

            status, created = request_json(
                "/api/setup",
                {
                    "name": "Dono Online",
                    "email": "dono@example.com",
                    "password": "Senha123",
                    "setup_token": "token-de-teste-online-abcdefghijklmnopqrstuvwxyz-123456",
                },
            )
            assert status == 201 and created["ok"] is True
            assert (Path(data_dir) / "one_crm.db").is_file()

            print("ONLINE MODE TEST: OK")
            print("PORT, Volume, healthcheck e token inicial funcionaram corretamente.")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            if process.returncode not in (0, -15, 143):
                output = process.stdout.read() if process.stdout else ""
                print(output)


if __name__ == "__main__":
    main()
