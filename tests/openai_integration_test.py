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
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUEST_TIMEOUT = 15


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class MockOpenAIHandler(BaseHTTPRequestHandler):
    requests: list[dict] = []

    def log_message(self, *_args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        self.__class__.requests.append(payload)
        raw = json.dumps({
            "id": f"resp_test_{len(self.__class__.requests)}",
            "model": payload.get("model", "gpt-5.6-luna"),
            "output": [{
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Análise concluída com segurança.", "annotations": []}],
            }],
            "usage": {"input_tokens": 100, "output_tokens": 8, "total_tokens": 108},
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True


class Client:
    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def request(self, path: str, method: str = "GET", data=None, expected: int = 200):
        body = json.dumps(data).encode("utf-8") if data is not None else None
        headers = {"Accept": "application/json", "Connection": "close"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if method != "GET" and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(self.base + path, data=body, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=REQUEST_TIMEOUT) as response:
                result = json.loads(response.read().decode("utf-8"))
                assert response.status == expected, (path, response.status, result)
        except urllib.error.HTTPError as exc:
            result = json.loads(exc.read().decode("utf-8"))
            assert exc.code == expected, (path, exc.code, result)
        if result.get("csrf_token"):
            self.csrf = result["csrf_token"]
        return result

    def login(self, email: str, password: str):
        self.request("/api/login", "POST", {"email": email, "password": password})
        boot = self.request("/api/bootstrap")
        self.csrf = boot["csrf_token"]
        return boot["user"]


def wait_server(base: str, process: subprocess.Popen, log_path: Path) -> None:
    for _ in range(120):
        if process.poll() is not None:
            raise RuntimeError(log_path.read_text(encoding="utf-8", errors="replace"))
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=0.5):
                return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError("Servidor ONE CRM não iniciou.")


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="one_crm_ai_test_"))
    crm_port = free_port()
    openai_port = free_port()
    mock_server = ThreadingHTTPServer(("127.0.0.1", openai_port), MockOpenAIHandler)
    threading.Thread(target=mock_server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{crm_port}"
    env = os.environ.copy()
    env.update({
        "ONE_CRM_DATA_DIR": str(temp),
        "ONE_CRM_PORT": str(crm_port),
        "ONE_CRM_NO_BROWSER": "1",
        "OPENAI_API_KEY": "sk-test-one-crm",
        "OPENAI_MODEL": "gpt-5.6-luna",
        "ONE_CRM_AI_ENABLED": "1",
        "OPENAI_API_URL": f"http://127.0.0.1:{openai_port}/v1/responses",
        "PYTHONUNBUFFERED": "1",
    })
    log_path = temp / "server.log"
    log_handle = log_path.open("w", encoding="utf-8", buffering=1)
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "one_crm_server.py")],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_server(base, process, log_path)
        owner = Client(base)
        owner.request("/api/setup", "POST", {"name": "Dono", "email": "owner@teste.local", "password": "Owner1234"}, 201)
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]
        status = owner.request("/api/ai/status")["openai"]
        assert status["ready"] is True
        assert status["model"] == "gpt-5.6-luna"
        test = owner.request("/api/ai/test", "POST", {})
        assert test["ok"] is True

        plan_id = owner.request("/api/plans")["plans"][0]["id"]
        seller_id = owner.request("/api/users", "POST", {
            "name": "Vendedor",
            "email": "seller@teste.local",
            "password": "Seller123",
            "role_code": "seller",
        }, 201)["id"]
        sale_id = owner.request("/api/sales", "POST", {
            "client_name": "Cliente Sigiloso",
            "person_type": "CPF",
            "cpf_cnpj": "529.982.247-25",
            "phone": "(61) 99999-9999",
            "email": "cliente@segredo.local",
            "cep": "72410-200",
            "address": "Quadra 4",
            "address_number": "10",
            "city": "Brasília",
            "uf": "DF",
            "notes": "Retornar no telefone 61999999999. CPF 52998224725 e email cliente@segredo.local.",
            "plan_id": plan_id,
            "seller_id": seller_id,
        }, 201)["id"]
        answer = owner.request("/api/ai/ask", "POST", {
            "question": "Qual é a próxima ação recomendada?",
            "sale_id": sale_id,
        })
        assert answer["answer"] == "Análise concluída com segurança."
        assert answer["usage"]["total_tokens"] == 108

        sent = json.dumps(MockOpenAIHandler.requests[-1], ensure_ascii=False)
        assert "52998224725" not in sent
        assert "61999999999" not in sent
        assert "cliente@segredo.local" not in sent
        assert "OPENAI_API_KEY" not in sent

        seller = Client(base)
        seller.login("seller@teste.local", "Seller123")
        seller.request("/api/ai/ask", "POST", {"question": "Teste"}, expected=403)

        with sqlite3.connect(temp / "one_crm.db") as conn:
            success_count = conn.execute("SELECT COUNT(*) FROM ai_usage_logs WHERE status='success'").fetchone()[0]
            assert success_count >= 1
        print("OPENAI INTEGRATION TEST: OK")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        log_handle.close()
        mock_server.shutdown()
        mock_server.server_close()
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
