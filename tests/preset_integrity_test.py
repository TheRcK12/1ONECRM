from __future__ import annotations

import http.cookiejar
import importlib.util
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


def load_templates():
    spec = importlib.util.spec_from_file_location("onecrm_profiles_integrity", ROOT / "one_crm_profiles.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module.PROFILE_TEMPLATES


def schema_test() -> None:
    templates = load_templates()
    allowed_types = {"text", "textarea", "number", "date", "email", "tel", "url", "catalog", "record", "plan"}
    for code, template in templates.items():
        catalogs = set(template.get("catalogs", {})) | set(template.get("catalog_labels", {}))
        records = template.get("records", {})
        modules = set(template.get("modules", []))
        for module, config in records.items():
            assert module in modules, (code, module, "record fora dos módulos")
            assert "due_label" in config, (code, module, "due_label implícito")
            assert "amount_label" in config, (code, module, "amount_label implícito")
            for field in config.get("fields", []):
                field_type = field.get("type", "text")
                assert field_type in allowed_types, (code, module, field)
                if field_type == "catalog":
                    assert field.get("category") in catalogs, (code, module, field, "catálogo de outro perfil")
                if field_type == "record":
                    target = field.get("module")
                    assert target in records and target in modules, (code, module, field, "referência inválida")

    recruitment = templates["recruitment"]
    candidate = recruitment["records"]["candidates"]
    vacancy_field = next(field for field in candidate["fields"] if field["key"] == "vacancy")
    assert candidate["amount_label"] is False
    assert candidate["due_label"] is False
    assert vacancy_field["type"] == "record" and vacancy_field["module"] == "vacancies"
    assert "aberta" in vacancy_field.get("status_in", [])
    assert next(field for field in candidate["fields"] if field["key"] == "source")["type"] == "catalog"

    relation_expectations = {
        ("services", "service_orders", "client"): "clients",
        ("general_crm", "opportunities", "client"): "leads",
        ("collections", "negotiations", "debtor"): "debtors",
        ("after_sales", "tickets", "customer"): "customers",
        ("real_estate", "visits", "property"): "properties",
        ("real_estate", "visits", "client"): "real_estate_leads",
        ("retail", "orders", "customer"): "customers",
        ("consulting", "projects", "client"): "clients",
        ("recruitment", "interviews", "candidate"): "candidates",
        ("recruitment", "interviews", "vacancy"): "vacancies",
    }
    for (preset, module, key), target in relation_expectations.items():
        field = next(item for item in templates[preset]["records"][module]["fields"] if item["key"] == key)
        assert field["type"] == "record" and field["module"] == target, (preset, module, key)


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


def code_for(catalogs, category: str, label: str) -> str:
    return next(item["code"] for item in catalogs[category] if item["label"] == label)


def api_test() -> None:
    global BASE
    temp = Path(tempfile.mkdtemp(prefix="onecrm_preset_integrity_"))
    port = free_port()
    BASE = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update({"ONE_CRM_DATA_DIR": str(temp), "ONE_CRM_PORT": str(port), "ONE_CRM_NO_BROWSER": "1"})
    process = subprocess.Popen([sys.executable, str(ROOT / "one_crm_server.py")], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        wait_server(process)
        owner = Client()
        owner.request("/api/setup", "POST", {"name": "Dono", "email": "owner@integrity.local", "password": "Owner1234"}, 201)
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]

        created = owner.request("/api/profiles", "POST", {"name": "RH Teste", "business_type": "recruitment"}, 201)
        owner.request("/api/profiles/switch", "POST", {"profile_id": created["id"]})
        boot = owner.request("/api/bootstrap")
        owner.csrf = boot["csrf_token"]

        catalogs = owner.request("/api/catalogs?all=1")["catalogs"]
        expected_categories = {
            "vacancy_status", "candidate_stage", "interview_status", "task_status", "hr_department",
            "work_model", "employment_type", "candidate_source", "interview_format", "task_priority",
        }
        assert set(catalogs) == expected_categories, set(catalogs)
        assert "biometric_status" not in catalogs and "property_type" not in catalogs

        role_data = owner.request("/api/roles")
        role_names = {item["name"].split(" · ")[0] for item in role_data["roles"]}
        assert role_names == {"Coordenador de RH", "Recrutador", "Assistente de RH"}, role_names
        assert {item["code"] for item in role_data["base_roles"]} == {"manager", "bko", "seller"}
        permission_codes = {item["code"] for item in role_data["permissions"]}
        assert "candidates.manage" in permission_codes
        assert "sales.create" not in permission_codes
        assert "workflow.bko" not in permission_codes

        vacancy_status = code_for(catalogs, "vacancy_status", "Aberta")
        department = code_for(catalogs, "hr_department", "Tecnologia")
        work_model = code_for(catalogs, "work_model", "Remoto")
        employment_type = code_for(catalogs, "employment_type", "CLT")
        vacancy = owner.request("/api/profile-records", "POST", {
            "module": "vacancies", "title": "DEV JUNIOR", "status": vacancy_status, "due_date": "2026-09-01",
            "data": {"department": department, "location": "Brasília", "work_model": work_model,
                     "employment_type": employment_type, "positions": 1, "salary_min": 2500, "salary_max": 3500},
        }, 201)["id"]

        candidate_config = owner.request("/api/profile-records?module=candidates")["config"]
        assert candidate_config["amount_label"] is False and candidate_config["due_label"] is False
        source = code_for(catalogs, "candidate_source", "LinkedIn")
        stage = code_for(catalogs, "candidate_stage", "Inscrito")
        candidate = owner.request("/api/profile-records", "POST", {
            "module": "candidates", "title": "Candidato Teste", "status": stage,
            "data": {"phone": "61999999999", "email": "candidate@example.com", "vacancy": vacancy, "source": source},
        }, 201)
        assert candidate["id"] > 0
        owner.request("/api/profile-records", "POST", {
            "module": "candidates", "title": "Referência inválida", "status": stage,
            "data": {"vacancy": 999999, "source": source},
        }, 400)

        # A API também bloqueia a criação de categorias alheias ao preset.
        owner.request("/api/catalogs", "POST", {"category": "biometric_status", "label": "Não deveria existir"}, 400)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(temp, ignore_errors=True)


def main() -> int:
    schema_test()
    api_test()
    print("PRESET INTEGRITY TEST: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
