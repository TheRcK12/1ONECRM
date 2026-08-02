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
BASE = ""
REQUEST_TIMEOUT = 15


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def step(label: str) -> None:
    print(f"[TESTE] {label}...", flush=True)


class TestHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32


class CepMockHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def send_payload(self, status: int, payload: dict):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def do_GET(self):
        cep = self.path.rstrip("/").rsplit("/", 1)[-1].replace(".json", "")
        if self.path.startswith("/brasilapi/"):
            if cep == "72862504":
                return self.send_payload(200, {"cep": cep, "state": "GO", "city": "Novo Gama", "neighborhood": "Loteamento Lunabel 3", "street": "Quadra 4", "service": "mock"})
            if cep == "72410200":
                return self.send_payload(503, {"message": "indisponível"})
            return self.send_payload(404, {"message": "não encontrado"})
        if self.path.startswith("/viacep/"):
            if cep == "72410200":
                return self.send_payload(200, {"cep": "72410-200", "logradouro": "Quadra 4", "bairro": "Setor Sul (Gama)", "localidade": "Brasília", "uf": "DF", "ddd": "61", "ibge": "5300108"})
            return self.send_payload(404, {"erro": True})
        return self.send_payload(404, {"erro": True})


class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def request(self, path: str, method: str = "GET", data=None, expected: int = 200):
        body = None
        headers = {"Accept": "application/json", "Connection": "close"}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method != "GET" and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
        try:
            with self.opener.open(request, timeout=REQUEST_TIMEOUT) as response:
                raw = response.read().decode("utf-8")
                result = json.loads(raw) if raw else {}
                assert response.status == expected, (path, response.status, result)
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8")
                result = json.loads(raw) if raw else {}
                assert exc.code == expected, (path, exc.code, result)
            finally:
                exc.close()
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as exc:
            raise AssertionError(f"Falha de comunicação em {method} {path}: {exc}") from exc
        if isinstance(result, dict) and result.get("csrf_token"):
            self.csrf = result["csrf_token"]
        return result

    def login(self, email: str, password: str):
        self.request("/api/login", "POST", {"email": email, "password": password})
        boot = self.request("/api/bootstrap")
        self.csrf = boot["csrf_token"]
        return boot["user"]


