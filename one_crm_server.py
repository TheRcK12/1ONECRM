from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from one_crm_ai import (
    AIAuthenticationError,
    AIConfigurationError,
    AIConnectionError,
    AIRateLimitError,
    create_ai_response,
    public_ai_status,
    test_ai_connection,
)

APP_NAME = "ONE CRM"
APP_VERSION = "1.9.0-beta.1"
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
IS_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_PROJECT_ID")
    or os.getenv("RAILWAY_SERVICE_ID")
)
RAILWAY_VOLUME_PATH = (os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()

if RAILWAY_VOLUME_PATH:
    # Railway injeta este caminho automaticamente quando um Volume é anexado.
    DEFAULT_DATA_DIR = Path(RAILWAY_VOLUME_PATH)
elif os.name == "nt" and os.getenv("LOCALAPPDATA"):
    _local_appdata = Path(os.environ["LOCALAPPDATA"])
    _new_data_dir = _local_appdata / "ONE_CRM"
    _legacy_data_dir = _local_appdata / "ANNIE_X"
    _legacy_db = _legacy_data_dir / "annie_x.db"
    DEFAULT_DATA_DIR = _legacy_data_dir if _legacy_db.exists() and not (_new_data_dir / "one_crm.db").exists() else _new_data_dir
else:
    DEFAULT_DATA_DIR = BASE_DIR / "data"

DATA_DIR = Path(os.getenv("ONE_CRM_DATA_DIR", os.getenv("ANNIE_DATA_DIR", str(DEFAULT_DATA_DIR)))).resolve()
DB_PATH = DATA_DIR / ("annie_x.db" if (DATA_DIR / "annie_x.db").exists() and not (DATA_DIR / "one_crm.db").exists() else "one_crm.db")
BACKUP_DIR = DATA_DIR / "backups"
DEFAULT_LOG_DIR = DATA_DIR / "logs" if IS_RAILWAY or RAILWAY_VOLUME_PATH else BASE_DIR / "logs"
LOG_DIR = Path(os.getenv("ONE_CRM_LOG_DIR", str(DEFAULT_LOG_DIR))).resolve()
CONFIG_PATH = BASE_DIR / "config.json"
PID_PATH = Path(os.getenv("ONE_CRM_PID_PATH", "/tmp/one_crm.pid" if IS_RAILWAY else str(BASE_DIR / "server.pid")))
MAX_BODY = 2 * 1024 * 1024
COOKIE_NAME = "onecrm_session"
SECURE_COOKIES = (
    os.getenv("ONE_CRM_SECURE_COOKIES", "1" if IS_RAILWAY else "0").strip().lower()
    not in {"0", "false", "no", "off"}
)
TRUST_PROXY_HEADERS = (
    os.getenv("ONE_CRM_TRUST_PROXY_HEADERS", "1" if IS_RAILWAY else "0").strip().lower()
    not in {"0", "false", "no", "off"}
)
SETUP_TOKEN = (os.getenv("ONE_CRM_SETUP_TOKEN") or "").strip()
SETUP_LOCK = threading.Lock()
LOG_MAX_BYTES = max(256 * 1024, int(os.getenv("ONE_CRM_LOG_MAX_BYTES", str(5 * 1024 * 1024))))

DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_LOCK = threading.Lock()
AI_RATE_LOCK = threading.Lock()
AI_RATE_BUCKETS: dict[int, list[float]] = {}
AI_RATE_LIMIT = max(1, int(os.getenv("ONE_CRM_AI_RATE_LIMIT", "10")))
AI_RATE_WINDOW_SECONDS = max(10, int(os.getenv("ONE_CRM_AI_RATE_WINDOW_SECONDS", "60")))


# ------------------------- utilidades -------------------------

def utc_now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def local_today() -> str:
    return date.today().isoformat()


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def only_digits(value: str) -> str:
    return "".join(ch for ch in (value or "") if ch.isdigit())


def redact_ai_text(value: Any, max_length: int = 800) -> str:
    """Remove identificadores óbvios antes de incluir texto livre no contexto da IA."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[e-mail omitido]", text)
    text = re.sub(r"(?<!\d)(?:\+?55\s*)?(?:\(?\d{2}\)?[\s.-]*)?9?\d{4}[\s.-]*\d{4}(?!\d)", "[telefone omitido]", text)
    text = re.sub(r"(?<!\d)\d{3}[.\s-]?\d{3}[.\s-]?\d{3}[-\s]?\d{2}(?!\d)", "[documento omitido]", text)
    text = re.sub(r"(?<!\d)\d{2}[.\s-]?\d{3}[.\s-]?\d{3}[\/\s-]?\d{4}[-\s]?\d{2}(?!\d)", "[documento omitido]", text)
    return text[:max_length]


BRAZILIAN_DDDS = {
    "11","12","13","14","15","16","17","18","19","21","22","24","27","28",
    "31","32","33","34","35","37","38","41","42","43","44","45","46","47",
    "48","49","51","53","54","55","61","62","63","64","65","66","67","68",
    "69","71","73","74","75","77","79","81","82","83","84","85","86","87",
    "88","89","91","92","93","94","95","96","97","98","99"
}


def validate_cpf(value: str) -> bool:
    digits = only_digits(value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(digits[index]) * (size + 1 - index) for index in range(size))
        check = (total * 10) % 11
        if check == 10:
            check = 0
        if check != int(digits[size]):
            return False
    return True


def validate_cnpj(value: str) -> bool:
    digits = only_digits(value)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False
    def digit(base: str, weights: list[int]) -> int:
        remainder = sum(int(number) * weight for number, weight in zip(base, weights)) % 11
        return 0 if remainder < 2 else 11 - remainder
    first = digit(digits[:12], [5,4,3,2,9,8,7,6,5,4,3,2])
    second = digit(digits[:12] + str(first), [6,5,4,3,2,9,8,7,6,5,4,3,2])
    return digits[-2:] == f"{first}{second}"


def normalize_mobile_phone(value: str) -> str:
    digits = only_digits(value)
    if len(digits) in (12, 13) and digits.startswith("55"):
        digits = digits[2:]
    if len(digits) == 10:
        digits = digits[:2] + "9" + digits[2:]
    if len(digits) != 11 or digits[:2] not in BRAZILIAN_DDDS or digits[2] != "9":
        return ""
    return digits


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class CepNotFoundError(Exception):
    """O provedor respondeu corretamente, mas não possui o CEP."""


class CepProviderError(Exception):
    """O provedor não respondeu, respondeu inválido ou ficou indisponível."""


CEP_PROVIDER_URLS = {
    "BrasilAPI": os.getenv("ONE_CRM_CEP_BRASILAPI_URL", "https://brasilapi.com.br/api/cep/v2/{cep}"),
    "ViaCEP": os.getenv("ONE_CRM_CEP_VIACEP_URL", "https://viacep.com.br/ws/{cep}/json/"),
    "OpenCEP": os.getenv("ONE_CRM_CEP_OPENCEP_URL", "https://opencep.com/v1/{cep}.json"),
}


def fetch_cep_json(provider: str, cep: str, attempts: int = 2, timeout: float = 6.0) -> dict[str, Any]:
    """Consulta um provedor com repetição curta para falhas transitórias."""
    url = CEP_PROVIDER_URLS[provider].format(cep=cep)
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": f"ONE-CRM/{APP_VERSION}",
                "Cache-Control": "no-cache",
                "Connection": "close",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(512 * 1024 + 1)
                if len(raw) > 512 * 1024:
                    raise CepProviderError(f"{provider} devolveu uma resposta grande demais")
                payload = json.loads(raw.decode("utf-8-sig"))
                if not isinstance(payload, dict):
                    raise CepProviderError(f"{provider} devolveu um formato inesperado")
                return payload
        except urllib.error.HTTPError as exc:
            if exc.code in {400, 404, 422}:
                raise CepNotFoundError(f"{provider} não encontrou o CEP") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError, CepProviderError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(0.25 * (attempt + 1))
    raise CepProviderError(f"{provider} indisponível: {last_error}")


def normalize_cep_payload(provider: str, cep: str, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("erro") is True or payload.get("error") is True:
        raise CepNotFoundError(f"{provider} não encontrou o CEP")

    if provider == "BrasilAPI":
        street = payload.get("street") or payload.get("logradouro") or ""
        complement = payload.get("complement") or payload.get("complemento") or ""
        neighborhood = payload.get("neighborhood") or payload.get("bairro") or ""
        city = payload.get("city") or payload.get("localidade") or ""
        uf = payload.get("state") or payload.get("uf") or ""
        ddd = payload.get("ddd") or ""
        ibge = payload.get("ibge") or ""
        source_detail = payload.get("service") or "múltiplas fontes"
        source = f"BrasilAPI · {source_detail}"
    else:
        street = payload.get("logradouro") or payload.get("street") or ""
        complement = payload.get("complemento") or payload.get("complement") or ""
        neighborhood = payload.get("bairro") or payload.get("neighborhood") or ""
        city = payload.get("localidade") or payload.get("city") or ""
        uf = payload.get("uf") or payload.get("state") or ""
        ddd = payload.get("ddd") or ""
        ibge = payload.get("ibge") or ""
        source = provider

    result = {
        "cep": cep,
        "street": str(street).strip(),
        "complement": str(complement).strip(),
        "neighborhood": str(neighborhood).strip(),
        "city": str(city).strip(),
        "uf": str(uf).strip().upper(),
        "ddd": only_digits(str(ddd))[:2],
        "ibge": only_digits(str(ibge)),
        "source": source,
        "cached": False,
    }
    if not result["city"] or len(result["uf"]) != 2:
        raise CepProviderError(f"{provider} devolveu endereço incompleto")
    if not result["street"]:
        result["warning"] = "CEP geral encontrado. Preencha o logradouro e o número manualmente."
    return result


def lookup_cep_from_providers(cep: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str], list[str]]:
    """Tenta fontes independentes. Retorna resultado, payload, falhas e fontes sem cadastro."""
    failures: list[str] = []
    not_found: list[str] = []
    for provider in ("BrasilAPI", "ViaCEP", "OpenCEP"):
        try:
            payload = fetch_cep_json(provider, cep)
            return normalize_cep_payload(provider, cep, payload), payload, failures, not_found
        except CepNotFoundError as exc:
            not_found.append(provider)
            log(f"Consulta CEP {cep}: {exc}")
        except CepProviderError as exc:
            failures.append(provider)
            log(f"Consulta CEP {cep}: {exc}")
    return None, None, failures, not_found


def load_config() -> dict[str, Any]:
    default = {
        "host": "0.0.0.0" if IS_RAILWAY else "127.0.0.1",
        "port": 8000,
        "open_browser": not IS_RAILWAY,
        "session_hours": 12,
        "automatic_daily_backup": True,
        "automatic_backup_retention": 14,
    }
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            default.update(data)
    except Exception:
        pass
    return default


def log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    text = f"[{stamp}] {message}"
    # O servidor é multithread. O bloqueio evita linhas misturadas e reduz
    # comportamento imprevisível quando testes redirecionam a saída.
    with LOG_LOCK:
        print(text, flush=True)
        try:
            log_path = LOG_DIR / "one_crm.log"
            if log_path.exists() and log_path.stat().st_size >= LOG_MAX_BYTES:
                rotated = LOG_DIR / "one_crm.log.1"
                rotated.unlink(missing_ok=True)
                log_path.replace(rotated)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except Exception:
            pass


# ------------------------- banco -------------------------

def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def dict_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def init_database() -> None:
    schema = r"""
    PRAGMA journal_mode = WAL;
    PRAGMA synchronous = NORMAL;

    CREATE TABLE IF NOT EXISTS teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        manager_id INTEGER,
        monthly_target INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(manager_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS roles (
        code TEXT PRIMARY KEY,
        name TEXT NOT NULL UNIQUE COLLATE NOCASE,
        description TEXT NOT NULL DEFAULT '',
        base_role TEXT NOT NULL CHECK(base_role IN ('owner','manager','bko','seller')),
        is_system INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        display_name TEXT,
        email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        phone TEXT,
        bio TEXT,
        theme_preference TEXT NOT NULL DEFAULT 'dark' CHECK(theme_preference IN ('dark','light')),
        password_hash TEXT NOT NULL,
        role_code TEXT NOT NULL CHECK(role_code IN ('owner','manager','bko','seller')),
        custom_role_code TEXT,
        team_id INTEGER,
        active INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 0,
        last_login_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS permissions (
        code TEXT PRIMARY KEY,
        module TEXT NOT NULL,
        description TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS role_permissions (
        role_code TEXT NOT NULL,
        permission_code TEXT NOT NULL,
        allowed INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY(role_code, permission_code),
        FOREIGN KEY(role_code) REFERENCES roles(code) ON DELETE CASCADE,
        FOREIGN KEY(permission_code) REFERENCES permissions(code) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        csrf_token TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS login_attempts (
        identity TEXT PRIMARY KEY,
        failed_count INTEGER NOT NULL DEFAULT 0,
        first_failed_at TEXT,
        blocked_until TEXT
    );

    CREATE TABLE IF NOT EXISTS catalog_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        code TEXT NOT NULL,
        label TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(category, code)
    );

    CREATE TABLE IF NOT EXISTS cep_cache (
        cep TEXT PRIMARY KEY,
        street TEXT,
        complement TEXT,
        neighborhood TEXT,
        city TEXT NOT NULL,
        uf TEXT NOT NULL,
        ddd TEXT,
        ibge TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL,
        service TEXT NOT NULL,
        name TEXT NOT NULL,
        speed TEXT,
        price REAL NOT NULL DEFAULT 0,
        benefits TEXT,
        uf_list TEXT,
        sort_order INTEGER NOT NULL DEFAULT 0,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_type TEXT NOT NULL DEFAULT 'CPF',
        client_name TEXT NOT NULL,
        cpf_cnpj TEXT,
        birth_date TEXT,
        mother_name TEXT,
        phone TEXT NOT NULL,
        contact_phone TEXT,
        email TEXT,
        cep TEXT,
        address TEXT,
        address_number TEXT,
        complement TEXT,
        neighborhood TEXT,
        city TEXT,
        uf TEXT,
        property_type TEXT,
        plan_id INTEGER,
        plan_name_snapshot TEXT NOT NULL,
        plan_price_snapshot REAL NOT NULL DEFAULT 0,
        provider TEXT,
        service TEXT,
        payment_method TEXT,
        due_day TEXT,
        channel TEXT,
        suggested_date TEXT,
        suggested_period TEXT,
        notes TEXT,
        seller_id INTEGER NOT NULL,
        team_id INTEGER,
        bko_user_id INTEGER,
        status TEXT NOT NULL DEFAULT 'nova',
        activation_status TEXT NOT NULL DEFAULT 'aguardando_ativacao',
        biometric_status TEXT NOT NULL DEFAULT 'biometria_pendente',
        installation_status TEXT NOT NULL DEFAULT 'aguardando_instalacao',
        appointment_status TEXT,
        appointment_date TEXT,
        appointment_period TEXT,
        os_number TEXT,
        bypass_required INTEGER NOT NULL DEFAULT 0,
        handling_biometric INTEGER NOT NULL DEFAULT 0,
        handling_installation INTEGER NOT NULL DEFAULT 0,
        cancelled_reason TEXT,
        installed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(plan_id) REFERENCES plans(id) ON DELETE SET NULL,
        FOREIGN KEY(seller_id) REFERENCES users(id) ON DELETE RESTRICT,
        FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE SET NULL,
        FOREIGN KEY(bko_user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE INDEX IF NOT EXISTS idx_sales_seller ON sales(seller_id);
    CREATE INDEX IF NOT EXISTS idx_sales_team ON sales(team_id);
    CREATE INDEX IF NOT EXISTS idx_sales_bko ON sales(bko_user_id);
    CREATE INDEX IF NOT EXISTS idx_sales_created ON sales(created_at);
    CREATE INDEX IF NOT EXISTS idx_sales_status ON sales(status);
    CREATE INDEX IF NOT EXISTS idx_sales_phone ON sales(phone);

    CREATE TABLE IF NOT EXISTS sale_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sale_id INTEGER NOT NULL,
        user_id INTEGER,
        event_type TEXT NOT NULL,
        field_name TEXT,
        old_value TEXT,
        new_value TEXT,
        details TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE CASCADE,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        action TEXT NOT NULL,
        entity_type TEXT,
        entity_id TEXT,
        details TEXT,
        ip_address TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS system_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        secret INTEGER NOT NULL DEFAULT 0,
        updated_by INTEGER,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS ai_usage_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        sale_id INTEGER,
        response_id TEXT,
        provider TEXT,
        model TEXT,
        fallback_used INTEGER NOT NULL DEFAULT 0,
        question_length INTEGER NOT NULL DEFAULT 0,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL,
        error_code TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL,
        FOREIGN KEY(sale_id) REFERENCES sales(id) ON DELETE SET NULL
    );

    CREATE INDEX IF NOT EXISTS idx_ai_usage_user_created ON ai_usage_logs(user_id,created_at);
    """
    with db_connect() as conn:
        conn.executescript(schema)
        # Migração segura para bancos criados por versões anteriores do ANNIE X.
        existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        migrations = {
            "display_name": "ALTER TABLE users ADD COLUMN display_name TEXT",
            "phone": "ALTER TABLE users ADD COLUMN phone TEXT",
            "bio": "ALTER TABLE users ADD COLUMN bio TEXT",
            "theme_preference": "ALTER TABLE users ADD COLUMN theme_preference TEXT NOT NULL DEFAULT 'dark'",
            "custom_role_code": "ALTER TABLE users ADD COLUMN custom_role_code TEXT",
        }
        for column, statement in migrations.items():
            if column not in existing_columns:
                conn.execute(statement)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_custom_role ON users(custom_role_code)")
        ai_columns = {row[1] for row in conn.execute("PRAGMA table_info(ai_usage_logs)").fetchall()}
        if "provider" not in ai_columns:
            conn.execute("ALTER TABLE ai_usage_logs ADD COLUMN provider TEXT")
        if "fallback_used" not in ai_columns:
            conn.execute("ALTER TABLE ai_usage_logs ADD COLUMN fallback_used INTEGER NOT NULL DEFAULT 0")
    seed_database()


PERMISSIONS = [
    ("dashboard.view", "Dashboard", "Visualizar indicadores"),
    ("sales.own", "Vendas", "Visualizar as próprias vendas"),
    ("sales.all", "Vendas", "Visualizar todas as vendas"),
    ("sales.create", "Vendas", "Cadastrar vendas"),
    ("sales.edit_own", "Vendas", "Editar as próprias vendas"),
    ("sales.edit_all", "Vendas", "Editar qualquer venda"),
    ("workflow.bko", "Back-office", "Tratar ativação, biometria e instalação"),
    ("workflow.assign", "Back-office", "Atribuir vendas ao BKO"),
    ("ranking.own", "Ranking", "Visualizar a própria posição"),
    ("ranking.all", "Ranking", "Visualizar ranking completo"),
    ("daily.view", "Análise", "Visualizar análise diária por equipe"),
    ("users.view", "Funcionários", "Visualizar funcionários"),
    ("users.manage", "Funcionários", "Criar e administrar usuários"),
    ("teams.view", "Equipes", "Visualizar equipes"),
    ("teams.manage", "Equipes", "Administrar equipes"),
    ("plans.manage", "Cadastros", "Administrar planos"),
    ("catalogs.manage", "Cadastros", "Administrar opções e status"),
    ("roles.manage", "Segurança", "Administrar permissões dos cargos"),
    ("audit.view", "Auditoria", "Visualizar logs de auditoria"),
    ("intelligence.view", "Inteligência", "Visualizar inteligência operacional"),
    ("ai.use", "Inteligência", "Utilizar o assistente ONE Intelligence"),
    ("powerbi.view", "Relatórios", "Visualizar o painel Power BI"),
    ("backups.manage", "Sistema", "Criar e listar backups"),
    ("integrations.manage", "Sistema", "Administrar integrações"),
    ("export.data", "Relatórios", "Exportar dados"),
]

SYSTEM_ROLES = {
    "owner": ("Dono", "Acesso total e proteção administrativa", "owner"),
    "manager": ("Gerente", "Gestão completa da operação", "manager"),
    "bko": ("BKO", "Tratamento operacional das vendas", "bko"),
    "seller": ("Vendedor", "Operação comercial individual", "seller"),
}

ROLE_DEFAULTS = {
    "seller": {
        "dashboard.view", "sales.own", "sales.create", "sales.edit_own", "ranking.own"
    },
    "bko": {
        "dashboard.view", "workflow.bko", "sales.own", "teams.view"
    },
    "manager": {
        "dashboard.view", "sales.all", "sales.create", "sales.edit_all",
        "workflow.bko", "workflow.assign", "ranking.all", "daily.view",
        "users.view", "teams.view", "intelligence.view", "ai.use", "powerbi.view", "export.data"
    },
}

CATALOG_SEED: dict[str, list[tuple[str, str]]] = {
    "provider": [("tim", "TIM"), ("nio", "NIO"), ("vero", "VERO")],
    "service": [("fibra", "Fibra"), ("movel", "Móvel")],
    "sale_status": [
        ("nova", "Nova"), ("em_tratamento", "Em Tratamento"),
        ("cancelada", "Cancelada"), ("instalada", "Instalada")
    ],
    "activation_status": [
        ("aguardando_ativacao", "Aguard. Ativação"),
        ("ativado_pinga", "Ativado - Pinga"),
        ("ativado_trash", "Ativado - Trash"),
        ("nao_ativado", "Não Ativado")
    ],
    "biometric_status": [
        ("biometria_pendente", "Biometria Pendente"),
        ("prometeu_biometria", "Prometeu Biometria"),
        ("retorno_biometria", "Retorno Biometria"),
        ("biometria_ok", "Biometria OK"),
        ("biometria_bko", "Biometria BKO"),
        ("nao_cadastrado", "Não Cadastrado")
    ],
    "installation_status": [
        ("aguardando_ativacao", "Aguard. Ativação"),
        ("aguardando_instalacao", "Aguard. Instalação"),
        ("concluido_sem_sucesso", "Concluído S/Sucesso"),
        ("aguardando_cartao", "Aguard. Cartão Crédito"),
        ("solicitar_reagendamento", "Solicitar Reagendamento"),
        ("instalado", "Instalado"),
        ("instalado_regra_pdv", "Instalado - Regra PDV"),
        ("nao_instalado", "Não Instalado")
    ],
    "appointment_status": [
        ("aguardando_agendamento", "Aguard. Agendamento"),
        ("agendado", "Agendado"),
        ("reagendamento", "Reagendamento"),
        ("concluido", "Concluído")
    ],
    "payment_method": [
        ("boleto", "Boleto"), ("dacc", "DACC"),
        ("cartao_credito", "Cartão de Crédito"), ("e_dacc", "E-DACC")
    ],
    "due_day": [("1", "1"), ("7", "7"), ("10", "10"), ("12", "12"), ("15", "15"), ("20", "20")],
    "sales_channel": [
        ("whatsapp", "WhatsApp"), ("ura_1", "URA 1"), ("ura_2", "URA 2"),
        ("ura_3", "URA 3"), ("ura_4", "URA 4"), ("indicacao", "Indicação"),
        ("presencial", "Presencial")
    ],
    "period": [("manha", "Manhã"), ("tarde", "Tarde")],
    "property_type": [
        ("casa", "Casa"), ("apartamento", "Apartamento"),
        ("comercial", "Comercial"), ("condominio", "Condomínio")
    ],
    "cancellation_reason": [
        ("sem_viabilidade", "Sem viabilidade"),
        ("desistencia", "Desistência do cliente"),
        ("reprovacao", "Reprovação"),
        ("area_risco", "Área de risco"),
        ("duplicidade", "Duplicidade")
    ],
}


def seed_database() -> None:
    now = utc_now()
    with db_connect() as conn:
        for code, (name, description, base_role) in SYSTEM_ROLES.items():
            conn.execute(
                """INSERT OR IGNORE INTO roles
                (code,name,description,base_role,is_system,active,created_at,updated_at)
                VALUES(?,?,?,?,1,1,?,?)""",
                (code, name, description, base_role, now, now),
            )
            conn.execute(
                """UPDATE roles SET name=?,description=?,base_role=?,is_system=1,active=1,updated_at=?
                WHERE code=?""",
                (name, description, base_role, now, code),
            )
        conn.executemany(
            "INSERT OR IGNORE INTO permissions(code,module,description) VALUES(?,?,?)",
            PERMISSIONS,
        )
        for role, codes in ROLE_DEFAULTS.items():
            for code in codes:
                conn.execute(
                    "INSERT OR IGNORE INTO role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)",
                    (role, code),
                )
        for category, items in CATALOG_SEED.items():
            for order, (code, label) in enumerate(items, start=1):
                conn.execute(
                    """INSERT OR IGNORE INTO catalog_items
                    (category,code,label,sort_order,active,metadata_json,created_at,updated_at)
                    VALUES(?,?,?,?,1,'{}',?,?)""",
                    (category, code, label, order, now, now),
                )
        plan_count = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
        if plan_count == 0:
            plans = [
                ("TIM", "Fibra", "500 Mega", "500 Mega", 99.90, "", "", 10),
                ("TIM", "Fibra", "600 Mega", "600 Mega", 109.99, "", "", 20),
                ("TIM", "Fibra", "600 Mega + Paramount", "600 Mega", 109.99, "Paramount+", "", 30),
                ("TIM", "Fibra", "600 Mega + Globoplay", "600 Mega", 119.99, "Globoplay", "", 40),
                ("TIM", "Fibra", "800 Mega + YouTube Premium", "800 Mega", 129.99, "YouTube Premium", "", 50),
                ("TIM", "Fibra", "1 Giga", "1 Giga", 129.99, "", "", 60),
            ]
            conn.executemany(
                """INSERT INTO plans(provider,service,name,speed,price,benefits,uf_list,sort_order,active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,1,?,?)""",
                [(*p, now, now) for p in plans],
            )


# ------------------------- segurança -------------------------

def hash_password(password: str, iterations: int = 310_000) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_s, salt_s, digest_s = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_s.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_s.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_s))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def validate_password(password: str) -> str | None:
    if len(password or "") < 8:
        return "A senha precisa ter pelo menos 8 caracteres."
    if not any(ch.isalpha() for ch in password):
        return "A senha precisa conter ao menos uma letra."
    if not any(ch.isdigit() for ch in password):
        return "A senha precisa conter ao menos um número."
    return None


def token_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def effective_role_code(user: dict[str, Any] | sqlite3.Row | None) -> str:
    if not user:
        return "seller"
    getter = user.get if isinstance(user, dict) else lambda key, default=None: user[key] if key in user.keys() else default
    return str(getter("custom_role_code") or getter("effective_role_code") or getter("role_code") or "seller")


def get_role_permissions(role_code: str) -> set[str]:
    if role_code == "owner":
        return {code for code, _, _ in PERMISSIONS}
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT permission_code FROM role_permissions WHERE role_code=? AND allowed=1",
            (role_code,),
        ).fetchall()
    return {row[0] for row in rows}


def has_permission(user: dict[str, Any] | None, code: str) -> bool:
    if not user:
        return False
    return user.get("role_code") == "owner" or code in set(user.get("permissions", []))


def audit(user_id: int | None, action: str, entity_type: str | None = None,
          entity_id: str | int | None = None, details: Any = None, ip: str | None = None) -> None:
    detail_text = details if isinstance(details, str) else json_dumps(details or {})
    with db_connect() as conn:
        conn.execute(
            """INSERT INTO audit_logs(user_id,action,entity_type,entity_id,details,ip_address,created_at)
            VALUES(?,?,?,?,?,?,?)""",
            (user_id, action, entity_type, str(entity_id) if entity_id is not None else None,
             detail_text, ip, utc_now()),
        )


def create_session(user_id: int, hours: int) -> tuple[str, str]:
    raw = secrets.token_urlsafe(40)
    csrf = secrets.token_urlsafe(28)
    expires = (datetime.now() + timedelta(hours=hours)).replace(microsecond=0).isoformat()
    with db_connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (utc_now(),))
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at) VALUES(?,?,?,?,?)",
            (token_hash(raw), user_id, csrf, expires, utc_now()),
        )
    return raw, csrf


def get_user_by_session(raw_token: str | None) -> tuple[dict[str, Any] | None, str | None]:
    if not raw_token:
        return None, None
    with db_connect() as conn:
        row = conn.execute(
            """SELECT u.*, s.csrf_token, s.expires_at, t.name AS team_name,
                      r.name AS role_name, r.base_role AS registered_base_role
               FROM sessions s JOIN users u ON u.id=s.user_id
               LEFT JOIN teams t ON t.id=u.team_id
               LEFT JOIN roles r ON r.code=COALESCE(u.custom_role_code,u.role_code)
               WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
            (token_hash(raw_token), utc_now()),
        ).fetchone()
    if not row:
        return None, None
    user = dict(row)
    user["effective_role_code"] = effective_role_code(user)
    user["role_name"] = user.get("role_name") or SYSTEM_ROLES.get(user["role_code"], (user["role_code"], "", user["role_code"]))[0]
    user["permissions"] = sorted(get_role_permissions(user["effective_role_code"]))
    return user, user.pop("csrf_token")


def revoke_session(raw_token: str | None) -> None:
    if not raw_token:
        return
    with db_connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(raw_token),))


# ------------------------- validação/catálogos -------------------------

def catalog_exists(category: str, code: str | None, allow_blank: bool = True) -> bool:
    if not code:
        return allow_blank
    with db_connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM catalog_items WHERE category=? AND code=? AND active=1",
            (category, code),
        ).fetchone()
    return row is not None


def get_catalog_map(category: str) -> dict[str, str]:
    with db_connect() as conn:
        rows = conn.execute(
            "SELECT code,label FROM catalog_items WHERE category=? ORDER BY sort_order,label",
            (category,),
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def label_for(category: str, code: str | None) -> str:
    if not code:
        return ""
    return get_catalog_map(category).get(code, code)


def validate_iso_date(value: str | None, allow_blank: bool = True) -> bool:
    if not value:
        return allow_blank
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def sale_scope_sql(user: dict[str, Any], alias: str = "s") -> tuple[str, list[Any]]:
    if has_permission(user, "sales.all"):
        return "1=1", []
    if user["role_code"] == "bko":
        return f"({alias}.bko_user_id=? OR ({alias}.bko_user_id IS NULL AND {alias}.status IN ('nova','em_tratamento')))", [user["id"]]
    return f"{alias}.seller_id=?", [user["id"]]


def can_access_sale(user: dict[str, Any], sale: dict[str, Any]) -> bool:
    if has_permission(user, "sales.all"):
        return True
    if user["role_code"] == "bko":
        return sale.get("bko_user_id") in (None, user["id"]) and sale.get("status") in ("nova", "em_tratamento", "instalada", "cancelada")
    return sale.get("seller_id") == user["id"]


# ------------------------- HTTP -------------------------
@dataclass
class ApiError(Exception):
    status: int
    message: str


class OneCRMHTTPServer(ThreadingHTTPServer):
    """Servidor concorrente com encerramento limpo e fila mais tolerante."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


class OneCRMHandler(BaseHTTPRequestHandler):
    server_version = f"ONECRM/{APP_VERSION}"

    def client_ip(self) -> str:
        # Em hospedagens com proxy reverso, client_address é o proxy. O primeiro
        # endereço de X-Forwarded-For representa o navegador de origem.
        forwarded = ""
        if TRUST_PROXY_HEADERS:
            forwarded = (self.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
        return forwarded or self.client_address[0]

    def is_https(self) -> bool:
        proto = ""
        if TRUST_PROXY_HEADERS:
            proto = (self.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
        return proto == "https" or SECURE_COOKIES

    def log_message(self, format: str, *args: Any) -> None:
        log(f"{self.client_ip()} {format % args}")

    def parse_cookie(self, name: str) -> str | None:
        raw = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        try:
            jar.load(raw)
            return jar[name].value if name in jar else None
        except Exception:
            return None

    def current_user(self) -> tuple[dict[str, Any] | None, str | None, str | None]:
        raw = self.parse_cookie(COOKIE_NAME)
        user, csrf = get_user_by_session(raw)
        return user, csrf, raw

    def require_user(self) -> tuple[dict[str, Any], str, str]:
        user, csrf, raw = self.current_user()
        if not user or not csrf or not raw:
            raise ApiError(401, "Sessão expirada. Entre novamente.")
        return user, csrf, raw

    def require_permission(self, code: str) -> dict[str, Any]:
        user, _, _ = self.require_user()
        if not has_permission(user, code):
            raise ApiError(403, "Seu cargo não possui permissão para esta ação.")
        return user

    def check_csrf(self, expected: str) -> None:
        received = self.headers.get("X-CSRF-Token", "")
        if not received or not hmac.compare_digest(received, expected):
            raise ApiError(403, "Token de segurança inválido. Atualize a página.")

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_BODY:
            raise ApiError(413, "Requisição muito grande.")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception:
            raise ApiError(400, "JSON inválido.")
        if not isinstance(value, dict):
            raise ApiError(400, "O conteúdo precisa ser um objeto JSON.")
        return value

    def send_json(self, status: int, payload: Any, extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if self.is_https():
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Connection", "close")
        if extra_headers:
            for key, value in extra_headers.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def send_file(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            if STATIC_DIR.resolve() not in resolved.parents and resolved != STATIC_DIR.resolve():
                raise ApiError(403, "Acesso negado.")
            if not resolved.is_file():
                raise ApiError(404, "Arquivo não encontrado.")
            data = resolved.read_bytes()
            content_type = mimetypes.guess_type(str(resolved))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            if self.is_https():
                self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(data)
            self.close_connection = True
        except ApiError:
            raise
        except Exception:
            raise ApiError(500, "Não foi possível carregar o arquivo.")

    def send_csv(self, filename: str, content: str) -> None:
        data = ("\ufeff" + content).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def handle_error(self, exc: Exception) -> None:
        if isinstance(exc, ApiError):
            self.send_json(exc.status, {"ok": False, "error": exc.message})
            return
        log("ERRO INTERNO:\n" + traceback.format_exc())
        self.send_json(500, {"ok": False, "error": "Erro interno. Consulte logs/one_crm.log."})

    def do_GET(self) -> None:
        try:
            self.route_get()
        except Exception as exc:
            self.handle_error(exc)

    def do_POST(self) -> None:
        try:
            self.route_write("POST")
        except Exception as exc:
            self.handle_error(exc)

    def do_PUT(self) -> None:
        try:
            self.route_write("PUT")
        except Exception as exc:
            self.handle_error(exc)

    def route_get(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path == "/":
            return self.send_file(STATIC_DIR / "index.html")
        if path.startswith("/static/"):
            rel = unquote(path[len("/static/"):])
            return self.send_file(STATIC_DIR / rel)
        if path == "/api/bootstrap":
            return self.api_bootstrap()
        if path == "/api/me":
            return self.api_me_get()
        if path == "/api/dashboard":
            return self.api_dashboard()
        if path.startswith("/api/cep/") and path.count("/") == 3:
            return self.api_cep_lookup(path.rsplit("/", 1)[1], query)
        if path == "/api/sales":
            return self.api_sales_list(query)
        if path.startswith("/api/sales/") and path.count("/") == 3:
            return self.api_sale_detail(int(path.rsplit("/", 1)[1]))
        if path == "/api/ranking":
            return self.api_ranking(query)
        if path == "/api/daily-analysis":
            return self.api_daily_analysis(query)
        if path == "/api/intelligence":
            return self.api_intelligence()
        if path == "/api/ai/status":
            return self.api_ai_status()
        if path == "/api/users":
            return self.api_users_list()
        if path == "/api/teams":
            return self.api_teams_list()
        if path == "/api/plans":
            return self.api_plans_list(query)
        if path == "/api/catalogs":
            return self.api_catalogs(query)
        if path == "/api/roles":
            return self.api_roles()
        if path == "/api/audit":
            return self.api_audit(query)
        if path == "/api/backups":
            return self.api_backups_list()
        if path == "/api/integrations":
            return self.api_integrations_get()
        if path == "/api/powerbi":
            return self.api_powerbi_get()
        if path == "/api/export/sales.csv":
            return self.api_export_sales(query)
        if path == "/api/health":
            try:
                with db_connect() as conn:
                    conn.execute("SELECT 1").fetchone()
                return self.send_json(200, {
                    "ok": True,
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "time": utc_now(),
                    "database": "ok",
                    "persistent_storage": bool(RAILWAY_VOLUME_PATH or os.getenv("ONE_CRM_DATA_DIR")),
                })
            except Exception:
                return self.send_json(503, {"ok": False, "app": APP_NAME, "database": "unavailable"})
        raise ApiError(404, "Rota não encontrada.")

    def route_write(self, method: str) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if method == "POST" and path == "/api/setup":
            return self.api_setup()
        if method == "POST" and path == "/api/login":
            return self.api_login()
        if method == "POST" and path == "/api/logout":
            return self.api_logout()

        user, csrf, _ = self.require_user()
        self.check_csrf(csrf)

        if method == "POST" and path == "/api/ai/ask":
            return self.api_ai_ask(user)
        if method == "POST" and path == "/api/ai/test":
            return self.api_ai_test(user)
        if method == "POST" and path == "/api/sales":
            return self.api_sale_create(user)
        if method == "PUT" and path.startswith("/api/sales/"):
            parts = path.split("/")
            if len(parts) == 4:
                return self.api_sale_update(user, int(parts[3]))
            if len(parts) == 5 and parts[4] == "workflow":
                return self.api_sale_workflow(user, int(parts[3]))
        if method == "POST" and path == "/api/users":
            return self.api_user_create(user)
        if method == "PUT" and path.startswith("/api/users/"):
            return self.api_user_update(user, int(path.rsplit("/", 1)[1]))
        if method == "POST" and path == "/api/teams":
            return self.api_team_create(user)
        if method == "PUT" and path.startswith("/api/teams/"):
            return self.api_team_update(user, int(path.rsplit("/", 1)[1]))
        if method == "POST" and path == "/api/plans":
            return self.api_plan_create(user)
        if method == "PUT" and path.startswith("/api/plans/"):
            return self.api_plan_update(user, int(path.rsplit("/", 1)[1]))
        if method == "POST" and path == "/api/catalogs":
            return self.api_catalog_create(user)
        if method == "PUT" and path.startswith("/api/catalogs/"):
            return self.api_catalog_update(user, int(path.rsplit("/", 1)[1]))
        if method == "POST" and path == "/api/roles":
            return self.api_role_create(user)
        if method == "PUT" and path.startswith("/api/roles/"):
            return self.api_role_update(user, path.rsplit("/", 1)[1])
        if method == "POST" and path == "/api/backups":
            return self.api_backup_create(user)
        if method == "PUT" and path == "/api/integrations":
            return self.api_integrations_update(user)
        if method == "PUT" and path == "/api/me/profile":
            return self.api_profile_update(user)
        if method == "PUT" and path == "/api/me/theme":
            return self.api_theme_update(user)
        if method == "PUT" and path == "/api/me/password":
            return self.api_change_password(user)
        raise ApiError(404, "Rota não encontrada.")

    # ------------------------- autenticação -------------------------
    def api_bootstrap(self) -> None:
        with db_connect() as conn:
            setup_required = conn.execute("SELECT COUNT(*) FROM users WHERE role_code='owner' AND active=1").fetchone()[0] == 0
        user, csrf, _ = self.current_user()
        payload: dict[str, Any] = {
            "ok": True,
            "app": APP_NAME,
            "version": APP_VERSION,
            "setup_required": setup_required,
            "setup_token_required": bool(SETUP_TOKEN),
            "authenticated": bool(user),
            "runtime": {
                "online": IS_RAILWAY,
                "persistent_storage": bool(RAILWAY_VOLUME_PATH or os.getenv("ONE_CRM_DATA_DIR")),
            },
        }
        if user:
            payload["user"] = self.public_user(user)
            payload["csrf_token"] = csrf
        self.send_json(200, payload)

    def api_setup(self) -> None:
        data = self.read_json()
        provided_token = str(data.get("setup_token") or "").strip()
        if SETUP_TOKEN and not hmac.compare_digest(provided_token, SETUP_TOKEN):
            raise ApiError(403, "Token de configuração inicial inválido.")

        name = (data.get("name") or "").strip()
        email = normalize_email(data.get("email") or "")
        password = data.get("password") or ""
        if len(name) < 3 or "@" not in email:
            raise ApiError(400, "Informe nome e e-mail válidos.")
        password_error = validate_password(password)
        if password_error:
            raise ApiError(400, password_error)

        # Impede que duas requisições simultâneas criem dois primeiros Donos.
        with SETUP_LOCK:
            now = utc_now()
            with db_connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute("SELECT COUNT(*) FROM users WHERE role_code='owner' AND active=1").fetchone()[0] > 0:
                    raise ApiError(409, "O primeiro Dono já foi configurado.")
                cur = conn.execute(
                    """INSERT INTO users(name,email,password_hash,role_code,active,created_at,updated_at)
                       VALUES(?,?,?,'owner',1,?,?)""",
                    (name, email, hash_password(password), now, now),
                )
                user_id = cur.lastrowid

        audit(user_id, "system.setup", "user", user_id, {"email": email}, self.client_ip())
        raw, csrf = create_session(user_id, int(load_config().get("session_hours", 12)))
        headers = {"Set-Cookie": self.session_cookie(raw)}
        self.send_json(201, {"ok": True, "message": "Dono criado.", "csrf_token": csrf}, headers)

    def api_login(self) -> None:
        data = self.read_json()
        email = normalize_email(data.get("email") or "")
        password = data.get("password") or ""
        identity = f"{self.client_ip()}|{email}"
        now_dt = datetime.now()
        with db_connect() as conn:
            attempt = conn.execute("SELECT * FROM login_attempts WHERE identity=?", (identity,)).fetchone()
            if attempt and attempt["blocked_until"]:
                blocked = datetime.fromisoformat(attempt["blocked_until"])
                if blocked > now_dt:
                    seconds = int((blocked - now_dt).total_seconds())
                    raise ApiError(429, f"Muitas tentativas. Aguarde {max(1, seconds // 60)} minuto(s).")
            row = conn.execute("SELECT * FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
            valid = row is not None and row["active"] == 1 and verify_password(password, row["password_hash"])
            if not valid:
                failed = (attempt["failed_count"] if attempt else 0) + 1
                first = attempt["first_failed_at"] if attempt and attempt["first_failed_at"] else utc_now()
                blocked_until = None
                if failed >= 5:
                    blocked_until = (now_dt + timedelta(minutes=15)).replace(microsecond=0).isoformat()
                    failed = 0
                    first = None
                conn.execute(
                    """INSERT INTO login_attempts(identity,failed_count,first_failed_at,blocked_until)
                       VALUES(?,?,?,?) ON CONFLICT(identity) DO UPDATE SET
                       failed_count=excluded.failed_count, first_failed_at=excluded.first_failed_at,
                       blocked_until=excluded.blocked_until""",
                    (identity, failed, first, blocked_until),
                )
                audit(None, "auth.login_failed", "user", None, {"email": email}, self.client_ip())
                raise ApiError(401, "E-mail ou senha inválidos.")
            conn.execute("DELETE FROM login_attempts WHERE identity=?", (identity,))
            conn.execute("UPDATE users SET last_login_at=?,updated_at=? WHERE id=?", (utc_now(), utc_now(), row["id"]))
            user_id = row["id"]
        raw, csrf = create_session(user_id, int(load_config().get("session_hours", 12)))
        audit(user_id, "auth.login", "user", user_id, {}, self.client_ip())
        self.send_json(200, {"ok": True, "csrf_token": csrf}, {"Set-Cookie": self.session_cookie(raw)})

    def api_logout(self) -> None:
        user, csrf, raw = self.current_user()
        if user and csrf:
            self.check_csrf(csrf)
            audit(user["id"], "auth.logout", "user", user["id"], {}, self.client_ip())
        revoke_session(raw)
        secure = "; Secure" if self.is_https() else ""
        self.send_json(200, {"ok": True}, {"Set-Cookie": f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{secure}"})

    def session_cookie(self, raw: str) -> str:
        hours = max(1, int(load_config().get("session_hours", 12)))
        secure = "; Secure" if self.is_https() else ""
        return f"{COOKIE_NAME}={raw}; Path=/; Max-Age={hours * 3600}; HttpOnly; SameSite=Lax{secure}"

    def public_user(self, user: dict[str, Any]) -> dict[str, Any]:
        effective = user.get("effective_role_code") or effective_role_code(user)
        return {
            "id": user["id"], "name": user["name"],
            "display_name": user.get("display_name") or user["name"],
            "email": user["email"], "phone": user.get("phone") or "",
            "bio": user.get("bio") or "",
            "theme_preference": user.get("theme_preference") or "dark",
            "role_code": effective,
            "base_role": user["role_code"],
            "role_name": user.get("role_name") or SYSTEM_ROLES.get(user["role_code"], (effective, "", user["role_code"]))[0],
            "team_id": user.get("team_id"),
            "team_name": user.get("team_name"), "permissions": user.get("permissions", []),
            "must_change_password": bool(user.get("must_change_password")),
        }

    # ------------------------- dashboard / análises -------------------------
    def api_dashboard(self) -> None:
        user = self.require_permission("dashboard.view")
        where, params = sale_scope_sql(user)
        today = local_today()
        with db_connect() as conn:
            base = f"FROM sales s WHERE {where}"
            total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
            today_count = conn.execute(f"SELECT COUNT(*) {base} AND substr(s.created_at,1,10)=?", [*params, today]).fetchone()[0]
            installed = conn.execute(f"SELECT COUNT(*) {base} AND s.installation_status IN ('instalado','instalado_regra_pdv')", params).fetchone()[0]
            treatment = conn.execute(f"SELECT COUNT(*) {base} AND s.status='em_tratamento'", params).fetchone()[0]
            cancelled = conn.execute(f"SELECT COUNT(*) {base} AND s.status='cancelada'", params).fetchone()[0]
            agenda = conn.execute(f"SELECT COUNT(*) {base} AND s.appointment_date=?", [*params, today]).fetchone()[0]
            bio_ok = conn.execute(f"SELECT COUNT(*) {base} AND s.biometric_status='biometria_ok'", params).fetchone()[0]
            bio_pending = conn.execute(f"SELECT COUNT(*) {base} AND s.biometric_status IN ('biometria_pendente','prometeu_biometria','retorno_biometria')", params).fetchone()[0]
            recent = conn.execute(
                f"""SELECT s.id,s.client_name,s.phone,s.plan_name_snapshot,s.status,s.activation_status,
                    s.biometric_status,s.installation_status,s.appointment_date,s.created_at,
                    u.name AS seller_name,t.name AS team_name,b.name AS bko_name
                    FROM sales s JOIN users u ON u.id=s.seller_id
                    LEFT JOIN teams t ON t.id=s.team_id LEFT JOIN users b ON b.id=s.bko_user_id
                    WHERE {where} ORDER BY s.id DESC LIMIT 12""",
                params,
            ).fetchall()
            teams = []
            if has_permission(user, "sales.all"):
                teams = [dict(r) for r in conn.execute(
                    """SELECT COALESCE(t.name,'Sem equipe') AS team_name, COUNT(s.id) AS total,
                        SUM(CASE WHEN substr(s.created_at,1,10)=? THEN 1 ELSE 0 END) AS today,
                        SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed
                        FROM sales s LEFT JOIN teams t ON t.id=s.team_id
                        GROUP BY COALESCE(t.name,'Sem equipe') ORDER BY today DESC,total DESC""",
                    (today,),
                ).fetchall()]
        self.send_json(200, {
            "ok": True,
            "cards": {"total": total, "today": today_count, "installed": installed,
                      "treatment": treatment, "cancelled": cancelled, "agenda_today": agenda,
                      "biometric_ok": bio_ok, "biometric_pending": bio_pending},
            "recent": [self.decorate_sale(dict(r)) for r in recent],
            "teams": teams,
        })

    def api_ranking(self, query: dict[str, list[str]]) -> None:
        user, _, _ = self.require_user()
        if not (has_permission(user, "ranking.all") or has_permission(user, "ranking.own")):
            raise ApiError(403, "Sem permissão para visualizar o ranking.")
        period = (query.get("period") or ["month"])[0]
        prefix = date.today().strftime("%Y-%m") if period == "month" else None
        date_clause = "AND substr(s.created_at,1,7)=?" if prefix else ""
        params: list[Any] = [prefix] if prefix else []
        with db_connect() as conn:
            rows = conn.execute(
                f"""SELECT u.id,u.name,COALESCE(t.name,'Sem equipe') AS team_name,
                    COUNT(s.id) AS total,
                    SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed,
                    SUM(CASE WHEN s.status='cancelada' THEN 1 ELSE 0 END) AS cancelled,
                    COALESCE(SUM(s.plan_price_snapshot),0) AS revenue
                    FROM users u LEFT JOIN teams t ON t.id=u.team_id
                    LEFT JOIN sales s ON s.seller_id=u.id {date_clause}
                    WHERE u.role_code='seller' AND u.active=1
                    GROUP BY u.id,u.name,t.name""",
                params,
            ).fetchall()
        ranking = []
        for row in rows:
            item = dict(row)
            total = item["total"] or 0
            installed = item["installed"] or 0
            item["conversion"] = round(installed * 100 / total, 1) if total else 0
            item["points"] = installed * 100 + total * 10 - (item["cancelled"] or 0) * 5
            ranking.append(item)
        ranking.sort(key=lambda x: (x["points"], x["installed"], x["total"]), reverse=True)
        for idx, item in enumerate(ranking, 1):
            item["position"] = idx
        if not has_permission(user, "ranking.all"):
            ranking = [item for item in ranking if item["id"] == user["id"]]
        self.send_json(200, {"ok": True, "period": period, "ranking": ranking})

    def api_daily_analysis(self, query: dict[str, list[str]]) -> None:
        user = self.require_permission("daily.view")
        selected = (query.get("date") or [local_today()])[0]
        if not validate_iso_date(selected, False):
            raise ApiError(400, "Data inválida.")
        with db_connect() as conn:
            team_rows = conn.execute(
                """SELECT COALESCE(t.name,'Sem equipe') AS team_name,COUNT(s.id) AS sales,
                    SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed,
                    SUM(CASE WHEN s.status='cancelada' THEN 1 ELSE 0 END) AS cancelled
                    FROM sales s LEFT JOIN teams t ON t.id=s.team_id
                    WHERE substr(s.created_at,1,10)=?
                    GROUP BY COALESCE(t.name,'Sem equipe') ORDER BY sales DESC""",
                (selected,),
            ).fetchall()
            seller_rows = conn.execute(
                """SELECT u.name AS seller_name,COALESCE(t.name,'Sem equipe') AS team_name,COUNT(s.id) AS sales,
                    SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed
                    FROM sales s JOIN users u ON u.id=s.seller_id LEFT JOIN teams t ON t.id=s.team_id
                    WHERE substr(s.created_at,1,10)=?
                    GROUP BY u.id,u.name,t.name ORDER BY sales DESC,u.name""",
                (selected,),
            ).fetchall()
        self.send_json(200, {"ok": True, "date": selected,
                             "teams": [dict(r) for r in team_rows],
                             "sellers": [dict(r) for r in seller_rows]})

    def api_intelligence(self) -> None:
        user = self.require_permission("intelligence.view")
        today = date.today()
        insights: list[dict[str, Any]] = []
        where, params = sale_scope_sql(user)
        with db_connect() as conn:
            pending = conn.execute(
                f"""SELECT s.id,s.client_name,s.created_at,u.name AS seller_name
                   FROM sales s JOIN users u ON u.id=s.seller_id
                   WHERE {where} AND s.status NOT IN ('instalada','cancelada')
                   ORDER BY s.created_at ASC""",
                params,
            ).fetchall()
            for row in pending:
                try:
                    age = (today - date.fromisoformat(row["created_at"][:10])).days
                except Exception:
                    age = 0
                if age >= 3:
                    insights.append({"severity": "warning", "title": f"Venda #{row['id']} parada há {age} dias",
                                     "description": f"{row['client_name']} · vendedor {row['seller_name']}", "sale_id": row["id"]})
            late = conn.execute(
                f"""SELECT s.id,s.client_name,s.appointment_date FROM sales s
                   WHERE {where} AND s.appointment_date IS NOT NULL AND s.appointment_date<?
                   AND s.installation_status NOT IN ('instalado','instalado_regra_pdv')""",
                [*params, local_today()],
            ).fetchall()
            for row in late:
                insights.append({"severity": "danger", "title": f"Agendamento atrasado na venda #{row['id']}",
                                 "description": f"{row['client_name']} estava agendado para {row['appointment_date']}", "sale_id": row["id"]})
            bio_count = conn.execute(
                f"""SELECT COUNT(*) FROM sales s WHERE {where}
                AND s.biometric_status IN ('biometria_pendente','prometeu_biometria','retorno_biometria')""",
                params,
            ).fetchone()[0]
            if bio_count:
                insights.append({"severity": "info", "title": f"{bio_count} biometria(s) ainda pendente(s)",
                                 "description": "Priorize vendas já ativadas e com instalação próxima."})
            team_rows = conn.execute(
                f"""SELECT COALESCE(t.name,'Sem equipe') team_name,COUNT(s.id) total,
                    SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) installed
                    FROM sales s LEFT JOIN teams t ON t.id=s.team_id
                    WHERE {where} GROUP BY COALESCE(t.name,'Sem equipe')""",
                params,
            ).fetchall()
            for row in team_rows:
                total = row["total"] or 0
                conversion = (row["installed"] or 0) * 100 / total if total else 0
                if total >= 5 and conversion < 30:
                    insights.append({"severity": "warning", "title": f"Conversão baixa em {row['team_name']}",
                                     "description": f"Conversão atual: {conversion:.1f}% em {total} vendas."})
        self.send_json(200, {"ok": True, "generated_at": utc_now(), "insights": insights[:50]})

    def _ai_settings_overrides(self) -> dict[str, str]:
        keys = ("ai_provider", "groq_model", "openai_model")
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT key,value FROM system_settings WHERE key IN (?,?,?)",
                keys,
            ).fetchall()
        saved = {str(row["key"]): str(row["value"] or "").strip() for row in rows}
        return {
            "provider": saved.get("ai_provider", ""),
            "groq_model": saved.get("groq_model", ""),
            "openai_model": saved.get("openai_model", ""),
        }

    def _check_ai_rate_limit(self, user_id: int) -> None:
        now = time.monotonic()
        with AI_RATE_LOCK:
            bucket = [stamp for stamp in AI_RATE_BUCKETS.get(user_id, []) if now - stamp < AI_RATE_WINDOW_SECONDS]
            if len(bucket) >= AI_RATE_LIMIT:
                retry_after = max(1, int(AI_RATE_WINDOW_SECONDS - (now - bucket[0])))
                raise ApiError(429, f"Limite temporário da IA atingido. Tente novamente em {retry_after} segundo(s).")
            bucket.append(now)
            AI_RATE_BUCKETS[user_id] = bucket

    def _record_ai_usage(
        self,
        *,
        user_id: int,
        sale_id: int | None,
        status: str,
        provider: str = "",
        model: str = "",
        response_id: str = "",
        fallback_used: bool = False,
        question_length: int = 0,
        usage: dict[str, Any] | None = None,
        error_code: str = "",
    ) -> None:
        usage = usage or {}
        try:
            with db_connect() as conn:
                conn.execute(
                    """INSERT INTO ai_usage_logs
                    (user_id,sale_id,response_id,provider,model,fallback_used,question_length,input_tokens,output_tokens,status,error_code,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        user_id,
                        sale_id,
                        response_id or None,
                        provider or None,
                        model or None,
                        1 if fallback_used else 0,
                        max(0, int(question_length)),
                        max(0, int(usage.get("input_tokens") or 0)),
                        max(0, int(usage.get("output_tokens") or 0)),
                        status,
                        error_code or None,
                        utc_now(),
                    ),
                )
        except Exception as exc:
            log(f"Falha ao registrar uso da IA: {exc}")

    def api_ai_status(self) -> None:
        user, _, _ = self.require_user()
        if not (has_permission(user, "ai.use") or has_permission(user, "integrations.manage") or has_permission(user, "intelligence.view")):
            raise ApiError(403, "Seu cargo não possui acesso à inteligência artificial.")
        overrides = self._ai_settings_overrides()
        status = public_ai_status(
            provider_override=overrides["provider"],
            groq_model_override=overrides["groq_model"],
            openai_model_override=overrides["openai_model"],
        )
        status.update({
            "permission": has_permission(user, "ai.use"),
            "rate_limit": AI_RATE_LIMIT,
            "rate_window_seconds": AI_RATE_WINDOW_SECONDS,
        })
        self.send_json(200, {
            "ok": True,
            "ai": status,
            "groq": status.get("providers", {}).get("groq", {}),
            "openai": status.get("providers", {}).get("openai", {}),
        })

    def _build_ai_context(self, user: dict[str, Any], sale_id: int | None = None) -> dict[str, Any]:
        where, params = sale_scope_sql(user)
        today = local_today()
        context: dict[str, Any] = {
            "data_atual": today,
            "usuario": {
                "cargo": user.get("role_name") or user.get("role_code"),
                "escopo": "todas as vendas" if has_permission(user, "sales.all") else "fila BKO" if user.get("role_code") == "bko" else "próprias vendas",
            },
        }
        with db_connect() as conn:
            base = f"FROM sales s WHERE {where}"
            metrics = {
                "total_vendas": conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0],
                "vendas_hoje": conn.execute(f"SELECT COUNT(*) {base} AND substr(s.created_at,1,10)=?", [*params, today]).fetchone()[0],
                "instaladas": conn.execute(f"SELECT COUNT(*) {base} AND s.installation_status IN ('instalado','instalado_regra_pdv')", params).fetchone()[0],
                "canceladas": conn.execute(f"SELECT COUNT(*) {base} AND s.status='cancelada'", params).fetchone()[0],
                "biometrias_pendentes": conn.execute(
                    f"SELECT COUNT(*) {base} AND s.biometric_status IN ('biometria_pendente','prometeu_biometria','retorno_biometria')",
                    params,
                ).fetchone()[0],
                "agendamentos_atrasados": conn.execute(
                    f"SELECT COUNT(*) {base} AND s.appointment_date IS NOT NULL AND s.appointment_date<? AND s.installation_status NOT IN ('instalado','instalado_regra_pdv')",
                    [*params, today],
                ).fetchone()[0],
            }
            context["indicadores"] = metrics
            recent = conn.execute(
                f"""SELECT s.id,s.status,s.activation_status,s.biometric_status,s.installation_status,
                    s.appointment_date,s.created_at,COALESCE(t.name,'Sem equipe') AS team_name
                    FROM sales s LEFT JOIN teams t ON t.id=s.team_id
                    WHERE {where} ORDER BY s.id DESC LIMIT 12""",
                params,
            ).fetchall()
            context["vendas_recentes"] = [
                {
                    "id": row["id"],
                    "status": label_for("sale_status", row["status"]),
                    "ativacao": label_for("activation_status", row["activation_status"]),
                    "biometria": label_for("biometric_status", row["biometric_status"]),
                    "instalacao": label_for("installation_status", row["installation_status"]),
                    "agendamento": row["appointment_date"],
                    "equipe": row["team_name"],
                    "criada_em": row["created_at"],
                }
                for row in recent
            ]
            uf_rows = conn.execute(
                f"""SELECT COALESCE(NULLIF(TRIM(s.uf),''),'Sem UF') AS uf,COUNT(*) AS total,
                    SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS instaladas
                    FROM sales s WHERE {where}
                    GROUP BY COALESCE(NULLIF(TRIM(s.uf),''),'Sem UF') ORDER BY total DESC LIMIT 27""",
                params,
            ).fetchall()
            context["vendas_por_uf"] = [dict(row) for row in uf_rows]
            team_rows = conn.execute(
                f"""SELECT COALESCE(t.name,'Sem equipe') AS equipe,COUNT(*) AS total,
                    SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS instaladas
                    FROM sales s LEFT JOIN teams t ON t.id=s.team_id WHERE {where}
                    GROUP BY COALESCE(t.name,'Sem equipe') ORDER BY total DESC LIMIT 30""",
                params,
            ).fetchall()
            context["equipes"] = [dict(row) for row in team_rows]
            if sale_id is not None:
                row = conn.execute(
                    """SELECT s.*,COALESCE(t.name,'Sem equipe') AS team_name,u.name AS seller_name
                    FROM sales s JOIN users u ON u.id=s.seller_id
                    LEFT JOIN teams t ON t.id=s.team_id WHERE s.id=?""",
                    (sale_id,),
                ).fetchone()
                if not row:
                    raise ApiError(404, "Venda não encontrada.")
                sale = dict(row)
                if not can_access_sale(user, sale):
                    raise ApiError(403, "Você não pode consultar esta venda com a IA.")
                context["venda_especifica"] = {
                    "id": sale["id"],
                    "referencia_cliente": f"Cliente da venda #{sale['id']}",
                    "plano": sale.get("plan_name_snapshot"),
                    "valor": sale.get("plan_price_snapshot"),
                    "operadora": sale.get("provider"),
                    "servico": sale.get("service"),
                    "equipe": sale.get("team_name"),
                    "vendedor": sale.get("seller_name"),
                    "status": label_for("sale_status", sale.get("status")),
                    "ativacao": label_for("activation_status", sale.get("activation_status")),
                    "biometria": label_for("biometric_status", sale.get("biometric_status")),
                    "instalacao": label_for("installation_status", sale.get("installation_status")),
                    "agendamento_status": label_for("appointment_status", sale.get("appointment_status")),
                    "agendamento_data": sale.get("appointment_date"),
                    "agendamento_periodo": label_for("period", sale.get("appointment_period")),
                    "observacoes_sem_dados_pessoais": redact_ai_text(sale.get("notes")),
                    "criada_em": sale.get("created_at"),
                    "atualizada_em": sale.get("updated_at"),
                }
        return context

    def api_ai_ask(self, user: dict[str, Any]) -> None:
        if not has_permission(user, "ai.use"):
            raise ApiError(403, "Seu cargo não possui permissão para usar o ONE Intelligence.")
        self._check_ai_rate_limit(int(user["id"]))
        data = self.read_json()
        question = str(data.get("question") or "").strip()
        if not question:
            raise ApiError(400, "Digite uma pergunta.")
        if len(question) > 2_000:
            raise ApiError(400, "A pergunta excede o limite de 2.000 caracteres.")
        raw_sale_id = data.get("sale_id")
        sale_id: int | None = None
        if raw_sale_id not in (None, ""):
            try:
                sale_id = int(raw_sale_id)
            except (TypeError, ValueError):
                raise ApiError(400, "O número da venda é inválido.")
        context = self._build_ai_context(user, sale_id)
        overrides = self._ai_settings_overrides()
        try:
            result = create_ai_response(
                question=question,
                context=context,
                provider_override=overrides["provider"],
                groq_model_override=overrides["groq_model"],
                openai_model_override=overrides["openai_model"],
            )
        except ValueError as exc:
            self._record_ai_usage(user_id=user["id"], sale_id=sale_id, status="error", question_length=len(question), error_code="validation")
            raise ApiError(400, str(exc)) from exc
        except AIConfigurationError as exc:
            self._record_ai_usage(user_id=user["id"], sale_id=sale_id, status="error", question_length=len(question), error_code="configuration")
            raise ApiError(503, str(exc)) from exc
        except AIAuthenticationError as exc:
            self._record_ai_usage(user_id=user["id"], sale_id=sale_id, status="error", question_length=len(question), error_code="authentication")
            raise ApiError(502, str(exc)) from exc
        except AIRateLimitError as exc:
            self._record_ai_usage(user_id=user["id"], sale_id=sale_id, status="error", question_length=len(question), error_code="provider_rate_limit")
            raise ApiError(429, str(exc)) from exc
        except AIConnectionError as exc:
            self._record_ai_usage(user_id=user["id"], sale_id=sale_id, status="error", question_length=len(question), error_code="connection")
            raise ApiError(502, str(exc)) from exc
        self._record_ai_usage(
            user_id=user["id"],
            sale_id=sale_id,
            status="success",
            provider=result.get("provider", ""),
            model=result.get("model", ""),
            response_id=result.get("response_id", ""),
            fallback_used=bool(result.get("fallback_used")),
            question_length=len(question),
            usage=result.get("usage") or {},
        )
        audit(
            user["id"],
            "ai.ask",
            "sale" if sale_id else "operation",
            sale_id,
            {
                "provider": result.get("provider"),
                "model": result.get("model"),
                "fallback_used": bool(result.get("fallback_used")),
                "response_id": result.get("response_id"),
                "question_length": len(question),
            },
            self.client_ip(),
        )
        self.send_json(200, {"ok": True, **result})

    def api_ai_test(self, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "integrations.manage"):
            raise ApiError(403, "Sem permissão para testar integrações.")
        data = self.read_json()
        provider = str(data.get("provider") or "").strip().lower()
        overrides = self._ai_settings_overrides()
        if not provider:
            provider = overrides["provider"] or "groq"
        try:
            result = test_ai_connection(
                provider=provider,
                groq_model_override=overrides["groq_model"],
                openai_model_override=overrides["openai_model"],
            )
        except AIConfigurationError as exc:
            raise ApiError(503, str(exc)) from exc
        except AIAuthenticationError as exc:
            raise ApiError(502, str(exc)) from exc
        except AIRateLimitError as exc:
            raise ApiError(429, str(exc)) from exc
        except AIConnectionError as exc:
            raise ApiError(502, str(exc)) from exc
        label = result.get("provider_label") or provider.title()
        audit(actor["id"], "integration.ai.test", "integration", provider, {"model": result.get("model")}, self.client_ip())
        self.send_json(
            200,
            {
                "ok": True,
                "message": f"Conexão com {label} confirmada.",
                "provider": result.get("provider"),
                "provider_label": label,
                "model": result.get("model"),
                "response_id": result.get("response_id"),
            },
        )

    # ------------------------- vendas -------------------------
    def api_cep_lookup(self, raw_cep: str, query: dict[str, list[str]] | None = None) -> None:
        self.require_user()
        cep = only_digits(unquote(raw_cep or ""))
        if len(cep) != 8:
            raise ApiError(400, "Informe um CEP com 8 números.")

        query = query or {}
        refresh = str((query.get("refresh") or ["0"])[0]).lower() in {"1", "true", "yes", "sim"}
        cached: dict[str, Any] | None = None
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM cep_cache WHERE cep=?", (cep,)).fetchone()
            if row:
                candidate = dict(row)
                if candidate.get("city") and len(candidate.get("uf") or "") == 2:
                    cached = candidate

        def cached_result(warning: str = "") -> dict[str, Any]:
            assert cached is not None
            result = {
                "cep": cached["cep"], "street": cached.get("street") or "",
                "complement": cached.get("complement") or "",
                "neighborhood": cached.get("neighborhood") or "",
                "city": cached.get("city") or "", "uf": cached.get("uf") or "",
                "ddd": cached.get("ddd") or "", "ibge": cached.get("ibge") or "",
                "source": "Cache local", "cached": True,
            }
            if warning:
                result["warning"] = warning
            elif not result["street"]:
                result["warning"] = "CEP geral encontrado no cache. Preencha o logradouro e o número manualmente."
            return result

        if cached and not refresh:
            self.send_json(200, {"ok": True, "address": cached_result()})
            return

        result, payload, failures, not_found = lookup_cep_from_providers(cep)
        if result and payload is not None:
            now = utc_now()
            with db_connect() as conn:
                conn.execute(
                    """INSERT INTO cep_cache(cep,street,complement,neighborhood,city,uf,ddd,ibge,payload_json,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(cep) DO UPDATE SET street=excluded.street,complement=excluded.complement,
                    neighborhood=excluded.neighborhood,city=excluded.city,uf=excluded.uf,ddd=excluded.ddd,
                    ibge=excluded.ibge,payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
                    (cep, result["street"], result["complement"], result["neighborhood"], result["city"],
                     result["uf"], result["ddd"], result["ibge"],
                     json_dumps({"provider": result["source"], "payload": payload}), now),
                )
            self.send_json(200, {"ok": True, "address": result})
            return

        # Em atualização manual, um cache válido é melhor que abandonar o cadastro.
        if cached:
            attempted = ", ".join(failures + not_found) or "fontes externas"
            self.send_json(200, {
                "ok": True,
                "address": cached_result(f"As fontes externas ({attempted}) não responderam agora. Endereço recuperado do cache local."),
            })
            return

        if len(not_found) == 3:
            raise ApiError(404, "CEP não encontrado nas fontes consultadas. Confira os números ou preencha o endereço manualmente.")

        attempted = ", ".join(failures + not_found) or "provedores de CEP"
        raise ApiError(503, f"Não foi possível consultar o CEP agora. O ONE CRM tentou {attempted}. Tente novamente ou preencha manualmente.")

    def api_sales_list(self, query: dict[str, list[str]]) -> None:
        user, _, _ = self.require_user()
        if not (has_permission(user, "sales.all") or has_permission(user, "sales.own") or user["role_code"] == "bko"):
            raise ApiError(403, "Sem permissão para visualizar vendas.")
        where, params = sale_scope_sql(user)
        filters = [where]
        search = (query.get("search") or [""])[0].strip()
        status = (query.get("status") or [""])[0].strip()
        date_from = (query.get("date_from") or [""])[0].strip()
        date_to = (query.get("date_to") or [""])[0].strip()
        if search:
            filters.append("(s.client_name LIKE ? OR s.phone LIKE ? OR s.cpf_cnpj LIKE ? OR s.os_number LIKE ?)")
            term = f"%{search}%"
            params.extend([term, term, term, term])
        if status:
            filters.append("s.status=?")
            params.append(status)
        if date_from and validate_iso_date(date_from, False):
            filters.append("substr(s.created_at,1,10)>=?")
            params.append(date_from)
        if date_to and validate_iso_date(date_to, False):
            filters.append("substr(s.created_at,1,10)<=?")
            params.append(date_to)
        sql_where = " AND ".join(filters)
        with db_connect() as conn:
            rows = conn.execute(
                f"""SELECT s.*,u.name AS seller_name,t.name AS team_name,b.name AS bko_name
                    FROM sales s JOIN users u ON u.id=s.seller_id
                    LEFT JOIN teams t ON t.id=s.team_id LEFT JOIN users b ON b.id=s.bko_user_id
                    WHERE {sql_where} ORDER BY s.id DESC LIMIT 1000""",
                params,
            ).fetchall()
        self.send_json(200, {"ok": True, "sales": [self.decorate_sale(dict(r)) for r in rows]})

    def api_sale_detail(self, sale_id: int) -> None:
        user, _, _ = self.require_user()
        with db_connect() as conn:
            row = conn.execute(
                """SELECT s.*,u.name AS seller_name,t.name AS team_name,b.name AS bko_name
                   FROM sales s JOIN users u ON u.id=s.seller_id
                   LEFT JOIN teams t ON t.id=s.team_id LEFT JOIN users b ON b.id=s.bko_user_id
                   WHERE s.id=?""",
                (sale_id,),
            ).fetchone()
            if not row:
                raise ApiError(404, "Venda não encontrada.")
            sale = dict(row)
            if not can_access_sale(user, sale):
                raise ApiError(403, "Você não pode acessar esta venda.")
            history = conn.execute(
                """SELECT h.*,u.name AS user_name FROM sale_history h
                   LEFT JOIN users u ON u.id=h.user_id WHERE h.sale_id=? ORDER BY h.id DESC""",
                (sale_id,),
            ).fetchall()
        self.send_json(200, {"ok": True, "sale": self.decorate_sale(sale), "history": [dict(r) for r in history]})

    def api_sale_create(self, user: dict[str, Any]) -> None:
        if not has_permission(user, "sales.create"):
            raise ApiError(403, "Sem permissão para cadastrar vendas.")
        data = self.read_json()
        client_name = (data.get("client_name") or "").strip()
        phone = normalize_mobile_phone(data.get("phone") or "")
        plan_id = int(data.get("plan_id") or 0)
        if len(client_name) < 3 or not phone or not plan_id:
            raise ApiError(400, "Cliente, celular brasileiro válido e plano são obrigatórios.")
        with db_connect() as conn:
            plan = conn.execute("SELECT * FROM plans WHERE id=? AND active=1", (plan_id,)).fetchone()
            if not plan:
                raise ApiError(400, "Plano inválido ou inativo.")
            seller_id = user["id"]
            if has_permission(user, "sales.all") and data.get("seller_id"):
                seller_id = int(data["seller_id"])
            seller = conn.execute("SELECT id,team_id,active FROM users WHERE id=?", (seller_id,)).fetchone()
            if not seller or not seller["active"]:
                raise ApiError(400, "Vendedor inválido.")
            fields = self.sale_general_values(data)
            if not fields["cpf_cnpj"]:
                raise ApiError(400, "CPF ou CNPJ é obrigatório para cadastrar a venda.")
            now = utc_now()
            cur = conn.execute(
                """INSERT INTO sales(
                    person_type,client_name,cpf_cnpj,birth_date,mother_name,phone,contact_phone,email,
                    cep,address,address_number,complement,neighborhood,city,uf,property_type,
                    plan_id,plan_name_snapshot,plan_price_snapshot,provider,service,
                    payment_method,due_day,channel,suggested_date,suggested_period,notes,
                    seller_id,team_id,status,activation_status,biometric_status,installation_status,
                    created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'nova',
                    'aguardando_ativacao','biometria_pendente','aguardando_instalacao',?,?)""",
                (
                    fields["person_type"], client_name, fields["cpf_cnpj"], fields["birth_date"], fields["mother_name"],
                    phone, fields["contact_phone"], fields["email"], fields["cep"], fields["address"],
                    fields["address_number"], fields["complement"], fields["neighborhood"], fields["city"],
                    fields["uf"], fields["property_type"], plan_id, plan["name"], plan["price"],
                    plan["provider"], plan["service"], fields["payment_method"], fields["due_day"],
                    fields["channel"], fields["suggested_date"], fields["suggested_period"], fields["notes"],
                    seller_id, seller["team_id"], now, now,
                ),
            )
            sale_id = cur.lastrowid
            conn.execute(
                "INSERT INTO sale_history(sale_id,user_id,event_type,details,created_at) VALUES(?,?,'created',?,?)",
                (sale_id, user["id"], "Venda cadastrada", now),
            )
        audit(user["id"], "sale.create", "sale", sale_id, {"client": client_name}, self.client_ip())
        self.trigger_webhook("sale.created", {"sale_id": sale_id, "client_name": client_name})
        self.send_json(201, {"ok": True, "id": sale_id, "message": "Venda cadastrada."})

    GENERAL_SALE_FIELDS = {
        "person_type", "client_name", "cpf_cnpj", "birth_date", "mother_name", "phone",
        "contact_phone", "email", "cep", "address", "address_number", "complement",
        "neighborhood", "city", "uf", "property_type", "plan_id", "payment_method",
        "due_day", "channel", "suggested_date", "suggested_period", "notes", "seller_id"
    }

    def sale_general_values(self, data: dict[str, Any]) -> dict[str, Any]:
        person_type = (data.get("person_type") or "CPF").strip().upper()
        if person_type not in {"CPF", "CNPJ"}:
            raise ApiError(400, "Tipo de pessoa inválido.")
        document = only_digits(data.get("cpf_cnpj") or "")
        if document:
            valid_document = validate_cpf(document) if person_type == "CPF" else validate_cnpj(document)
            if not valid_document:
                raise ApiError(400, f"{person_type} inválido.")
        contact_raw = data.get("contact_phone") or ""
        contact_phone = normalize_mobile_phone(contact_raw) if only_digits(contact_raw) else ""
        if only_digits(contact_raw) and not contact_phone:
            raise ApiError(400, "Segundo telefone inválido. Informe um celular com DDD.")
        result = {
            "person_type": person_type,
            "cpf_cnpj": document or None,
            "birth_date": (data.get("birth_date") or "").strip() or None,
            "mother_name": (data.get("mother_name") or "").strip()[:160] or None,
            "contact_phone": contact_phone or None,
            "email": normalize_email(data.get("email") or "")[:160] or None,
            "cep": only_digits(data.get("cep") or "")[:8] or None,
            "address": (data.get("address") or "").strip()[:240] or None,
            "address_number": (data.get("address_number") or "").strip()[:40] or None,
            "complement": (data.get("complement") or "").strip()[:120] or None,
            "neighborhood": (data.get("neighborhood") or "").strip()[:120] or None,
            "city": (data.get("city") or "").strip()[:120] or None,
            "uf": (data.get("uf") or "").strip().upper()[:2] or None,
            "property_type": (data.get("property_type") or "").strip() or None,
            "payment_method": (data.get("payment_method") or "").strip() or None,
            "due_day": (data.get("due_day") or "").strip() or None,
            "channel": (data.get("channel") or "").strip() or None,
            "suggested_date": (data.get("suggested_date") or "").strip() or None,
            "suggested_period": (data.get("suggested_period") or "").strip() or None,
            "notes": (data.get("notes") or "").strip()[:5000] or None,
        }
        validations = [
            ("property_type", "property_type"), ("payment_method", "payment_method"),
            ("due_day", "due_day"), ("channel", "sales_channel"),
            ("suggested_period", "period"),
        ]
        for field, category in validations:
            if not catalog_exists(category, result[field]):
                raise ApiError(400, f"Valor inválido no campo {field}.")
        if result["birth_date"] and not validate_iso_date(result["birth_date"], False):
            raise ApiError(400, "Data de nascimento inválida.")
        if result["suggested_date"] and not validate_iso_date(result["suggested_date"], False):
            raise ApiError(400, "Data sugerida inválida.")
        return result

    def api_sale_update(self, user: dict[str, Any], sale_id: int) -> None:
        data = self.read_json()
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            if not row:
                raise ApiError(404, "Venda não encontrada.")
            sale = dict(row)
            permitted = has_permission(user, "sales.edit_all") or (has_permission(user, "sales.edit_own") and sale["seller_id"] == user["id"])
            if not permitted:
                raise ApiError(403, "Sem permissão para editar esta venda.")
            updates: dict[str, Any] = {}
            if "client_name" in data:
                name = (data.get("client_name") or "").strip()
                if len(name) < 3:
                    raise ApiError(400, "Nome do cliente inválido.")
                updates["client_name"] = name
            if "phone" in data:
                phone = normalize_mobile_phone(data.get("phone") or "")
                if not phone:
                    raise ApiError(400, "Telefone inválido. Informe um celular brasileiro com DDD.")
                updates["phone"] = phone
            if "person_type" in data or "cpf_cnpj" in data:
                proposed_type = (data.get("person_type") or sale.get("person_type") or "CPF").strip().upper()
                proposed_document = only_digits(data.get("cpf_cnpj") if "cpf_cnpj" in data else sale.get("cpf_cnpj") or "")
                if not proposed_document:
                    raise ApiError(400, "CPF ou CNPJ é obrigatório.")
                if proposed_type == "CPF" and not validate_cpf(proposed_document):
                    raise ApiError(400, "CPF inválido.")
                if proposed_type == "CNPJ" and not validate_cnpj(proposed_document):
                    raise ApiError(400, "CNPJ inválido.")
                if proposed_type not in {"CPF", "CNPJ"}:
                    raise ApiError(400, "Tipo de pessoa inválido.")
                data = dict(data)
                data["person_type"] = proposed_type
                data["cpf_cnpj"] = proposed_document
            values = self.sale_general_values(data)
            for key in values:
                if key in data:
                    updates[key] = values[key]
            if "plan_id" in data:
                plan_id = int(data.get("plan_id") or 0)
                plan = conn.execute("SELECT * FROM plans WHERE id=? AND active=1", (plan_id,)).fetchone()
                if not plan:
                    raise ApiError(400, "Plano inválido.")
                updates.update({"plan_id": plan_id, "plan_name_snapshot": plan["name"],
                                "plan_price_snapshot": plan["price"], "provider": plan["provider"],
                                "service": plan["service"]})
            if "seller_id" in data:
                if not has_permission(user, "sales.edit_all"):
                    raise ApiError(403, "Apenas gestão pode trocar o vendedor.")
                seller_id = int(data.get("seller_id") or 0)
                seller = conn.execute("SELECT id,team_id,active FROM users WHERE id=?", (seller_id,)).fetchone()
                if not seller or not seller["active"]:
                    raise ApiError(400, "Vendedor inválido.")
                updates["seller_id"] = seller_id
                updates["team_id"] = seller["team_id"]
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            now = utc_now()
            for field, new_value in updates.items():
                old_value = sale.get(field)
                if str(old_value or "") != str(new_value or ""):
                    conn.execute(
                        """INSERT INTO sale_history(sale_id,user_id,event_type,field_name,old_value,new_value,details,created_at)
                        VALUES(?,?,'general_update',?,?,?,?,?)""",
                        (sale_id, user["id"], field, str(old_value or ""), str(new_value or ""), "Cadastro atualizado", now),
                    )
            assignments = ",".join(f"{field}=?" for field in updates)
            conn.execute(f"UPDATE sales SET {assignments},updated_at=? WHERE id=?", [*updates.values(), now, sale_id])
        audit(user["id"], "sale.update", "sale", sale_id, {"fields": list(updates)}, self.client_ip())
        self.trigger_webhook("sale.updated", {"sale_id": sale_id, "fields": list(updates)})
        self.send_json(200, {"ok": True, "message": "Venda atualizada."})

    WORKFLOW_FIELDS = {
        "status": "sale_status", "activation_status": "activation_status",
        "biometric_status": "biometric_status", "installation_status": "installation_status",
        "appointment_status": "appointment_status", "appointment_period": "period",
        "cancelled_reason": "cancellation_reason"
    }

    def api_sale_workflow(self, user: dict[str, Any], sale_id: int) -> None:
        if not has_permission(user, "workflow.bko"):
            raise ApiError(403, "Sem permissão para tratar o fluxo BKO.")
        data = self.read_json()
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            if not row:
                raise ApiError(404, "Venda não encontrada.")
            sale = dict(row)
            if user["role_code"] == "bko" and sale["bko_user_id"] not in (None, user["id"]):
                raise ApiError(403, "Venda atribuída a outro BKO.")
            updates: dict[str, Any] = {}
            for field, category in self.WORKFLOW_FIELDS.items():
                if field in data:
                    value = (data.get(field) or "").strip() or None
                    if value and not catalog_exists(category, value):
                        raise ApiError(400, f"Valor inválido em {field}.")
                    updates[field] = value
            for field in ("appointment_date", "os_number"):
                if field in data:
                    value = (data.get(field) or "").strip() or None
                    if field == "appointment_date" and value and not validate_iso_date(value, False):
                        raise ApiError(400, "Data de agendamento inválida.")
                    updates[field] = value
            for field in ("bypass_required", "handling_biometric", "handling_installation"):
                if field in data:
                    updates[field] = 1 if bool(data.get(field)) else 0
            if "bko_user_id" in data:
                target = data.get("bko_user_id")
                target_id = int(target) if target else None
                if not has_permission(user, "workflow.assign"):
                    if user["role_code"] != "bko" or target_id not in (None, user["id"]):
                        raise ApiError(403, "Sem permissão para atribuir BKO.")
                    target_id = user["id"] if sale["bko_user_id"] is None else sale["bko_user_id"]
                if target_id:
                    bko = conn.execute("SELECT id FROM users WHERE id=? AND role_code IN ('bko','manager','owner') AND active=1", (target_id,)).fetchone()
                    if not bko:
                        raise ApiError(400, "Responsável BKO inválido.")
                updates["bko_user_id"] = target_id
            elif user["role_code"] == "bko" and sale["bko_user_id"] is None:
                updates["bko_user_id"] = user["id"]
            if updates.get("installation_status") in ("instalado", "instalado_regra_pdv"):
                updates["status"] = "instalada"
                updates["installed_at"] = utc_now()
            if updates.get("status") == "cancelada" and not updates.get("cancelled_reason") and not sale.get("cancelled_reason"):
                raise ApiError(400, "Informe o motivo do cancelamento.")
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            now = utc_now()
            for field, new_value in updates.items():
                old_value = sale.get(field)
                if str(old_value or "") != str(new_value or ""):
                    conn.execute(
                        """INSERT INTO sale_history(sale_id,user_id,event_type,field_name,old_value,new_value,details,created_at)
                        VALUES(?,?,'workflow_update',?,?,?,?,?)""",
                        (sale_id, user["id"], field, str(old_value or ""), str(new_value or ""), "Fluxo operacional atualizado", now),
                    )
            assignments = ",".join(f"{field}=?" for field in updates)
            conn.execute(f"UPDATE sales SET {assignments},updated_at=? WHERE id=?", [*updates.values(), now, sale_id])
        audit(user["id"], "sale.workflow", "sale", sale_id, {"fields": list(updates)}, self.client_ip())
        self.trigger_webhook("sale.workflow_updated", {"sale_id": sale_id, "fields": list(updates)})
        self.send_json(200, {"ok": True, "message": "Fluxo atualizado."})

    def decorate_sale(self, sale: dict[str, Any]) -> dict[str, Any]:
        sale["status_label"] = label_for("sale_status", sale.get("status"))
        sale["activation_status_label"] = label_for("activation_status", sale.get("activation_status"))
        sale["biometric_status_label"] = label_for("biometric_status", sale.get("biometric_status"))
        sale["installation_status_label"] = label_for("installation_status", sale.get("installation_status"))
        sale["appointment_status_label"] = label_for("appointment_status", sale.get("appointment_status"))
        sale["payment_method_label"] = label_for("payment_method", sale.get("payment_method"))
        sale["channel_label"] = label_for("sales_channel", sale.get("channel"))
        return sale

    # ------------------------- usuários/equipes -------------------------
    def api_users_list(self) -> None:
        user = self.require_permission("users.view")
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT u.id,u.name,u.email,COALESCE(u.custom_role_code,u.role_code) AS role_code,
                    u.role_code AS base_role,r.name AS role_name,u.team_id,u.active,u.must_change_password,
                    u.last_login_at,u.created_at,t.name AS team_name
                    FROM users u
                    LEFT JOIN teams t ON t.id=u.team_id
                    LEFT JOIN roles r ON r.code=COALESCE(u.custom_role_code,u.role_code)
                    ORDER BY u.active DESC,u.name"""
            ).fetchall()
        self.send_json(200, {"ok": True, "users": [dict(r) for r in rows]})

    def api_user_create(self, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "users.manage"):
            raise ApiError(403, "Apenas o Dono administra usuários.")
        data = self.read_json()
        name = (data.get("name") or "").strip()
        email = normalize_email(data.get("email") or "")
        requested_role = (data.get("role_code") or "seller").strip()
        password = data.get("password") or ""
        team_id = int(data.get("team_id")) if data.get("team_id") else None
        with db_connect() as conn:
            role_row = conn.execute(
                "SELECT code,base_role,active FROM roles WHERE code=?",
                (requested_role,),
            ).fetchone()
            if len(name) < 3 or "@" not in email or not role_row or not role_row["active"]:
                raise ApiError(400, "Dados do usuário ou cargo inválidos.")
            if role_row["base_role"] == "owner" and actor.get("role_code") != "owner":
                raise ApiError(403, "Somente um Dono pode nomear outro Dono.")
            if team_id and not conn.execute("SELECT 1 FROM teams WHERE id=? AND active=1", (team_id,)).fetchone():
                raise ApiError(400, "Equipe inválida ou inativa.")
            error = validate_password(password)
            if error:
                raise ApiError(400, error)
            base_role = role_row["base_role"]
            custom_role = None if requested_role == base_role else requested_role
            now = utc_now()
            try:
                cur = conn.execute(
                    """INSERT INTO users(name,email,password_hash,role_code,custom_role_code,team_id,active,must_change_password,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,1,?,?,?)""",
                    (name, email, hash_password(password), base_role, custom_role, team_id,
                     1 if data.get("must_change_password", True) else 0, now, now),
                )
                user_id = cur.lastrowid
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe usuário com este e-mail.")
        audit(actor["id"], "user.create", "user", user_id, {"email": email, "role": requested_role}, self.client_ip())
        self.send_json(201, {"ok": True, "id": user_id, "message": "Usuário criado."})

    def api_user_update(self, actor: dict[str, Any], user_id: int) -> None:
        if not has_permission(actor, "users.manage"):
            raise ApiError(403, "Apenas o Dono administra usuários.")
        data = self.read_json()
        with db_connect() as conn:
            target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                raise ApiError(404, "Usuário não encontrado.")
            updates: dict[str, Any] = {}
            current_effective = target["custom_role_code"] or target["role_code"]
            requested_role = (data.get("role_code") or current_effective).strip() if "role_code" in data else current_effective
            role_row = conn.execute("SELECT code,base_role,active FROM roles WHERE code=?", (requested_role,)).fetchone()
            if not role_row or not role_row["active"]:
                raise ApiError(400, "Cargo inválido ou inativo.")
            if (target["role_code"] == "owner" or role_row["base_role"] == "owner") and actor.get("role_code") != "owner":
                raise ApiError(403, "Somente um Dono pode alterar contas de Dono.")
            if "name" in data:
                name = (data.get("name") or "").strip()
                if len(name) < 3:
                    raise ApiError(400, "Nome inválido.")
                updates["name"] = name
            if "email" in data:
                email = normalize_email(data.get("email") or "")
                if "@" not in email:
                    raise ApiError(400, "E-mail inválido.")
                updates["email"] = email
            if "team_id" in data:
                new_team_id = int(data["team_id"]) if data.get("team_id") else None
                if new_team_id and not conn.execute("SELECT 1 FROM teams WHERE id=? AND active=1", (new_team_id,)).fetchone():
                    raise ApiError(400, "Equipe inválida ou inativa.")
                updates["team_id"] = new_team_id
            if "role_code" in data:
                updates["role_code"] = role_row["base_role"]
                updates["custom_role_code"] = None if requested_role == role_row["base_role"] else requested_role
            if "active" in data:
                updates["active"] = 1 if bool(data.get("active")) else 0
            if "password" in data and data.get("password"):
                error = validate_password(data["password"])
                if error:
                    raise ApiError(400, error)
                updates["password_hash"] = hash_password(data["password"])
                updates["must_change_password"] = 1 if data.get("must_change_password", True) else 0
            resulting_role = updates.get("role_code", target["role_code"])
            resulting_active = updates.get("active", target["active"])
            if user_id == actor["id"] and not resulting_active:
                raise ApiError(400, "Você não pode bloquear sua própria conta.")
            if target["role_code"] == "owner" and (resulting_role != "owner" or not resulting_active):
                owners = conn.execute("SELECT COUNT(*) FROM users WHERE role_code='owner' AND active=1").fetchone()[0]
                if owners <= 1:
                    raise ApiError(400, "O último Dono ativo não pode ser rebaixado ou bloqueado.")
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            assignments = ",".join(f"{key}=?" for key in updates)
            try:
                conn.execute(f"UPDATE users SET {assignments},updated_at=? WHERE id=?", [*updates.values(), utc_now(), user_id])
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe usuário com este e-mail.")
            if not resulting_active or "password_hash" in updates:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit(actor["id"], "user.update", "user", user_id, {"fields": list(updates), "role": requested_role}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Usuário atualizado."})

    def api_me_get(self) -> None:
        user, _, _ = self.require_user()
        self.send_json(200, {"ok": True, "user": self.public_user(user)})

    def api_profile_update(self, user: dict[str, Any]) -> None:
        data = self.read_json()
        name = (data.get("name") or "").strip()
        display_name = (data.get("display_name") or "").strip()
        email = normalize_email(data.get("email") or "")
        phone_raw = only_digits(data.get("phone") or "")
        bio = (data.get("bio") or "").strip()
        current_password = data.get("current_password") or ""
        if len(name) < 3:
            raise ApiError(400, "Informe seu nome completo.")
        if display_name and len(display_name) < 2:
            raise ApiError(400, "O nome de exibição precisa ter ao menos 2 caracteres.")
        if "@" not in email or len(email) > 180:
            raise ApiError(400, "E-mail inválido.")
        if phone_raw and (len(phone_raw) not in (10, 11) or phone_raw[:2] not in BRAZILIAN_DDDS):
            raise ApiError(400, "Telefone inválido. Informe DDD e número.")
        if len(bio) > 300:
            raise ApiError(400, "A descrição pessoal pode ter no máximo 300 caracteres.")
        with db_connect() as conn:
            current = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
            if not current:
                raise ApiError(404, "Usuário não encontrado.")
            if email != current["email"]:
                if not current_password or not verify_password(current_password, current["password_hash"]):
                    raise ApiError(400, "Informe a senha atual para alterar o e-mail.")
            try:
                conn.execute(
                    """UPDATE users SET name=?,display_name=?,email=?,phone=?,bio=?,updated_at=? WHERE id=?""",
                    (name, display_name or None, email, phone_raw or None, bio or None, utc_now(), user["id"]),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Este e-mail já está em uso por outro usuário.")
        audit(user["id"], "user.profile_update", "user", user["id"],
              {"fields": ["name", "display_name", "email", "phone", "bio"]}, self.client_ip())
        refreshed, _, _ = self.current_user()
        self.send_json(200, {"ok": True, "message": "Perfil atualizado.", "user": self.public_user(refreshed or user)})

    def api_theme_update(self, user: dict[str, Any]) -> None:
        data = self.read_json()
        theme = (data.get("theme") or "").strip().lower()
        if theme not in {"dark", "light"}:
            raise ApiError(400, "Tema inválido.")
        with db_connect() as conn:
            conn.execute("UPDATE users SET theme_preference=?,updated_at=? WHERE id=?",
                         (theme, utc_now(), user["id"]))
        audit(user["id"], "user.theme_update", "user", user["id"], {"theme": theme}, self.client_ip())
        self.send_json(200, {"ok": True, "theme": theme})

    def api_change_password(self, user: dict[str, Any]) -> None:
        data = self.read_json()
        current = data.get("current_password") or ""
        new = data.get("new_password") or ""
        error = validate_password(new)
        if error:
            raise ApiError(400, error)
        with db_connect() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id=?", (user["id"],)).fetchone()
            if not row or not verify_password(current, row["password_hash"]):
                raise ApiError(400, "Senha atual incorreta.")
            conn.execute("UPDATE users SET password_hash=?,must_change_password=0,updated_at=? WHERE id=?",
                         (hash_password(new), utc_now(), user["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        audit(user["id"], "user.password_change", "user", user["id"], {}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Senha alterada. Entre novamente."},
                       {"Set-Cookie": f"{COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax{'; Secure' if self.is_https() else ''}"})

    def api_teams_list(self) -> None:
        user, _, _ = self.require_user()
        if not (has_permission(user, "teams.view") or has_permission(user, "teams.manage") or has_permission(user, "sales.create")):
            raise ApiError(403, "Sem permissão para visualizar equipes.")
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT t.*,u.name AS manager_name,
                    (SELECT COUNT(*) FROM users x WHERE x.team_id=t.id AND x.active=1) AS members
                    FROM teams t LEFT JOIN users u ON u.id=t.manager_id ORDER BY t.active DESC,t.name"""
            ).fetchall()
        self.send_json(200, {"ok": True, "teams": [dict(r) for r in rows]})

    def api_team_create(self, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "teams.manage"):
            raise ApiError(403, "Sem permissão para criar equipes.")
        data = self.read_json()
        name = (data.get("name") or "").strip()
        if len(name) < 2:
            raise ApiError(400, "Nome de equipe inválido.")
        manager_id = int(data["manager_id"]) if data.get("manager_id") else None
        if manager_id:
            with db_connect() as check_conn:
                if not check_conn.execute("SELECT 1 FROM users WHERE id=? AND role_code IN ('manager','owner') AND active=1", (manager_id,)).fetchone():
                    raise ApiError(400, "Gerente inválido.")
        now = utc_now()
        try:
            with db_connect() as conn:
                cur = conn.execute(
                    "INSERT INTO teams(name,manager_id,monthly_target,active,created_at,updated_at) VALUES(?,?,?,1,?,?)",
                    (name, manager_id, int(data.get("monthly_target") or 0), now, now),
                )
                team_id = cur.lastrowid
        except sqlite3.IntegrityError:
            raise ApiError(409, "Já existe equipe com este nome.")
        audit(actor["id"], "team.create", "team", team_id, {"name": name}, self.client_ip())
        self.send_json(201, {"ok": True, "id": team_id})

    def api_team_update(self, actor: dict[str, Any], team_id: int) -> None:
        if not has_permission(actor, "teams.manage"):
            raise ApiError(403, "Sem permissão para editar equipes.")
        data = self.read_json()
        with db_connect() as conn:
            if not conn.execute("SELECT 1 FROM teams WHERE id=?", (team_id,)).fetchone():
                raise ApiError(404, "Equipe não encontrada.")
            updates: dict[str, Any] = {}
            for key in ("name",):
                if key in data:
                    value = (data.get(key) or "").strip()
                    if len(value) < 2:
                        raise ApiError(400, "Nome inválido.")
                    updates[key] = value
            if "manager_id" in data:
                new_manager_id = int(data["manager_id"]) if data.get("manager_id") else None
                if new_manager_id and not conn.execute("SELECT 1 FROM users WHERE id=? AND role_code IN ('manager','owner') AND active=1", (new_manager_id,)).fetchone():
                    raise ApiError(400, "Gerente inválido.")
                updates["manager_id"] = new_manager_id
            if "monthly_target" in data:
                updates["monthly_target"] = max(0, int(data.get("monthly_target") or 0))
            if "active" in data:
                updates["active"] = 1 if data.get("active") else 0
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            assignments = ",".join(f"{k}=?" for k in updates)
            try:
                conn.execute(f"UPDATE teams SET {assignments},updated_at=? WHERE id=?", [*updates.values(), utc_now(), team_id])
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe equipe com este nome.")
        audit(actor["id"], "team.update", "team", team_id, {"fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True})

    # ------------------------- planos/catálogos/cargos -------------------------
    def api_plans_list(self, query: dict[str, list[str]]) -> None:
        user, _, _ = self.require_user()
        include_all = (query.get("all") or ["0"])[0] == "1" and has_permission(user, "plans.manage")
        where = "1=1" if include_all else "active=1"
        with db_connect() as conn:
            rows = conn.execute(f"SELECT * FROM plans WHERE {where} ORDER BY sort_order,name").fetchall()
        self.send_json(200, {"ok": True, "plans": [dict(r) for r in rows]})

    def plan_values(self, data: dict[str, Any]) -> dict[str, Any]:
        provider = (data.get("provider") or "").strip()
        service = (data.get("service") or "").strip()
        name = (data.get("name") or "").strip()
        if not provider or not service or len(name) < 2:
            raise ApiError(400, "Operadora, serviço e nome do plano são obrigatórios.")
        try:
            price = float(str(data.get("price") or 0).replace(",", "."))
        except ValueError:
            raise ApiError(400, "Preço inválido.")
        return {"provider": provider[:80], "service": service[:80], "name": name[:160],
                "speed": (data.get("speed") or "").strip()[:80] or None,
                "price": max(0, price), "benefits": (data.get("benefits") or "").strip()[:2000] or None,
                "uf_list": (data.get("uf_list") or "").strip().upper()[:200] or None,
                "sort_order": int(data.get("sort_order") or 0),
                "active": 1 if data.get("active", True) else 0}

    def api_plan_create(self, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "plans.manage"):
            raise ApiError(403, "Sem permissão para administrar planos.")
        values = self.plan_values(self.read_json())
        now = utc_now()
        with db_connect() as conn:
            cur = conn.execute(
                """INSERT INTO plans(provider,service,name,speed,price,benefits,uf_list,sort_order,active,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                [*values.values(), now, now],
            )
            plan_id = cur.lastrowid
        audit(actor["id"], "plan.create", "plan", plan_id, values, self.client_ip())
        self.send_json(201, {"ok": True, "id": plan_id})

    def api_plan_update(self, actor: dict[str, Any], plan_id: int) -> None:
        if not has_permission(actor, "plans.manage"):
            raise ApiError(403, "Sem permissão para administrar planos.")
        data = self.read_json()
        with db_connect() as conn:
            old = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
            if not old:
                raise ApiError(404, "Plano não encontrado.")
        merged = dict(old)
        merged.update(data)
        values = self.plan_values(merged)
        with db_connect() as conn:
            conn.execute(
                """UPDATE plans SET provider=?,service=?,name=?,speed=?,price=?,benefits=?,uf_list=?,sort_order=?,active=?,updated_at=?
                WHERE id=?""",
                [*values.values(), utc_now(), plan_id],
            )
        audit(actor["id"], "plan.update", "plan", plan_id, values, self.client_ip())
        self.send_json(200, {"ok": True})

    def api_catalogs(self, query: dict[str, list[str]]) -> None:
        user, _, _ = self.require_user()
        category = (query.get("category") or [""])[0].strip()
        include_all = (query.get("all") or ["0"])[0] == "1" and has_permission(user, "catalogs.manage")
        where = []
        params: list[Any] = []
        if category:
            where.append("category=?")
            params.append(category)
        if not include_all:
            where.append("active=1")
        clause = " AND ".join(where) if where else "1=1"
        with db_connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM catalog_items WHERE {clause} ORDER BY category,sort_order,label", params
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except Exception:
                item["metadata"] = {}
            grouped.setdefault(item["category"], []).append(item)
        self.send_json(200, {"ok": True, "catalogs": grouped})

    def api_catalog_create(self, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "catalogs.manage"):
            raise ApiError(403, "Sem permissão para administrar catálogos.")
        data = self.read_json()
        category = (data.get("category") or "").strip().lower()
        code = (data.get("code") or "").strip().lower().replace(" ", "_")
        label = (data.get("label") or "").strip()
        if not category or not code or not label:
            raise ApiError(400, "Categoria, código e descrição são obrigatórios.")
        now = utc_now()
        try:
            with db_connect() as conn:
                cur = conn.execute(
                    """INSERT INTO catalog_items(category,code,label,sort_order,active,metadata_json,created_at,updated_at)
                    VALUES(?,?,?,?,1,?,?,?)""",
                    (category, code, label, int(data.get("sort_order") or 0),
                     json_dumps(data.get("metadata") or {}), now, now),
                )
                item_id = cur.lastrowid
        except sqlite3.IntegrityError:
            raise ApiError(409, "Já existe este código na categoria.")
        audit(actor["id"], "catalog.create", "catalog", item_id, {"category": category, "code": code}, self.client_ip())
        self.send_json(201, {"ok": True, "id": item_id})

    def api_catalog_update(self, actor: dict[str, Any], item_id: int) -> None:
        if not has_permission(actor, "catalogs.manage"):
            raise ApiError(403, "Sem permissão para administrar catálogos.")
        data = self.read_json()
        with db_connect() as conn:
            item = conn.execute("SELECT * FROM catalog_items WHERE id=?", (item_id,)).fetchone()
            if not item:
                raise ApiError(404, "Item não encontrado.")
            updates: dict[str, Any] = {}
            for key in ("label", "code"):
                if key in data:
                    value = (data.get(key) or "").strip()
                    if not value:
                        raise ApiError(400, f"{key} não pode ficar vazio.")
                    updates[key] = value.lower().replace(" ", "_") if key == "code" else value
            if "sort_order" in data:
                updates["sort_order"] = int(data.get("sort_order") or 0)
            if "active" in data:
                updates["active"] = 1 if data.get("active") else 0
            if "metadata" in data:
                updates["metadata_json"] = json_dumps(data.get("metadata") or {})
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            assignments = ",".join(f"{k}=?" for k in updates)
            try:
                conn.execute(f"UPDATE catalog_items SET {assignments},updated_at=? WHERE id=?",
                             [*updates.values(), utc_now(), item_id])
            except sqlite3.IntegrityError:
                raise ApiError(409, "Código duplicado nesta categoria.")
        audit(actor["id"], "catalog.update", "catalog", item_id, {"fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True})

    def api_roles(self) -> None:
        user, _, _ = self.require_user()
        if not (has_permission(user, "roles.manage") or has_permission(user, "users.view")):
            raise ApiError(403, "Sem permissão para visualizar cargos.")
        with db_connect() as conn:
            permissions = [dict(r) for r in conn.execute("SELECT * FROM permissions ORDER BY module,description").fetchall()]
            role_rows = [dict(r) for r in conn.execute(
                """SELECT r.*,
                    COALESCE((SELECT COUNT(*) FROM users u WHERE COALESCE(u.custom_role_code,u.role_code)=r.code),0) AS users_count,
                    COALESCE((SELECT COUNT(*) FROM users u WHERE COALESCE(u.custom_role_code,u.role_code)=r.code AND u.active=1),0) AS active_users_count
                    FROM roles r ORDER BY r.is_system DESC, r.name"""
            ).fetchall()]
            permission_rows = conn.execute(
                "SELECT role_code,permission_code,allowed FROM role_permissions WHERE allowed=1"
            ).fetchall()
        role_map: dict[str, list[str]] = {role["code"]: [] for role in role_rows}
        for row in permission_rows:
            role_map.setdefault(row["role_code"], []).append(row["permission_code"])
        all_permissions = [p["code"] for p in permissions]
        for role in role_rows:
            role["permissions"] = all_permissions[:] if role["code"] == "owner" else sorted(role_map.get(role["code"], []))
            role["active"] = bool(role["active"])
            role["is_system"] = bool(role["is_system"])
        self.send_json(200, {"ok": True, "permissions": permissions, "roles": role_rows})

    def api_role_create(self, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "roles.manage"):
            raise ApiError(403, "Sem permissão para criar cargos.")
        data = self.read_json()
        name = (data.get("name") or "").strip()
        code = (data.get("code") or "").strip().lower()
        description = (data.get("description") or "").strip()
        base_role = (data.get("base_role") or "").strip()
        permission_codes = data.get("permissions")
        if len(name) < 2:
            raise ApiError(400, "Informe um nome de cargo válido.")
        if not code or len(code) > 40 or not all(ch.isalnum() or ch == "_" for ch in code):
            raise ApiError(400, "O código deve conter apenas letras, números e sublinhado.")
        if code in SYSTEM_ROLES:
            raise ApiError(409, "Este código é reservado para um cargo nativo.")
        if base_role not in {"manager", "bko", "seller"}:
            raise ApiError(400, "Selecione Gerente, BKO ou Vendedor como cargo-base.")
        valid = {permission_code for permission_code, _, _ in PERMISSIONS}
        with db_connect() as conn:
            if permission_codes is None:
                selected = get_role_permissions(base_role)
            elif isinstance(permission_codes, list):
                selected = {str(item) for item in permission_codes if str(item) in valid}
            else:
                raise ApiError(400, "Lista de permissões inválida.")
            now = utc_now()
            try:
                conn.execute(
                    """INSERT INTO roles(code,name,description,base_role,is_system,active,created_at,updated_at)
                    VALUES(?,?,?,?,0,1,?,?)""",
                    (code, name, description, base_role, now, now),
                )
                conn.executemany(
                    "INSERT INTO role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)",
                    [(code, permission) for permission in sorted(selected)],
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe um cargo com este nome ou código.")
        audit(actor["id"], "role.create", "role", code, {"name": name, "base_role": base_role, "permissions": sorted(selected)}, self.client_ip())
        self.send_json(201, {"ok": True, "code": code, "message": "Cargo criado."})

    def api_role_update(self, actor: dict[str, Any], role: str) -> None:
        if not has_permission(actor, "roles.manage"):
            raise ApiError(403, "Sem permissão para administrar cargos.")
        data = self.read_json()
        with db_connect() as conn:
            current = conn.execute("SELECT * FROM roles WHERE code=?", (role,)).fetchone()
            if not current:
                raise ApiError(404, "Cargo não encontrado.")
            if role == "owner":
                raise ApiError(400, "O cargo Dono possui acesso total e não pode ser alterado.")
            updates: dict[str, Any] = {}
            if not current["is_system"]:
                if "name" in data:
                    name = (data.get("name") or "").strip()
                    if len(name) < 2:
                        raise ApiError(400, "Nome do cargo inválido.")
                    updates["name"] = name
                if "description" in data:
                    updates["description"] = (data.get("description") or "").strip()
                if "base_role" in data:
                    base_role = (data.get("base_role") or "").strip()
                    if base_role not in {"manager", "bko", "seller"}:
                        raise ApiError(400, "Cargo-base inválido.")
                    updates["base_role"] = base_role
                if "active" in data:
                    active = 1 if bool(data.get("active")) else 0
                    if not active:
                        in_use = conn.execute(
                            "SELECT COUNT(*) FROM users WHERE custom_role_code=?", (role,)
                        ).fetchone()[0]
                        if in_use:
                            raise ApiError(400, "Transfira os usuários vinculados antes de desativar este cargo.")
                    updates["active"] = active
            codes = data.get("permissions")
            valid = {code for code, _, _ in PERMISSIONS}
            selected: set[str] | None = None
            if codes is not None:
                if not isinstance(codes, list):
                    raise ApiError(400, "Lista de permissões inválida.")
                selected = {str(code) for code in codes if str(code) in valid}
            if updates:
                updates["updated_at"] = utc_now()
                assignments = ",".join(f"{key}=?" for key in updates)
                try:
                    conn.execute(f"UPDATE roles SET {assignments} WHERE code=?", [*updates.values(), role])
                except sqlite3.IntegrityError:
                    raise ApiError(409, "Já existe outro cargo com este nome.")
                if "base_role" in updates:
                    conn.execute("UPDATE users SET role_code=?,updated_at=? WHERE custom_role_code=?",
                                 (updates["base_role"], utc_now(), role))
            if selected is not None:
                conn.execute("DELETE FROM role_permissions WHERE role_code=?", (role,))
                conn.executemany(
                    "INSERT INTO role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)",
                    [(role, code) for code in sorted(selected)],
                )
            if not updates and selected is None:
                raise ApiError(400, "Nenhuma alteração enviada.")
        audit(actor["id"], "role.update", "role", role, {"fields": list(updates), "permissions": sorted(selected) if selected is not None else None}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Cargo atualizado."})

    # ------------------------- auditoria, backups, integrações -------------------------
    def api_audit(self, query: dict[str, list[str]]) -> None:
        user = self.require_permission("audit.view")
        limit = min(1000, max(1, int((query.get("limit") or ["300"])[0])))
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT a.*,u.name AS user_name FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id
                   ORDER BY a.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        self.send_json(200, {"ok": True, "logs": [dict(r) for r in rows]})

    def api_backups_list(self) -> None:
        user = self.require_permission("backups.manage")
        files = []
        for path in sorted(BACKUP_DIR.glob("*_*.db"), reverse=True):
            stat = path.stat()
            files.append({"name": path.name, "size": stat.st_size,
                          "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")})
        self.send_json(200, {"ok": True, "backups": files})

    def api_backup_create(self, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "backups.manage"):
            raise ApiError(403, "Sem permissão para criar backup.")
        path = create_backup("manual")
        audit(actor["id"], "backup.create", "backup", path.name, {}, self.client_ip())
        self.send_json(201, {"ok": True, "name": path.name, "message": "Backup criado."})

    INTEGRATION_KEYS = {
        "powerbi_embed_url": False,
        "generic_webhook_url": False,
        "evolution_api_url": False,
        "evolution_api_key": True,
        "ai_provider": False,
        "groq_model": False,
        "openai_model": False,
    }

    def api_integrations_get(self) -> None:
        self.require_permission("integrations.manage")
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT key,value,secret,updated_at FROM system_settings WHERE key IN (%s)"
                % ",".join("?" for _ in self.INTEGRATION_KEYS),
                tuple(self.INTEGRATION_KEYS),
            ).fetchall()
        saved = {row["key"]: dict(row) for row in rows}
        result: dict[str, Any] = {}
        for key, secret in self.INTEGRATION_KEYS.items():
            row = saved.get(key)
            if secret:
                result[key] = {
                    "configured": bool(row and row["value"]),
                    "value": "••••••••" if row and row["value"] else "",
                }
            else:
                result[key] = {
                    "configured": bool(row and row["value"]),
                    "value": row["value"] if row else "",
                }
        ai_status = public_ai_status(
            provider_override=result.get("ai_provider", {}).get("value") or "",
            groq_model_override=result.get("groq_model", {}).get("value") or "",
            openai_model_override=result.get("openai_model", {}).get("value") or "",
        )
        result["ai"] = ai_status
        result["groq"] = ai_status.get("providers", {}).get("groq", {})
        result["openai"] = ai_status.get("providers", {}).get("openai", {})
        self.send_json(
            200,
            {
                "ok": True,
                "integrations": result,
                "notes": {
                    "powerbi": "URL incorporada funcional.",
                    "webhook": "Eventos de venda são enviados por POST.",
                    "evolution": "Credenciais armazenadas; conector específico depende da versão da API.",
                    "ai": (
                        "O ONE Intelligence pode usar GroqCloud, OpenAI ou análise local. "
                        "As chaves são lidas apenas das variáveis do Railway."
                    ),
                    "groq": (
                        "GROQ_API_KEY é lida com segurança do Railway; o modo local assume quando o limite gratuito é atingido."
                    ),
                    "openai": (
                        "OPENAI_API_KEY é opcional e pode permanecer desativada enquanto não houver faturamento."
                    ),
                },
            },
        )

    def api_powerbi_get(self) -> None:
        user = self.require_permission("powerbi.view")
        with db_connect() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key='powerbi_embed_url'").fetchone()
        self.send_json(200, {"ok": True, "embed_url": row["value"] if row else ""})

    def api_integrations_update(self, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "integrations.manage"):
            raise ApiError(403, "Sem permissão para administrar integrações.")
        data = self.read_json()
        now = utc_now()
        changed = []
        with db_connect() as conn:
            for key, secret in self.INTEGRATION_KEYS.items():
                if key not in data:
                    continue
                value = str(data.get(key) or "").strip()
                if value == "••••••••":
                    continue
                if data.get(f"clear_{key}"):
                    value = ""
                if value and key in {"powerbi_embed_url", "generic_webhook_url", "evolution_api_url"} and not value.lower().startswith(("http://", "https://")):
                    raise ApiError(400, f"A URL de {key} precisa começar com http:// ou https://.")
                if key == "ai_provider" and value and value not in {"auto", "groq", "openai", "local"}:
                    raise ApiError(400, "Provedor de IA inválido.")
                if key in {"groq_model", "openai_model"} and len(value) > 120:
                    raise ApiError(400, "O identificador do modelo é muito longo.")
                conn.execute(
                    """INSERT INTO system_settings(key,value,secret,updated_by,updated_at) VALUES(?,?,?,?,?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,secret=excluded.secret,
                    updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                    (key, value, 1 if secret else 0, actor["id"], now),
                )
                changed.append(key)
        # Credenciais externas antigas gravadas no SQLite deixam de ser utilizadas.
        # Segredos devem existir apenas nas variáveis GROQ_API_KEY e OPENAI_API_KEY.
        with db_connect() as conn:
            conn.execute("DELETE FROM system_settings WHERE key IN ('openai_api_key','groq_api_key')")
        audit(actor["id"], "integrations.update", "settings", None, {"keys": changed}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Integrações atualizadas."})

    def trigger_webhook(self, event: str, payload: dict[str, Any]) -> None:
        with db_connect() as conn:
            row = conn.execute("SELECT value FROM system_settings WHERE key='generic_webhook_url'").fetchone()
        if not row or not row["value"]:
            return
        url = row["value"]
        body = json.dumps({"event": event, "app": APP_NAME, "version": APP_VERSION,
                           "timestamp": utc_now(), "data": payload}, ensure_ascii=False).encode("utf-8")

        def send() -> None:
            try:
                request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=6) as response:
                    log(f"Webhook {event}: HTTP {response.status}")
            except Exception as exc:
                log(f"Webhook {event} falhou: {exc}")
        threading.Thread(target=send, daemon=True).start()

    def api_export_sales(self, query: dict[str, list[str]]) -> None:
        user = self.require_permission("export.data")
        where, params = sale_scope_sql(user)
        with db_connect() as conn:
            rows = conn.execute(
                f"""SELECT s.id,s.client_name,s.cpf_cnpj,s.phone,s.email,s.cep,s.address,s.city,s.uf,
                    s.plan_name_snapshot,s.plan_price_snapshot,s.status,s.activation_status,s.biometric_status,
                    s.installation_status,s.appointment_date,s.os_number,u.name seller,t.name team,s.created_at
                    FROM sales s JOIN users u ON u.id=s.seller_id LEFT JOIN teams t ON t.id=s.team_id
                    WHERE {where} ORDER BY s.id""", params).fetchall()
        out = io.StringIO()
        writer = csv.writer(out, delimiter=";")
        headers = ["ID", "CLIENTE", "CPF/CNPJ", "TELEFONE", "EMAIL", "CEP", "ENDEREÇO", "CIDADE", "UF",
                   "PLANO", "VALOR", "STATUS", "ATIVAÇÃO", "BIOMETRIA", "INSTALAÇÃO", "AGENDAMENTO", "OS",
                   "VENDEDOR", "EQUIPE", "CRIADO EM"]
        writer.writerow(headers)
        for row in rows:
            writer.writerow(list(row))
        self.send_csv(f"ONE_CRM_VENDAS_{local_today()}.csv", out.getvalue())


def create_backup(kind: str = "auto") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"one_crm_{kind}_{stamp}.db"
    with db_connect() as source:
        source.execute("PRAGMA wal_checkpoint(FULL)")
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    return target


def maybe_daily_backup() -> None:
    config = load_config()
    if not config.get("automatic_daily_backup", True) or not DB_PATH.exists():
        return
    today = datetime.now().strftime("%Y%m%d")
    if any(BACKUP_DIR.glob(f"one_crm_auto_{today}_*.db")):
        return
    try:
        path = create_backup("auto")
        keep = max(1, int(config.get("automatic_backup_retention", 14)))
        automatic = sorted(BACKUP_DIR.glob("one_crm_auto_*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old_backup in automatic[keep:]:
            old_backup.unlink(missing_ok=True)
        log(f"Backup automático criado: {path.name}")
    except Exception as exc:
        log(f"Falha no backup automático: {exc}")


def find_free_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 11):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"Nenhuma porta livre entre {preferred} e {preferred + 10}.")


def main() -> None:
    print("=" * 66)
    print(f" {APP_NAME} {APP_VERSION}")
    print(" CRM operacional sem dependências externas")
    print("=" * 66)
    print(f"Python: {sys.version.split()[0]}")
    print(f"Pasta:  {BASE_DIR}")
    print(f"Banco:  {DB_PATH}")
    print()
    if sys.version_info < (3, 10):
        print("ERRO: é necessário Python 3.10 ou superior.")
        input("Pressione ENTER para fechar...")
        raise SystemExit(1)
    init_database()
    maybe_daily_backup()
    config = load_config()
    railway_port = (os.getenv("PORT") or "").strip()
    if railway_port:
        # Railway exige a porta injetada e o bind em todas as interfaces.
        host = "0.0.0.0"
        port = int(railway_port)
        preferred = port
    else:
        host = os.getenv("ONE_CRM_HOST", os.getenv("ANNIE_HOST", str(config.get("host", "127.0.0.1"))))
        preferred = int(os.getenv("ONE_CRM_PORT", os.getenv("ANNIE_PORT", str(config.get("port", 8000)))))
        port = find_free_port(host, preferred)

    server = OneCRMHTTPServer((host, port), OneCRMHandler)
    try:
        PID_PATH.parent.mkdir(parents=True, exist_ok=True)
        PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    except Exception:
        pass

    display_host = "127.0.0.1" if host == "0.0.0.0" and not IS_RAILWAY else host
    url = f"http://{display_host}:{port}"
    print(f"ONE CRM iniciado em: {url}")
    print(f"Modo: {'Railway / online' if IS_RAILWAY else 'local'}")
    print(f"Armazenamento persistente: {'sim' if RAILWAY_VOLUME_PATH or os.getenv('ONE_CRM_DATA_DIR') else 'não'}")
    if IS_RAILWAY and not RAILWAY_VOLUME_PATH and not os.getenv("ONE_CRM_DATA_DIR"):
        print("AVISO: nenhum Volume foi detectado; os dados podem ser perdidos em um novo deploy.")
    if port != preferred:
        print(f"Aviso: a porta {preferred} estava ocupada; usando {port}.")
    print("Para encerrar localmente, pressione CTRL+C nesta janela.")
    print(f"Logs: {LOG_DIR / 'one_crm.log'}")
    print("-" * 66, flush=True)

    stopping = threading.Event()

    def request_shutdown(signum: int, _frame: Any) -> None:
        if stopping.is_set():
            return
        stopping.set()
        log(f"Sinal {signum} recebido; encerrando servidor.")
        threading.Thread(target=server.shutdown, daemon=True).start()

    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_shutdown)
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, request_shutdown)

    no_browser = os.getenv("ONE_CRM_NO_BROWSER", os.getenv("ANNIE_NO_BROWSER")) == "1"
    if config.get("open_browser", True) and not IS_RAILWAY and not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\nEncerrando ONE CRM...")
    finally:
        server.server_close()
        try:
            PID_PATH.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