def read_url(path: str, timeout: float = REQUEST_TIMEOUT) -> bytes:
    request = urllib.request.Request(BASE + path, headers={"Connection": "close"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def wait_server(process: subprocess.Popen, server_log: Path) -> None:
    for _ in range(120):
        if process.poll() is not None:
            details = server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else ""
            raise RuntimeError(f"Servidor encerrou durante a inicialização.\n{details[-4000:]}")
        try:
            read_url("/api/health", timeout=0.5)
            return
        except Exception:
            time.sleep(0.1)
    details = server_log.read_text(encoding="utf-8", errors="replace") if server_log.exists() else ""
    raise RuntimeError(f"Servidor não iniciou no tempo esperado.\n{details[-4000:]}")


def main() -> int:
    global BASE
    temp = Path(tempfile.mkdtemp(prefix="one_crm_test_"))
    crm_port = free_port()
    cep_port = free_port()
    while cep_port == crm_port:
        cep_port = free_port()
    BASE = f"http://127.0.0.1:{crm_port}"

    cep_server = TestHTTPServer(("127.0.0.1", cep_port), CepMockHandler)
    cep_thread = threading.Thread(target=cep_server.serve_forever, name="cep-mock", daemon=True)
    cep_thread.start()

    env = os.environ.copy()
    env.update({
        "ONE_CRM_DATA_DIR": str(temp),
        "ONE_CRM_PORT": str(crm_port),
        "ONE_CRM_NO_BROWSER": "1",
        "PYTHONUNBUFFERED": "1",
        "ONE_CRM_CEP_BRASILAPI_URL": f"http://127.0.0.1:{cep_port}/brasilapi/{{cep}}",
        "ONE_CRM_CEP_VIACEP_URL": f"http://127.0.0.1:{cep_port}/viacep/{{cep}}",
        "ONE_CRM_CEP_OPENCEP_URL": f"http://127.0.0.1:{cep_port}/opencep/{{cep}}.json",
    })

    server_log = temp / "server-output.log"
    log_handle = server_log.open("w", encoding="utf-8", buffering=1)
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "one_crm_server.py")],
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    success = False
    try:
        step("Inicialização isolada do servidor")
        wait_server(process, server_log)

        step("Interface, identidade e navegação")
        index_html = read_url("/")
        app_js = read_url("/static/app.js")
        assert b"ONE CRM" in index_html
        assert b"one-crm-logo.svg" in index_html
        assert b'id="top-nav"' in index_html
        assert b'id="context-subnav"' in index_html
        assert b'id="sidebar"' not in index_html
        assert b"renderDashboard" in app_js
        assert b"navigationItems" in app_js
        assert b"Administrativo" in app_js
        assert b"Resumo de hoje" not in app_js
        assert b"ANNIE Intelligence" not in app_js
        assert b"lookupCepInBrowser" in app_js

        step("Primeiro Dono, perfil e tema")
        owner = Client()
        assert owner.request("/api/bootstrap")["setup_required"] is True
        owner.request("/api/setup", "POST", {"name": "Dono", "email": "owner@test.local", "password": "Owner1234"}, 201)
        owner_boot = owner.request("/api/bootstrap")
        owner.csrf = owner_boot["csrf_token"]
        assert owner_boot["user"]["role_code"] == "owner"
        profile = owner.request("/api/me/profile", "PUT", {"name": "Dono Principal", "display_name": "Jorla", "email": "owner@test.local", "phone": "(61) 99111-1111", "bio": "Administração do CRM"})
        assert profile["user"]["display_name"] == "Jorla"
        assert profile["user"]["phone"] == "61991111111"
        owner.request("/api/me/theme", "PUT", {"theme": "light"})
        assert owner.request("/api/me")["user"]["theme_preference"] == "light"

        step("Cargos personalizados, equipes, usuários e planos")
        role_created = owner.request("/api/roles", "POST", {
            "name": "Supervisor",
            "code": "supervisor",
            "description": "Acompanha a operação sem administrar o sistema",
            "base_role": "manager",
            "permissions": ["dashboard.view", "sales.all", "daily.view", "users.view", "ranking.all"],
        }, 201)
        assert role_created["code"] == "supervisor"
        roles = owner.request("/api/roles")["roles"]
        assert any(role["code"] == "supervisor" and role["base_role"] == "manager" for role in roles)
        team = owner.request("/api/teams", "POST", {"name": "Equipe Teste", "monthly_target": 30}, 201)["id"]
        seller1 = owner.request("/api/users", "POST", {"name": "Seller Um", "email": "s1@test.local", "password": "Seller123", "role_code": "seller", "team_id": team}, 201)["id"]
        seller2 = owner.request("/api/users", "POST", {"name": "Seller Dois", "email": "s2@test.local", "password": "Seller123", "role_code": "seller", "team_id": team}, 201)["id"]
        bko_id = owner.request("/api/users", "POST", {"name": "BKO", "email": "bko@test.local", "password": "Backoffice1", "role_code": "bko"}, 201)["id"]
        manager_id = owner.request("/api/users", "POST", {"name": "Gerente", "email": "manager@test.local", "password": "Manager123", "role_code": "manager"}, 201)["id"]
        supervisor_id = owner.request("/api/users", "POST", {"name": "Supervisor Teste", "email": "supervisor@test.local", "password": "Supervisor1", "role_code": "supervisor"}, 201)["id"]
        plan = owner.request("/api/plans")["plans"][0]["id"]

        step("Cadastro, documento, telefone e fluxo de vendas")
        sale1 = owner.request("/api/sales", "POST", {"client_name": "Cliente Um", "person_type": "CPF", "cpf_cnpj": "529.982.247-25", "phone": "(61) 99999-9991", "cep": "01001-000", "address": "Praça da Sé", "address_number": "1", "neighborhood": "Sé", "city": "São Paulo", "uf": "SP", "plan_id": plan, "seller_id": seller1}, 201)["id"]
        sale2 = owner.request("/api/sales", "POST", {"client_name": "Cliente Dois", "person_type": "CPF", "cpf_cnpj": "111.444.777-35", "phone": "(61) 99999-9992", "cep": "70040-010", "address": "Esplanada dos Ministérios", "address_number": "1", "neighborhood": "Zona Cívico-Administrativa", "city": "Brasília", "uf": "DF", "plan_id": plan, "seller_id": seller2}, 201)["id"]
        owner.request(f"/api/sales/{sale1}/workflow", "PUT", {"installation_status": "instalado", "biometric_status": "biometria_ok", "bko_user_id": bko_id})

        step("Consulta de CEP, fallback e cache")
        owner.request("/api/cep/123", expected=400)
        via_result = owner.request("/api/cep/72410200")["address"]
        assert via_result["city"] == "Brasília" and via_result["source"] == "ViaCEP", via_result
        brasil_result = owner.request("/api/cep/72862504")["address"]
        assert brasil_result["city"] == "Novo Gama" and brasil_result["source"].startswith("BrasilAPI"), brasil_result
        owner.request("/api/cep/99999999", expected=404)
        with sqlite3.connect(temp / "one_crm.db") as conn:
            conn.execute(
                """INSERT INTO cep_cache(cep,street,complement,neighborhood,city,uf,ddd,ibge,payload_json,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("01001000", "Praça da Sé", "lado ímpar", "Sé", "São Paulo", "SP", "11", "3550308", "{}", "2026-08-01T00:00:00"),
            )
        cep_result = owner.request("/api/cep/01001000")["address"]
        assert cep_result["street"] == "Praça da Sé" and cep_result["source"] == "Cache local"
        refreshed_cache = owner.request("/api/cep/01001000?refresh=1")["address"]
        assert refreshed_cache["source"] == "Cache local" and "fontes externas" in refreshed_cache.get("warning", "")
        detail = owner.request(f"/api/sales/{sale1}")["sale"]
        assert detail["cpf_cnpj"] == "52998224725"
        assert detail["phone"] == "61999999991"

        step("Restrições e ranking do Vendedor")
        seller = Client()
        seller.login("s2@test.local", "Seller123")
        seller_sales = seller.request("/api/sales")["sales"]
        assert {item["id"] for item in seller_sales} == {sale2}
        seller_rank = seller.request("/api/ranking")["ranking"]
        assert len(seller_rank) == 1 and seller_rank[0]["id"] == seller2
        assert seller_rank[0]["position"] == 2, seller_rank
        seller.request("/api/users", expected=403)
        seller.request(f"/api/sales/{sale2}/workflow", "PUT", {"biometric_status": "biometria_ok"}, expected=403)

        step("Cargo personalizado e herança operacional")
        supervisor = Client()
        supervisor_user = supervisor.login("supervisor@test.local", "Supervisor1")
        assert supervisor_user["role_code"] == "supervisor"
        assert supervisor_user["base_role"] == "manager"
        assert supervisor_user["role_name"] == "Supervisor"
        assert "sales.all" in supervisor_user["permissions"]
        assert len(supervisor.request("/api/sales")["sales"]) == 2
        supervisor.request("/api/users", "POST", {"name": "Nope"}, expected=403)

        step("Visão global e limitações do Gerente")
        manager = Client()
        manager.login("manager@test.local", "Manager123")
        assert len(manager.request("/api/sales")["sales"]) == 2
        assert len(manager.request("/api/users")["users"]) == 6
        manager.request("/api/users", "POST", {"name": "Nope"}, expected=403)
        assert manager.request("/api/daily-analysis")["teams"]
        manager.request("/api/intelligence")
        assert manager.request("/api/powerbi")["embed_url"] == ""

        step("Escopo e tratamento do BKO")
        bko = Client()
        bko.login("bko@test.local", "Backoffice1")
        # O 403 abaixo é esperado e confirma que o BKO não administra usuários.
        bko.request("/api/users", expected=403)
        visible = bko.request("/api/sales")["sales"]
        assert {item["id"] for item in visible} == {sale1, sale2}
        bko.request(f"/api/sales/{sale2}/workflow", "PUT", {"activation_status": "ativado_pinga"})
        owner.request(f"/api/sales/{sale2}/workflow", "PUT", {"bko_user_id": manager_id})
        visible_after = bko.request("/api/sales")["sales"]
        assert {item["id"] for item in visible_after} == {sale1}

        step("Proteções do Dono e backup")
        owner.request(f"/api/users/{owner_boot['user']['id']}", "PUT", {"active": False}, expected=400)
        owner.request("/api/roles/owner", "PUT", {"permissions": []}, expected=400)
        owner.request("/api/roles/supervisor", "PUT", {"active": False}, expected=400)
        owner.request("/api/roles/supervisor", "PUT", {"name": "Supervisão", "permissions": ["dashboard.view", "sales.all"]})
        updated_roles = owner.request("/api/roles")["roles"]
        assert any(role["code"] == "supervisor" and role["name"] == "Supervisão" for role in updated_roles)
        owner.request("/api/backups", "POST", {}, 201)

        success = True
        print("\nSMOKE TEST: OK", flush=True)
        print("Todos os testes funcionais passaram sem alterar o banco real.", flush=True)
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log_handle.close()
        if not success and server_log.exists():
            print("\n--- ÚLTIMAS LINHAS DO SERVIDOR DE TESTE ---", flush=True)
            output = server_log.read_text(encoding="utf-8", errors="replace")
            print(output[-5000:], flush=True)
        cep_server.shutdown()
        cep_server.server_close()
        shutil.rmtree(temp, ignore_errors=True)
        try:
            (ROOT / "server.pid").unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
