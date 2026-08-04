from __future__ import annotations

"""Camada multi-perfil do ONE CRM.

Esta extensão mantém a aplicação monolítica atual compatível, mas adiciona:
- perfis de negócio isolados;
- Dono da plataforma com visão global;
- Contratante limitado ao próprio perfil;
- módulos por perfil;
- separação de vendas, equipes, planos, catálogos, cargos e integrações;
- módulo inicial de controle de caixa.

O arquivo é instalado em tempo de importação por ``install_profiles(globals())``.
"""

import json
import re
import secrets
import sqlite3
import threading
from datetime import date
from typing import Any, Callable


PROFILE_TEMPLATES: dict[str, dict[str, Any]] = {
    "internet_sales": {
        "name": "Venda de internet",
        "description": "Operação comercial de internet, BKO, biometria e instalação.",
        "modules": [
            "dashboard", "sales", "bko", "daily", "ranking", "intelligence",
            "powerbi", "users", "teams", "plans", "catalogs", "roles",
            "audit", "integrations",
        ],
    },
    "cash_control": {
        "name": "Controle de caixa",
        "description": "Entradas, saídas, saldo, categorias e fechamento financeiro.",
        "modules": [
            "dashboard", "cash", "intelligence", "users", "roles", "audit",
            "integrations",
        ],
    },
    "services": {
        "name": "Prestação de serviços",
        "description": "CRM genérico para clientes, tarefas, equipes e acompanhamento.",
        "modules": [
            "dashboard", "sales", "daily", "intelligence", "users", "teams",
            "catalogs", "roles", "audit", "integrations",
        ],
    },
}

# O Contratante funciona como administrador de visualização do perfil.
# Ele enxerga todos os dados permitidos no próprio ambiente, mas não cria,
# edita, exclui, trata ou configura registros.
PROFILE_CONTRACTOR_PERMISSIONS = {
    "profile.view",
    "dashboard.view",
    "sales.all",
    "ranking.all", "daily.view",
    "users.view", "teams.view",
    "plans.view", "catalogs.view", "roles.view", "audit.view",
    "intelligence.view", "ai.use", "powerbi.view", "integrations.view",
    "cash.view",
}

PROFILE_ADMIN_PERMISSIONS = {
    "users.manage", "teams.manage", "plans.manage", "catalogs.manage",
    "roles.manage", "integrations.manage",
}

REQUEST_CONTEXT = threading.local()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _parse_json(value: str | None, default: Any) -> Any:
    try:
        parsed = json.loads(value or "")
        return parsed
    except Exception:
        return default


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return normalized[:64] or f"perfil-{secrets.token_hex(3)}"


def install_profiles(ns: dict[str, Any]) -> None:
    db_connect = ns["db_connect"]
    utc_now = ns["utc_now"]
    local_today = ns["local_today"]
    ApiError = ns["ApiError"]
    Handler = ns["OneCRMHandler"]
    original_init_database = ns["init_database"]
    original_get_role_permissions = ns["get_role_permissions"]
    original_read_json = Handler.read_json
    original_route_get = Handler.route_get
    original_route_write = Handler.route_write
    original_dashboard = Handler.api_dashboard
    original_intelligence = Handler.api_intelligence
    original_sale_list = Handler.api_sales_list
    original_sale_detail = Handler.api_sale_detail
    original_sale_update = Handler.api_sale_update
    original_sale_workflow = Handler.api_sale_workflow
    original_api_user_update = Handler.api_user_update
    original_export_sales = Handler.api_export_sales
    original_trigger_webhook = Handler.trigger_webhook

    # Permissões novas são acrescentadas antes de init_database() chamar seed_database().
    extra_permissions = [
        ("profile.view", "Perfil", "Visualizar a identidade e os módulos do perfil atual"),
        ("plans.view", "Cadastros", "Visualizar planos e serviços"),
        ("catalogs.view", "Cadastros", "Visualizar opções e status"),
        ("roles.view", "Segurança", "Visualizar cargos e permissões"),
        ("integrations.view", "Sistema", "Visualizar o estado das integrações"),
        ("cash.view", "Caixa", "Visualizar lançamentos e saldo do caixa"),
        ("cash.manage", "Caixa", "Criar e editar lançamentos do caixa"),
    ]
    existing_permission_codes = {item[0] for item in ns["PERMISSIONS"]}
    ns["PERMISSIONS"].extend(item for item in extra_permissions if item[0] not in existing_permission_codes)

    def add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def ensure_profile_schema() -> None:
        now = utc_now()
        with db_connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS business_profiles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    business_type TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    contractor_user_id INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    modules_json TEXT NOT NULL DEFAULT '[]',
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(contractor_user_id) REFERENCES users(id) ON DELETE SET NULL,
                    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS profile_users (
                    profile_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role_code TEXT NOT NULL,
                    team_id INTEGER,
                    is_contractor INTEGER NOT NULL DEFAULT 0,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(profile_id,user_id),
                    FOREIGN KEY(profile_id) REFERENCES business_profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(role_code) REFERENCES roles(code) ON DELETE RESTRICT,
                    FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS profile_settings (
                    profile_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    secret INTEGER NOT NULL DEFAULT 0,
                    updated_by INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(profile_id,key),
                    FOREIGN KEY(profile_id) REFERENCES business_profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS cash_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id INTEGER NOT NULL,
                    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('entry','exit')),
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL CHECK(amount >= 0),
                    transaction_date TEXT NOT NULL,
                    payment_method TEXT,
                    notes TEXT,
                    created_by INTEGER,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES business_profiles(id) ON DELETE CASCADE,
                    FOREIGN KEY(created_by) REFERENCES users(id) ON DELETE SET NULL
                );
                CREATE INDEX IF NOT EXISTS idx_profile_users_user ON profile_users(user_id,active);
                CREATE INDEX IF NOT EXISTS idx_cash_profile_date ON cash_transactions(profile_id,transaction_date);
                """
            )

            add_column(conn, "sessions", "active_profile_id", "INTEGER")
            add_column(conn, "teams", "profile_id", "INTEGER")
            add_column(conn, "roles", "profile_id", "INTEGER")
            add_column(conn, "catalog_items", "profile_id", "INTEGER")
            add_column(conn, "plans", "profile_id", "INTEGER")
            add_column(conn, "sales", "profile_id", "INTEGER")
            add_column(conn, "audit_logs", "profile_id", "INTEGER")
            add_column(conn, "ai_usage_logs", "profile_id", "INTEGER")

            profile = conn.execute("SELECT id FROM business_profiles ORDER BY id LIMIT 1").fetchone()
            if profile:
                default_profile_id = int(profile[0])
            else:
                template = PROFILE_TEMPLATES["internet_sales"]
                cur = conn.execute(
                    """INSERT INTO business_profiles
                       (name,slug,business_type,description,active,modules_json,settings_json,created_at,updated_at)
                       VALUES(?,?,?,?,1,?,'{}',?,?)""",
                    (
                        "Operação principal",
                        "operacao-principal",
                        "internet_sales",
                        template["description"],
                        _json(template["modules"]),
                        now,
                        now,
                    ),
                )
                default_profile_id = int(cur.lastrowid)

            for table in ("teams", "catalog_items", "plans", "sales", "audit_logs", "ai_usage_logs"):
                conn.execute(f"UPDATE {table} SET profile_id=? WHERE profile_id IS NULL OR profile_id=0", (default_profile_id,))
            conn.execute("UPDATE roles SET profile_id=? WHERE is_system=0 AND profile_id IS NULL", (default_profile_id,))

            # Migra os usuários atuais para o perfil inicial. O Dono continua sendo global.
            users = conn.execute(
                "SELECT id,role_code,custom_role_code,team_id,active,created_at,updated_at FROM users"
            ).fetchall()
            for row in users:
                effective = row["custom_role_code"] or row["role_code"]
                conn.execute(
                    """INSERT OR IGNORE INTO profile_users
                       (profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                       VALUES(?,?,?,?,0,?,?,?)""",
                    (
                        default_profile_id,
                        row["id"],
                        effective,
                        row["team_id"],
                        row["active"],
                        row["created_at"] or now,
                        row["updated_at"] or now,
                    ),
                )

            conn.execute(
                "UPDATE sessions SET active_profile_id=? WHERE active_profile_id IS NULL",
                (default_profile_id,),
            )

            # Configurações antigas passam a pertencer ao perfil inicial.
            settings = conn.execute("SELECT key,value,secret,updated_by,updated_at FROM system_settings").fetchall()
            for row in settings:
                conn.execute(
                    """INSERT OR IGNORE INTO profile_settings(profile_id,key,value,secret,updated_by,updated_at)
                       VALUES(?,?,?,?,?,?)""",
                    (default_profile_id, row["key"], row["value"], row["secret"], row["updated_by"], row["updated_at"]),
                )

            conn.execute("CREATE INDEX IF NOT EXISTS idx_sales_profile ON sales(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_teams_profile ON teams(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_plans_profile ON plans(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_catalog_profile ON catalog_items(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_roles_profile ON roles(profile_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_profile ON audit_logs(profile_id)")

            # Permissão legada removida: desde a 2.0.1 somente o Dono da
            # Plataforma pode alterar a identidade e os módulos de um perfil.
            conn.execute("DELETE FROM role_permissions WHERE permission_code='profile.configure'")
            conn.execute("DELETE FROM permissions WHERE code='profile.configure'")

    def init_database() -> None:
        original_init_database()
        ensure_profile_schema()

    ns["init_database"] = init_database

    def is_platform_owner(user: dict[str, Any] | None) -> bool:
        return bool(user and (user.get("platform_role_code") == "owner" or user.get("role_code") == "owner"))

    def current_profile_id(user: dict[str, Any] | None) -> int:
        try:
            return int((user or {}).get("profile_id") or 0)
        except Exception:
            return 0

    def get_profile(profile_id: int) -> dict[str, Any] | None:
        if not profile_id:
            return None
        with db_connect() as conn:
            row = conn.execute(
                "SELECT * FROM business_profiles WHERE id=?",
                (profile_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["modules"] = _parse_json(result.pop("modules_json", "[]"), [])
        result["settings"] = _parse_json(result.pop("settings_json", "{}"), {})
        return result

    def accessible_profiles(user_id: int, owner: bool = False) -> list[dict[str, Any]]:
        with db_connect() as conn:
            if owner:
                rows = conn.execute(
                    """SELECT p.*,u.name AS contractor_name,
                       (SELECT COUNT(*) FROM profile_users pu WHERE pu.profile_id=p.id AND pu.active=1) AS users_count
                       FROM business_profiles p
                       LEFT JOIN users u ON u.id=p.contractor_user_id
                       ORDER BY p.active DESC,p.name"""
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT p.*,u.name AS contractor_name,
                       (SELECT COUNT(*) FROM profile_users x WHERE x.profile_id=p.id AND x.active=1) AS users_count
                       FROM profile_users pu
                       JOIN business_profiles p ON p.id=pu.profile_id
                       LEFT JOIN users u ON u.id=p.contractor_user_id
                       WHERE pu.user_id=? AND pu.active=1 AND p.active=1
                       ORDER BY p.name""",
                    (user_id,),
                ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["modules"] = _parse_json(item.pop("modules_json", "[]"), [])
            item["settings"] = _parse_json(item.pop("settings_json", "{}"), {})
            item["active"] = bool(item["active"])
            result.append(item)
        return result

    def choose_profile_for_user(conn: sqlite3.Connection, user_id: int, owner: bool, requested: int | None = None) -> int | None:
        if requested:
            if owner:
                row = conn.execute("SELECT id FROM business_profiles WHERE id=? AND active=1", (requested,)).fetchone()
            else:
                row = conn.execute(
                    """SELECT p.id FROM business_profiles p JOIN profile_users pu ON pu.profile_id=p.id
                       WHERE p.id=? AND p.active=1 AND pu.user_id=? AND pu.active=1""",
                    (requested, user_id),
                ).fetchone()
            if row:
                return int(row[0])
        if owner:
            row = conn.execute("SELECT id FROM business_profiles WHERE active=1 ORDER BY id LIMIT 1").fetchone()
        else:
            row = conn.execute(
                """SELECT p.id FROM business_profiles p JOIN profile_users pu ON pu.profile_id=p.id
                   WHERE pu.user_id=? AND pu.active=1 AND p.active=1 ORDER BY p.id LIMIT 1""",
                (user_id,),
            ).fetchone()
        return int(row[0]) if row else None

    def create_session(user_id: int, hours: int) -> tuple[str, str]:
        raw = secrets.token_urlsafe(40)
        csrf = secrets.token_urlsafe(28)
        expires = (ns["datetime"].now() + ns["timedelta"](hours=hours)).replace(microsecond=0).isoformat()
        with db_connect() as conn:
            row = conn.execute("SELECT role_code FROM users WHERE id=?", (user_id,)).fetchone()
            owner = bool(row and row["role_code"] == "owner")
            profile_id = choose_profile_for_user(conn, user_id, owner)
            if not profile_id:
                raise ApiError(403, "Este usuário não está vinculado a nenhum perfil ativo.")
            conn.execute("DELETE FROM sessions WHERE expires_at < ?", (utc_now(),))
            conn.execute(
                """INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at,created_at,active_profile_id)
                   VALUES(?,?,?,?,?,?)""",
                (ns["token_hash"](raw), user_id, csrf, expires, utc_now(), profile_id),
            )
        return raw, csrf

    ns["create_session"] = create_session

    def get_user_by_session(raw_token: str | None) -> tuple[dict[str, Any] | None, str | None]:
        if not raw_token:
            return None, None
        with db_connect() as conn:
            session = conn.execute(
                """SELECT s.*,u.* FROM sessions s JOIN users u ON u.id=s.user_id
                   WHERE s.token_hash=? AND s.expires_at>? AND u.active=1""",
                (ns["token_hash"](raw_token), utc_now()),
            ).fetchone()
            if not session:
                return None, None
            data = dict(session)
            owner = data["role_code"] == "owner"
            profile_id = choose_profile_for_user(conn, data["user_id"], owner, data.get("active_profile_id"))
            if not profile_id:
                return None, None
            if profile_id != data.get("active_profile_id"):
                conn.execute(
                    "UPDATE sessions SET active_profile_id=? WHERE token_hash=?",
                    (profile_id, ns["token_hash"](raw_token)),
                )
            profile = conn.execute("SELECT * FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
            membership = conn.execute(
                """SELECT pu.*,r.name AS membership_role_name,r.base_role AS membership_base_role,t.name AS membership_team_name
                   FROM profile_users pu
                   LEFT JOIN roles r ON r.code=pu.role_code
                   LEFT JOIN teams t ON t.id=pu.team_id AND t.profile_id=pu.profile_id
                   WHERE pu.profile_id=? AND pu.user_id=? AND pu.active=1""",
                (profile_id, data["user_id"]),
            ).fetchone()
            if not owner and not membership:
                return None, None

        user = {key: data[key] for key in data.keys() if key not in {"token_hash", "csrf_token", "expires_at", "created_at", "active_profile_id", "user_id"}}
        user["id"] = data["user_id"]
        user["platform_role_code"] = data["role_code"]
        if owner:
            user["role_code"] = "owner"
            user["effective_role_code"] = "owner"
            user["role_name"] = "Dono"
            user["team_id"] = membership["team_id"] if membership else None
            user["team_name"] = membership["membership_team_name"] if membership else None
            user["is_contractor"] = False
            user["permissions"] = sorted(code for code, _, _ in ns["PERMISSIONS"])
        else:
            member = dict(membership)
            effective = member["role_code"]
            base = member.get("membership_base_role") or "seller"
            user["role_code"] = base
            user["effective_role_code"] = effective
            user["role_name"] = member.get("membership_role_name") or effective
            user["team_id"] = member.get("team_id")
            user["team_name"] = member.get("membership_team_name")
            user["is_contractor"] = bool(member.get("is_contractor"))
            if user["is_contractor"]:
                # O vínculo continua baseado em manager para compatibilidade,
                # mas as permissões efetivas são exclusivamente de leitura.
                permissions = set(PROFILE_CONTRACTOR_PERMISSIONS)
                user["role_name"] = "Contratante"
            else:
                permissions = set(original_get_role_permissions(effective))
            user["permissions"] = sorted(permissions)
        profile_dict = dict(profile)
        user["profile_id"] = profile_id
        user["profile_name"] = profile_dict["name"]
        user["profile_type"] = profile_dict["business_type"]
        user["profile_modules"] = _parse_json(profile_dict["modules_json"], [])
        user["profile_settings"] = _parse_json(profile_dict["settings_json"], {})
        user["profile_active"] = bool(profile_dict["active"])
        return user, data["csrf_token"]

    ns["get_user_by_session"] = get_user_by_session

    def effective_role_code(user: dict[str, Any] | sqlite3.Row | None) -> str:
        if not user:
            return "seller"
        if isinstance(user, dict):
            return str(user.get("effective_role_code") or user.get("membership_role_code") or user.get("custom_role_code") or user.get("role_code") or "seller")
        keys = user.keys()
        for key in ("effective_role_code", "membership_role_code", "custom_role_code", "role_code"):
            if key in keys and user[key]:
                return str(user[key])
        return "seller"

    ns["effective_role_code"] = effective_role_code

    permission_modules = {
        "dashboard.view": "dashboard",
        "sales.own": "sales", "sales.all": "sales", "sales.create": "sales",
        "sales.edit_own": "sales", "sales.edit_all": "sales",
        "workflow.bko": "bko", "workflow.assign": "bko",
        "ranking.own": "ranking", "ranking.all": "ranking",
        "daily.view": "daily", "users.view": "users", "users.manage": "users",
        "teams.view": "teams", "teams.manage": "teams",
        "plans.view": "plans", "plans.manage": "plans",
        "catalogs.view": "catalogs", "catalogs.manage": "catalogs",
        "roles.view": "roles", "roles.manage": "roles", "audit.view": "audit",
        "intelligence.view": "intelligence", "ai.use": "intelligence",
        "powerbi.view": "powerbi",
        "integrations.view": "integrations", "integrations.manage": "integrations",
        "profile.view": "users",
        "cash.view": "cash", "cash.manage": "cash",
    }

    def has_permission(user: dict[str, Any] | None, code: str) -> bool:
        if not user:
            return False
        if is_platform_owner(user):
            return True
        required_module = permission_modules.get(code)
        if required_module and required_module not in set(user.get("profile_modules") or []):
            return False
        if user.get("is_contractor") and code in PROFILE_CONTRACTOR_PERMISSIONS:
            return True
        return code in set(user.get("permissions", []))

    ns["has_permission"] = has_permission

    def sale_scope_sql(user: dict[str, Any], alias: str = "s") -> tuple[str, list[Any]]:
        pid = current_profile_id(user)
        if not pid:
            return "0=1", []
        prefix = f"{alias}.profile_id=?"
        if has_permission(user, "sales.all"):
            return prefix, [pid]
        if user.get("role_code") == "bko":
            return (
                f"{prefix} AND ({alias}.bko_user_id=? OR ({alias}.bko_user_id IS NULL AND {alias}.status IN ('nova','em_tratamento')))",
                [pid, user["id"]],
            )
        return f"{prefix} AND {alias}.seller_id=?", [pid, user["id"]]

    ns["sale_scope_sql"] = sale_scope_sql

    def can_access_sale(user: dict[str, Any], sale: dict[str, Any]) -> bool:
        if int(sale.get("profile_id") or 0) != current_profile_id(user):
            return False
        if has_permission(user, "sales.all"):
            return True
        if user.get("role_code") == "bko":
            return sale.get("bko_user_id") in (None, user["id"])
        return sale.get("seller_id") == user["id"]

    ns["can_access_sale"] = can_access_sale

    original_audit = ns["audit"]

    def audit(user_id: int | None, action: str, entity_type: str | None = None,
              entity_id: str | int | None = None, details: Any = None, ip: str | None = None) -> None:
        profile_id = getattr(REQUEST_CONTEXT, "profile_id", None)
        detail_text = details if isinstance(details, str) else ns["json_dumps"](details or {})
        with db_connect() as conn:
            conn.execute(
                """INSERT INTO audit_logs(profile_id,user_id,action,entity_type,entity_id,details,ip_address,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (profile_id, user_id, action, entity_type, str(entity_id) if entity_id is not None else None, detail_text, ip, utc_now()),
            )

    ns["audit"] = audit

    def read_json_cached(self: Any) -> dict[str, Any]:
        if hasattr(self, "_onecrm_json_cache"):
            return self._onecrm_json_cache
        value = original_read_json(self)
        self._onecrm_json_cache = value
        return value

    Handler.read_json = read_json_cached

    original_require_user = Handler.require_user

    def require_user(self: Any) -> tuple[dict[str, Any], str, str]:
        user, csrf, raw = original_require_user(self)
        REQUEST_CONTEXT.profile_id = current_profile_id(user)
        return user, csrf, raw

    Handler.require_user = require_user

    def public_user(self: Any, user: dict[str, Any]) -> dict[str, Any]:
        owner = is_platform_owner(user)
        profiles = accessible_profiles(user["id"], owner)
        profile = {
            "id": user.get("profile_id"),
            "name": user.get("profile_name"),
            "business_type": user.get("profile_type"),
            "modules": user.get("profile_modules", []),
            "settings": user.get("profile_settings", {}),
            "active": bool(user.get("profile_active", True)),
        }
        return {
            "id": user["id"],
            "name": user["name"],
            "display_name": user.get("display_name") or user["name"],
            "email": user["email"],
            "phone": user.get("phone") or "",
            "bio": user.get("bio") or "",
            "theme_preference": user.get("theme_preference") or "dark",
            "role_code": user.get("effective_role_code") or user.get("role_code"),
            "base_role": user.get("role_code"),
            "role_name": "Dono da Plataforma" if owner else (user.get("role_name") or "Usuário"),
            "team_id": user.get("team_id"),
            "team_name": user.get("team_name"),
            "permissions": user.get("permissions", []),
            "must_change_password": bool(user.get("must_change_password")),
            "is_platform_owner": owner,
            "is_contractor": bool(user.get("is_contractor")),
            "profile": profile,
            "profiles": profiles,
        }

    Handler.public_user = public_user

    # ------------------------- perfis -------------------------
    def normalize_modules(business_type: str, modules: Any) -> list[str]:
        allowed = {
            "dashboard", "sales", "bko", "daily", "ranking", "intelligence",
            "powerbi", "users", "teams", "plans", "catalogs", "roles",
            "audit", "integrations", "cash",
        }
        if not isinstance(modules, list):
            modules = PROFILE_TEMPLATES.get(business_type, PROFILE_TEMPLATES["services"])["modules"]
        result = [str(item) for item in modules if str(item) in allowed]
        if "dashboard" not in result:
            result.insert(0, "dashboard")
        for essential in ("users", "roles"):
            if essential not in result:
                result.append(essential)
        return list(dict.fromkeys(result))

    def seed_profile(conn: sqlite3.Connection, profile_id: int, business_type: str) -> None:
        now = utc_now()
        if business_type == "internet_sales":
            source_profile = conn.execute(
                "SELECT id FROM business_profiles WHERE id<>? AND business_type='internet_sales' ORDER BY id LIMIT 1",
                (profile_id,),
            ).fetchone()
            if source_profile:
                source_id = int(source_profile[0])
                plan_count = conn.execute("SELECT COUNT(*) FROM plans WHERE profile_id=?", (profile_id,)).fetchone()[0]
                if not plan_count:
                    conn.execute(
                        """INSERT INTO plans(profile_id,provider,service,name,speed,price,benefits,uf_list,sort_order,active,created_at,updated_at)
                           SELECT ?,provider,service,name,speed,price,benefits,uf_list,sort_order,active,?,? FROM plans WHERE profile_id=?""",
                        (profile_id, now, now, source_id),
                    )
                cat_count = conn.execute("SELECT COUNT(*) FROM catalog_items WHERE profile_id=?", (profile_id,)).fetchone()[0]
                if not cat_count:
                    rows = conn.execute(
                        "SELECT category,code,label,sort_order,active,metadata_json FROM catalog_items WHERE profile_id=?",
                        (source_id,),
                    ).fetchall()
                    for row in rows:
                        code = f"p{profile_id}_{row['code']}"
                        conn.execute(
                            """INSERT OR IGNORE INTO catalog_items
                               (profile_id,category,code,label,sort_order,active,metadata_json,created_at,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (profile_id, row["category"], code, row["label"], row["sort_order"], row["active"], row["metadata_json"], now, now),
                        )

    def api_profiles(self: Any) -> None:
        user, _, _ = self.require_user()
        owner = is_platform_owner(user)
        profiles = accessible_profiles(user["id"], owner)
        if not owner:
            profiles = [item for item in profiles if item["id"] == current_profile_id(user)]
        candidates = []
        if owner:
            with db_connect() as conn:
                candidates = [dict(row) for row in conn.execute(
                    "SELECT id,name,email FROM users WHERE active=1 AND role_code<>'owner' ORDER BY name"
                ).fetchall()]
        self.send_json(200, {
            "ok": True,
            "profiles": profiles,
            "templates": [
                {"code": code, **template}
                for code, template in PROFILE_TEMPLATES.items()
            ],
            "available_contractors": candidates,
        })

    def api_profile_create(self: Any, actor: dict[str, Any]) -> None:
        if not is_platform_owner(actor):
            raise ApiError(403, "Somente o Dono da plataforma pode criar perfis.")
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        business_type = str(data.get("business_type") or "internet_sales").strip()
        description = str(data.get("description") or "").strip()[:600]
        contractor_user_id = int(data.get("contractor_user_id") or 0) or None
        if len(name) < 3:
            raise ApiError(400, "Informe um nome de perfil com pelo menos 3 caracteres.")
        if business_type not in PROFILE_TEMPLATES:
            raise ApiError(400, "Modelo de negócio inválido.")
        modules = normalize_modules(business_type, data.get("modules"))
        slug = _slug(data.get("slug") or name)
        now = utc_now()
        with db_connect() as conn:
            base_slug = slug
            suffix = 2
            while conn.execute("SELECT 1 FROM business_profiles WHERE slug=?", (slug,)).fetchone():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            if contractor_user_id and not conn.execute("SELECT 1 FROM users WHERE id=? AND active=1", (contractor_user_id,)).fetchone():
                raise ApiError(400, "Contratante inválido ou inativo.")
            cur = conn.execute(
                """INSERT INTO business_profiles
                   (name,slug,business_type,description,contractor_user_id,active,modules_json,settings_json,created_by,created_at,updated_at)
                   VALUES(?,?,?,?,?,1,?,'{}',?,?,?)""",
                (name, slug, business_type, description or PROFILE_TEMPLATES[business_type]["description"], contractor_user_id,
                 _json(modules), actor["id"], now, now),
            )
            profile_id = int(cur.lastrowid)
            seed_profile(conn, profile_id, business_type)
            if contractor_user_id:
                conn.execute(
                    """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                       VALUES(?,?,'manager',NULL,1,1,?,?)
                       ON CONFLICT(profile_id,user_id) DO UPDATE SET role_code='manager',is_contractor=1,active=1,updated_at=excluded.updated_at""",
                    (profile_id, contractor_user_id, now, now),
                )
                conn.execute(
                    "UPDATE profile_users SET active=0,is_contractor=0,updated_at=? WHERE user_id=? AND profile_id<>?",
                    (now, contractor_user_id, profile_id),
                )
        audit(actor["id"], "profile.create", "profile", profile_id, {"name": name, "business_type": business_type}, self.client_ip())
        self.send_json(201, {"ok": True, "id": profile_id, "message": "Perfil criado."})

    def api_profile_update_business(self: Any, actor: dict[str, Any], profile_id: int) -> None:
        owner = is_platform_owner(actor)
        if not owner:
            raise ApiError(403, "Apenas o Dono da Plataforma pode configurar perfis.")
        data = self.read_json()
        with db_connect() as conn:
            current = conn.execute("SELECT * FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
            if not current:
                raise ApiError(404, "Perfil não encontrado.")
            updates: dict[str, Any] = {}
            if "name" in data:
                name = str(data.get("name") or "").strip()
                if len(name) < 3:
                    raise ApiError(400, "Nome do perfil inválido.")
                updates["name"] = name
            if "description" in data:
                updates["description"] = str(data.get("description") or "").strip()[:600]
            business_type = current["business_type"]
            if owner and "business_type" in data:
                business_type = str(data.get("business_type") or "").strip()
                if business_type not in PROFILE_TEMPLATES:
                    raise ApiError(400, "Modelo de negócio inválido.")
                updates["business_type"] = business_type
            if "modules" in data:
                updates["modules_json"] = _json(normalize_modules(business_type, data.get("modules")))
            if "settings" in data:
                settings = data.get("settings") if isinstance(data.get("settings"), dict) else {}
                updates["settings_json"] = _json(settings)
            if owner and "active" in data:
                updates["active"] = 1 if bool(data.get("active")) else 0
            contractor_id = None
            if owner and "contractor_user_id" in data:
                contractor_id = int(data.get("contractor_user_id") or 0) or None
                if contractor_id and not conn.execute("SELECT 1 FROM users WHERE id=? AND active=1", (contractor_id,)).fetchone():
                    raise ApiError(400, "Contratante inválido.")
                updates["contractor_user_id"] = contractor_id
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            updates["updated_at"] = utc_now()
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE business_profiles SET {assignments} WHERE id=?", [*updates.values(), profile_id])
            if owner and "contractor_user_id" in data:
                conn.execute("UPDATE profile_users SET is_contractor=0,updated_at=? WHERE profile_id=?", (utc_now(), profile_id))
                if contractor_id:
                    conn.execute(
                        """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                           VALUES(?,?,'manager',NULL,1,1,?,?)
                           ON CONFLICT(profile_id,user_id) DO UPDATE SET role_code='manager',is_contractor=1,active=1,updated_at=excluded.updated_at""",
                        (profile_id, contractor_id, utc_now(), utc_now()),
                    )
                    conn.execute(
                        "UPDATE profile_users SET active=0,is_contractor=0,updated_at=? WHERE user_id=? AND profile_id<>?",
                        (utc_now(), contractor_id, profile_id),
                    )
        audit(actor["id"], "profile.update", "profile", profile_id, {"fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Perfil atualizado."})

    def api_profile_switch(self: Any, actor: dict[str, Any]) -> None:
        data = self.read_json()
        profile_id = int(data.get("profile_id") or 0)
        if not profile_id:
            raise ApiError(400, "Perfil inválido.")
        raw = self.parse_cookie(ns["COOKIE_NAME"])
        if not raw:
            raise ApiError(401, "Sessão expirada.")
        with db_connect() as conn:
            selected = choose_profile_for_user(conn, actor["id"], is_platform_owner(actor), profile_id)
            if selected != profile_id:
                raise ApiError(403, "Você não possui acesso a este perfil.")
            conn.execute(
                "UPDATE sessions SET active_profile_id=? WHERE token_hash=?",
                (profile_id, ns["token_hash"](raw)),
            )
        audit(actor["id"], "profile.switch", "profile", profile_id, {}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Perfil alterado."})

    # ------------------------- usuários do perfil -------------------------
    def role_allowed_in_profile(conn: sqlite3.Connection, profile_id: int, role_code: str) -> sqlite3.Row | None:
        return conn.execute(
            """SELECT * FROM roles WHERE code=? AND active=1 AND (is_system=1 OR profile_id=?)""",
            (role_code, profile_id),
        ).fetchone()

    def api_users_list(self: Any) -> None:
        actor = self.require_permission("users.view")
        pid = current_profile_id(actor)
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT u.id,u.name,u.email,pu.role_code,r.base_role,r.name AS role_name,
                   pu.team_id,pu.is_contractor,pu.active,u.must_change_password,u.last_login_at,u.created_at,
                   t.name AS team_name
                   FROM profile_users pu JOIN users u ON u.id=pu.user_id
                   LEFT JOIN roles r ON r.code=pu.role_code
                   LEFT JOIN teams t ON t.id=pu.team_id AND t.profile_id=pu.profile_id
                   WHERE pu.profile_id=?
                   ORDER BY pu.active DESC,pu.is_contractor DESC,u.name""",
                (pid,),
            ).fetchall()
        users = [dict(row) for row in rows]
        if is_platform_owner(actor):
            included = {item["id"] for item in users}
            with db_connect() as conn:
                owners = conn.execute(
                    "SELECT id,name,email,'owner' AS role_code,'owner' AS base_role,'Dono da Plataforma' AS role_name,NULL AS team_id,0 AS is_contractor,active,must_change_password,last_login_at,created_at,NULL AS team_name FROM users WHERE role_code='owner' ORDER BY name"
                ).fetchall()
            users.extend(dict(row) for row in owners if row["id"] not in included)
        self.send_json(200, {"ok": True, "users": users})

    def api_user_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "users.manage"):
            raise ApiError(403, "Sem permissão para administrar usuários neste perfil.")
        pid = current_profile_id(actor)
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        email = ns["normalize_email"](data.get("email") or "")
        role_code = str(data.get("role_code") or "seller").strip()
        team_id = int(data.get("team_id") or 0) or None
        password = str(data.get("password") or "")
        make_contractor = bool(data.get("is_contractor")) and is_platform_owner(actor)
        if len(name) < 3 or "@" not in email:
            raise ApiError(400, "Nome ou e-mail inválido.")
        with db_connect() as conn:
            role = role_allowed_in_profile(conn, pid, role_code)
            if not role:
                raise ApiError(400, "Cargo inválido para este perfil.")
            if role["base_role"] == "owner" and not is_platform_owner(actor):
                raise ApiError(403, "Somente o Dono da plataforma pode nomear outro Dono.")
            if team_id and not conn.execute("SELECT 1 FROM teams WHERE id=? AND profile_id=? AND active=1", (team_id, pid)).fetchone():
                raise ApiError(400, "Equipe inválida.")
            existing = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            now = utc_now()
            if existing:
                user_id = int(existing["id"])
                if existing["role_code"] == "owner" and role["base_role"] != "owner":
                    raise ApiError(400, "A conta de Dono da plataforma não pode ser vinculada como funcionário comum.")
            else:
                error = ns["validate_password"](password)
                if error:
                    raise ApiError(400, error)
                cur = conn.execute(
                    """INSERT INTO users(name,email,password_hash,role_code,custom_role_code,team_id,active,must_change_password,created_at,updated_at)
                       VALUES(?,?,?,?,?,?,1,?,?,?)""",
                    (name, email, ns["hash_password"](password), role["base_role"], None if role["base_role"] == "owner" or role_code == role["base_role"] else role_code,
                     team_id, 1 if data.get("must_change_password", True) else 0, now, now),
                )
                user_id = int(cur.lastrowid)
            try:
                conn.execute(
                    """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                       VALUES(?,?,?,?,?,1,?,?)""",
                    (pid, user_id, role_code, team_id, 1 if make_contractor else 0, now, now),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Este usuário já pertence ao perfil atual.")
            if make_contractor:
                conn.execute("UPDATE profile_users SET is_contractor=0 WHERE profile_id=? AND user_id<>?", (pid, user_id))
                conn.execute("UPDATE profile_users SET active=0,is_contractor=0,updated_at=? WHERE user_id=? AND profile_id<>?", (now, user_id, pid))
                conn.execute("UPDATE business_profiles SET contractor_user_id=?,updated_at=? WHERE id=?", (user_id, now, pid))
        audit(actor["id"], "profile_user.create", "user", user_id, {"profile_id": pid, "role": role_code}, self.client_ip())
        self.send_json(201, {"ok": True, "id": user_id, "message": "Usuário vinculado ao perfil."})

    def api_user_update(self: Any, actor: dict[str, Any], user_id: int) -> None:
        if not has_permission(actor, "users.manage"):
            raise ApiError(403, "Sem permissão para administrar usuários neste perfil.")
        pid = current_profile_id(actor)
        data = self.read_json()
        if is_platform_owner(actor):
            with db_connect() as owner_conn:
                global_target = owner_conn.execute("SELECT role_code FROM users WHERE id=?", (user_id,)).fetchone()
            if global_target and global_target["role_code"] == "owner":
                return original_api_user_update(self, actor, user_id)
        with db_connect() as conn:
            target = conn.execute(
                """SELECT u.*,pu.role_code AS membership_role,pu.team_id AS membership_team,
                   pu.active AS membership_active,pu.is_contractor
                   FROM users u JOIN profile_users pu ON pu.user_id=u.id
                   WHERE u.id=? AND pu.profile_id=?""",
                (user_id, pid),
            ).fetchone()
            if not target:
                raise ApiError(404, "Usuário não encontrado neste perfil.")
            if target["role_code"] == "owner":
                raise ApiError(403, "A conta de Dono da plataforma não pode ser alterada por um perfil.")
            user_updates: dict[str, Any] = {}
            member_updates: dict[str, Any] = {}
            if "name" in data:
                name = str(data.get("name") or "").strip()
                if len(name) < 3:
                    raise ApiError(400, "Nome inválido.")
                user_updates["name"] = name
            if "email" in data:
                email = ns["normalize_email"](data.get("email") or "")
                if "@" not in email:
                    raise ApiError(400, "E-mail inválido.")
                user_updates["email"] = email
            if data.get("password"):
                error = ns["validate_password"](data["password"])
                if error:
                    raise ApiError(400, error)
                user_updates["password_hash"] = ns["hash_password"](data["password"])
                user_updates["must_change_password"] = 1 if data.get("must_change_password", True) else 0
            if "role_code" in data:
                role_code = str(data.get("role_code") or "").strip()
                role = role_allowed_in_profile(conn, pid, role_code)
                if not role or role["base_role"] == "owner":
                    raise ApiError(400, "Cargo inválido.")
                member_updates["role_code"] = role_code
                # Mantém um fallback global coerente para versões antigas e relatórios legados.
                user_updates["role_code"] = role["base_role"]
                user_updates["custom_role_code"] = None if role_code == role["base_role"] else role_code
            if "team_id" in data:
                team_id = int(data.get("team_id") or 0) or None
                if team_id and not conn.execute("SELECT 1 FROM teams WHERE id=? AND profile_id=? AND active=1", (team_id, pid)).fetchone():
                    raise ApiError(400, "Equipe inválida.")
                member_updates["team_id"] = team_id
            if "active" in data:
                member_updates["active"] = 1 if bool(data.get("active")) else 0
            if is_platform_owner(actor) and "is_contractor" in data:
                contractor = 1 if bool(data.get("is_contractor")) else 0
                member_updates["is_contractor"] = contractor
                if contractor:
                    conn.execute("UPDATE profile_users SET is_contractor=0 WHERE profile_id=? AND user_id<>?", (pid, user_id))
                    conn.execute("UPDATE profile_users SET active=0,is_contractor=0,updated_at=? WHERE user_id=? AND profile_id<>?", (utc_now(), user_id, pid))
                    conn.execute("UPDATE business_profiles SET contractor_user_id=?,updated_at=? WHERE id=?", (user_id, utc_now(), pid))
                elif target["is_contractor"]:
                    conn.execute("UPDATE business_profiles SET contractor_user_id=NULL,updated_at=? WHERE id=?", (utc_now(), pid))
            if not user_updates and not member_updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            now = utc_now()
            if user_updates:
                user_updates["updated_at"] = now
                assignments = ",".join(f"{key}=?" for key in user_updates)
                try:
                    conn.execute(f"UPDATE users SET {assignments} WHERE id=?", [*user_updates.values(), user_id])
                except sqlite3.IntegrityError:
                    raise ApiError(409, "Este e-mail já está em uso.")
            if member_updates:
                member_updates["updated_at"] = now
                assignments = ",".join(f"{key}=?" for key in member_updates)
                conn.execute(f"UPDATE profile_users SET {assignments} WHERE profile_id=? AND user_id=?", [*member_updates.values(), pid, user_id])
            conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        audit(actor["id"], "profile_user.update", "user", user_id, {"profile_id": pid, "fields": list(user_updates) + list(member_updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Usuário atualizado no perfil."})

    # ------------------------- equipes -------------------------
    def api_teams_list(self: Any) -> None:
        actor, _, _ = self.require_user()
        if not (has_permission(actor, "teams.view") or has_permission(actor, "teams.manage")):
            raise ApiError(403, "Sem permissão para visualizar equipes.")
        pid = current_profile_id(actor)
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT t.*,u.name AS manager_name,
                   (SELECT COUNT(*) FROM profile_users pu WHERE pu.profile_id=t.profile_id AND pu.team_id=t.id AND pu.active=1) AS members
                   FROM teams t LEFT JOIN users u ON u.id=t.manager_id
                   WHERE t.profile_id=? ORDER BY t.active DESC,t.name""",
                (pid,),
            ).fetchall()
        self.send_json(200, {"ok": True, "teams": [dict(row) for row in rows]})

    def api_team_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "teams.manage"):
            raise ApiError(403, "Sem permissão para administrar equipes.")
        pid = current_profile_id(actor)
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        manager_id = int(data.get("manager_id") or 0) or None
        target = max(0, int(data.get("monthly_target") or 0))
        if len(name) < 2:
            raise ApiError(400, "Nome da equipe inválido.")
        with db_connect() as conn:
            if manager_id:
                manager = conn.execute(
                    """SELECT r.base_role,pu.is_contractor FROM profile_users pu JOIN roles r ON r.code=pu.role_code
                       WHERE pu.profile_id=? AND pu.user_id=? AND pu.active=1""",
                    (pid, manager_id),
                ).fetchone()
                if not manager or (manager["base_role"] not in {"manager"} and not manager["is_contractor"]):
                    raise ApiError(400, "Gestor inválido para este perfil.")
            now = utc_now()
            try:
                cur = conn.execute(
                    """INSERT INTO teams(profile_id,name,manager_id,monthly_target,active,created_at,updated_at)
                       VALUES(?,?,?,?,1,?,?)""",
                    (pid, name, manager_id, target, now, now),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe uma equipe com este nome.")
        audit(actor["id"], "team.create", "team", cur.lastrowid, {"profile_id": pid, "name": name}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "message": "Equipe criada."})

    def api_team_update(self: Any, actor: dict[str, Any], team_id: int) -> None:
        if not has_permission(actor, "teams.manage"):
            raise ApiError(403, "Sem permissão para administrar equipes.")
        pid = current_profile_id(actor)
        data = self.read_json()
        with db_connect() as conn:
            current = conn.execute("SELECT * FROM teams WHERE id=? AND profile_id=?", (team_id, pid)).fetchone()
            if not current:
                raise ApiError(404, "Equipe não encontrada.")
            updates: dict[str, Any] = {}
            for field in ("name", "monthly_target", "active"):
                if field in data:
                    if field == "name":
                        value = str(data.get(field) or "").strip()
                        if len(value) < 2:
                            raise ApiError(400, "Nome inválido.")
                    elif field == "monthly_target":
                        value = max(0, int(data.get(field) or 0))
                    else:
                        value = 1 if bool(data.get(field)) else 0
                    updates[field] = value
            if "manager_id" in data:
                manager_id = int(data.get("manager_id") or 0) or None
                if manager_id and not conn.execute("SELECT 1 FROM profile_users WHERE profile_id=? AND user_id=? AND active=1", (pid, manager_id)).fetchone():
                    raise ApiError(400, "Gestor inválido.")
                updates["manager_id"] = manager_id
            if not updates:
                raise ApiError(400, "Nenhuma alteração enviada.")
            updates["updated_at"] = utc_now()
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE teams SET {assignments} WHERE id=? AND profile_id=?", [*updates.values(), team_id, pid])
        audit(actor["id"], "team.update", "team", team_id, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Equipe atualizada."})

    # ------------------------- planos e catálogos -------------------------
    def api_plans_list(self: Any, query: dict[str, list[str]]) -> None:
        actor, _, _ = self.require_user()
        pid = current_profile_id(actor)
        include_all = (query.get("all") or [""])[0] == "1" and (
            has_permission(actor, "plans.manage") or has_permission(actor, "plans.view")
        )
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT * FROM plans WHERE profile_id=? " + ("" if include_all else "AND active=1 ") + "ORDER BY sort_order,name",
                (pid,),
            ).fetchall()
        self.send_json(200, {"ok": True, "plans": [dict(row) for row in rows]})

    def api_plan_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "plans.manage"):
            raise ApiError(403, "Sem permissão para administrar planos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        if len(name) < 2:
            raise ApiError(400, "Nome do plano inválido.")
        now = utc_now()
        with db_connect() as conn:
            cur = conn.execute(
                """INSERT INTO plans(profile_id,provider,service,name,speed,price,benefits,uf_list,sort_order,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                (pid, str(data.get("provider") or "").strip(), str(data.get("service") or "").strip(), name,
                 str(data.get("speed") or "").strip(), float(data.get("price") or 0), str(data.get("benefits") or "").strip(),
                 str(data.get("uf_list") or "").strip(), int(data.get("sort_order") or 0), now, now),
            )
        audit(actor["id"], "plan.create", "plan", cur.lastrowid, {"profile_id": pid, "name": name}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "message": "Plano criado."})

    def api_plan_update(self: Any, actor: dict[str, Any], plan_id: int) -> None:
        if not has_permission(actor, "plans.manage"):
            raise ApiError(403, "Sem permissão para administrar planos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        allowed = {"provider", "service", "name", "speed", "price", "benefits", "uf_list", "sort_order", "active"}
        updates = {key: data[key] for key in allowed if key in data}
        if not updates:
            raise ApiError(400, "Nenhuma alteração enviada.")
        if "price" in updates:
            updates["price"] = float(updates["price"] or 0)
        if "sort_order" in updates:
            updates["sort_order"] = int(updates["sort_order"] or 0)
        if "active" in updates:
            updates["active"] = 1 if bool(updates["active"]) else 0
        updates["updated_at"] = utc_now()
        with db_connect() as conn:
            if not conn.execute("SELECT 1 FROM plans WHERE id=? AND profile_id=?", (plan_id, pid)).fetchone():
                raise ApiError(404, "Plano não encontrado.")
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE plans SET {assignments} WHERE id=? AND profile_id=?", [*updates.values(), plan_id, pid])
        audit(actor["id"], "plan.update", "plan", plan_id, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Plano atualizado."})

    def api_catalogs(self: Any, query: dict[str, list[str]]) -> None:
        actor, _, _ = self.require_user()
        pid = current_profile_id(actor)
        include_all = (query.get("all") or [""])[0] == "1" and (
            has_permission(actor, "catalogs.manage") or has_permission(actor, "catalogs.view")
        )
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT * FROM catalog_items WHERE profile_id=? " + ("" if include_all else "AND active=1 ") + "ORDER BY category,sort_order,label",
                (pid,),
            ).fetchall()
        catalogs: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            catalogs.setdefault(item["category"], []).append(item)
        self.send_json(200, {"ok": True, "catalogs": catalogs})

    def api_catalog_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "catalogs.manage"):
            raise ApiError(403, "Sem permissão para administrar catálogos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        category = str(data.get("category") or "").strip()
        label = str(data.get("label") or "").strip()
        raw_code = str(data.get("code") or label).strip().lower()
        code = re.sub(r"[^a-z0-9_]+", "_", raw_code).strip("_")
        if not category or len(label) < 1 or not code:
            raise ApiError(400, "Categoria, código e rótulo são obrigatórios.")
        # Evita colisões globais do esquema legado.
        stored_code = code
        with db_connect() as conn:
            if conn.execute("SELECT 1 FROM catalog_items WHERE category=? AND code=?", (category, stored_code)).fetchone():
                stored_code = f"p{pid}_{code}"
            now = utc_now()
            cur = conn.execute(
                """INSERT INTO catalog_items(profile_id,category,code,label,sort_order,active,metadata_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,1,'{}',?,?)""",
                (pid, category, stored_code, label, int(data.get("sort_order") or 0), now, now),
            )
        audit(actor["id"], "catalog.create", "catalog", cur.lastrowid, {"profile_id": pid, "category": category}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "code": stored_code, "message": "Opção criada."})

    def api_catalog_update(self: Any, actor: dict[str, Any], item_id: int) -> None:
        if not has_permission(actor, "catalogs.manage"):
            raise ApiError(403, "Sem permissão para administrar catálogos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        allowed = {"label", "sort_order", "active"}
        updates = {key: data[key] for key in allowed if key in data}
        if not updates:
            raise ApiError(400, "Nenhuma alteração enviada.")
        if "sort_order" in updates:
            updates["sort_order"] = int(updates["sort_order"] or 0)
        if "active" in updates:
            updates["active"] = 1 if bool(updates["active"]) else 0
        updates["updated_at"] = utc_now()
        with db_connect() as conn:
            if not conn.execute("SELECT 1 FROM catalog_items WHERE id=? AND profile_id=?", (item_id, pid)).fetchone():
                raise ApiError(404, "Opção não encontrada.")
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE catalog_items SET {assignments} WHERE id=? AND profile_id=?", [*updates.values(), item_id, pid])
        audit(actor["id"], "catalog.update", "catalog", item_id, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Opção atualizada."})

    # ------------------------- cargos do perfil -------------------------
    def api_roles(self: Any) -> None:
        actor, _, _ = self.require_user()
        if not (has_permission(actor, "roles.manage") or has_permission(actor, "roles.view")):
            raise ApiError(403, "Sem permissão para visualizar cargos.")
        pid = current_profile_id(actor)
        with db_connect() as conn:
            roles = conn.execute(
                """SELECT r.*,
                   (SELECT COUNT(*) FROM profile_users pu WHERE pu.profile_id=? AND pu.role_code=r.code) AS users_count,
                   (SELECT COUNT(*) FROM profile_users pu WHERE pu.profile_id=? AND pu.role_code=r.code AND pu.active=1) AS active_users_count
                   FROM roles r WHERE r.is_system=1 OR r.profile_id=? ORDER BY r.is_system DESC,r.name""",
                (pid, pid, pid),
            ).fetchall()
            permission_rows = conn.execute("SELECT role_code,permission_code,allowed FROM role_permissions WHERE allowed=1").fetchall()
            permissions = conn.execute("SELECT * FROM permissions ORDER BY module,description").fetchall()
        role_map: dict[str, list[str]] = {}
        for row in permission_rows:
            role_map.setdefault(row["role_code"], []).append(row["permission_code"])
        self.send_json(200, {"ok": True, "roles": [dict(row) for row in roles], "permissions": [dict(row) for row in permissions], "role_permissions": role_map})

    def api_role_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "roles.manage"):
            raise ApiError(403, "Sem permissão para administrar cargos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        name = str(data.get("name") or "").strip()
        base_role = str(data.get("base_role") or "seller").strip()
        if len(name) < 2 or base_role not in {"manager", "bko", "seller"}:
            raise ApiError(400, "Nome ou cargo-base inválido.")
        raw_code = re.sub(r"[^a-z0-9_]+", "_", str(data.get("code") or name).lower()).strip("_")
        code = raw_code[:80]
        valid = {item[0] for item in ns["PERMISSIONS"]}
        selected = sorted({str(item) for item in (data.get("permissions") or []) if str(item) in valid})
        now = utc_now()
        with db_connect() as conn:
            if conn.execute("SELECT 1 FROM roles WHERE code=?", (code,)).fetchone():
                code = f"p{pid}_{raw_code}"[:80]
            try:
                conn.execute(
                    """INSERT INTO roles(code,name,description,base_role,is_system,active,created_at,updated_at,profile_id)
                       VALUES(?,?,?,?,0,1,?,?,?)""",
                    (code, name, str(data.get("description") or "").strip(), base_role, now, now, pid),
                )
            except sqlite3.IntegrityError:
                raise ApiError(409, "Já existe um cargo com este nome ou código.")
            conn.executemany(
                "INSERT INTO role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)",
                [(code, permission) for permission in selected],
            )
        audit(actor["id"], "role.create", "role", code, {"profile_id": pid, "name": name}, self.client_ip())
        self.send_json(201, {"ok": True, "code": code, "message": "Cargo criado no perfil."})

    def api_role_update(self: Any, actor: dict[str, Any], role_code: str) -> None:
        if not has_permission(actor, "roles.manage"):
            raise ApiError(403, "Sem permissão para administrar cargos.")
        pid = current_profile_id(actor)
        data = self.read_json()
        with db_connect() as conn:
            role = conn.execute("SELECT * FROM roles WHERE code=?", (role_code,)).fetchone()
            if not role:
                raise ApiError(404, "Cargo não encontrado.")
            if role["is_system"]:
                if role_code == "owner":
                    raise ApiError(400, "O cargo Dono possui acesso total e não pode ser limitado.")
                if not is_platform_owner(actor):
                    raise ApiError(403, "O Contratante cria cargos próprios; cargos nativos só podem ser alterados pelo Dono.")
            elif int(role["profile_id"] or 0) != pid:
                raise ApiError(403, "Este cargo pertence a outro perfil.")
            updates: dict[str, Any] = {}
            if not role["is_system"]:
                if "name" in data:
                    name = str(data.get("name") or "").strip()
                    if len(name) < 2:
                        raise ApiError(400, "Nome inválido.")
                    updates["name"] = name
                if "description" in data:
                    updates["description"] = str(data.get("description") or "").strip()
                if "base_role" in data:
                    base = str(data.get("base_role") or "").strip()
                    if base not in {"manager", "bko", "seller"}:
                        raise ApiError(400, "Cargo-base inválido.")
                    updates["base_role"] = base
                if "active" in data:
                    active = 1 if bool(data.get("active")) else 0
                    if not active and conn.execute("SELECT COUNT(*) FROM profile_users WHERE profile_id=? AND role_code=? AND active=1", (pid, role_code)).fetchone()[0]:
                        raise ApiError(400, "Transfira os usuários antes de desativar este cargo.")
                    updates["active"] = active
            selected = None
            if "permissions" in data:
                valid = {item[0] for item in ns["PERMISSIONS"]}
                selected = sorted({str(item) for item in (data.get("permissions") or []) if str(item) in valid})
            if not updates and selected is None:
                raise ApiError(400, "Nenhuma alteração enviada.")
            if updates:
                updates["updated_at"] = utc_now()
                assignments = ",".join(f"{key}=?" for key in updates)
                conn.execute(f"UPDATE roles SET {assignments} WHERE code=?", [*updates.values(), role_code])
            if selected is not None:
                conn.execute("DELETE FROM role_permissions WHERE role_code=?", (role_code,))
                conn.executemany("INSERT INTO role_permissions(role_code,permission_code,allowed) VALUES(?,?,1)", [(role_code, item) for item in selected])
        audit(actor["id"], "role.update", "role", role_code, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Cargo atualizado."})

    # ------------------------- vendas -------------------------
    def api_sale_create(self: Any, user: dict[str, Any]) -> None:
        if not has_permission(user, "sales.create"):
            raise ApiError(403, "Sem permissão para cadastrar vendas.")
        pid = current_profile_id(user)
        data = self.read_json()
        client_name = str(data.get("client_name") or "").strip()
        phone = ns["normalize_mobile_phone"](data.get("phone") or "")
        plan_id = int(data.get("plan_id") or 0)
        if len(client_name) < 3 or not phone or not plan_id:
            raise ApiError(400, "Cliente, celular brasileiro válido e plano são obrigatórios.")
        with db_connect() as conn:
            plan = conn.execute("SELECT * FROM plans WHERE id=? AND profile_id=? AND active=1", (plan_id, pid)).fetchone()
            if not plan:
                raise ApiError(400, "Plano inválido ou pertencente a outro perfil.")
            seller_id = user["id"]
            if has_permission(user, "sales.all") and data.get("seller_id"):
                seller_id = int(data["seller_id"])
            seller = conn.execute(
                """SELECT pu.user_id AS id,pu.team_id,pu.active,r.base_role FROM profile_users pu JOIN roles r ON r.code=pu.role_code
                   WHERE pu.profile_id=? AND pu.user_id=? AND pu.active=1""",
                (pid, seller_id),
            ).fetchone()
            if not seller or seller["base_role"] not in {"seller", "manager"}:
                raise ApiError(400, "Vendedor inválido para este perfil.")
            fields = self.sale_general_values(data)
            if not fields["cpf_cnpj"]:
                raise ApiError(400, "CPF ou CNPJ é obrigatório para cadastrar a venda.")
            now = utc_now()
            cur = conn.execute(
                """INSERT INTO sales(
                    profile_id,person_type,client_name,cpf_cnpj,birth_date,mother_name,phone,contact_phone,email,
                    cep,address,address_number,complement,neighborhood,city,uf,property_type,
                    plan_id,plan_name_snapshot,plan_price_snapshot,provider,service,
                    payment_method,due_day,channel,suggested_date,suggested_period,notes,
                    seller_id,team_id,status,activation_status,biometric_status,installation_status,
                    created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'nova',
                    'aguardando_ativacao','biometria_pendente','aguardando_instalacao',?,?)""",
                (
                    pid, fields["person_type"], client_name, fields["cpf_cnpj"], fields["birth_date"], fields["mother_name"],
                    phone, fields["contact_phone"], fields["email"], fields["cep"], fields["address"], fields["address_number"],
                    fields["complement"], fields["neighborhood"], fields["city"], fields["uf"], fields["property_type"],
                    plan_id, plan["name"], plan["price"], plan["provider"], plan["service"], fields["payment_method"],
                    fields["due_day"], fields["channel"], fields["suggested_date"], fields["suggested_period"], fields["notes"],
                    seller_id, seller["team_id"], now, now,
                ),
            )
            sale_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO sale_history(sale_id,user_id,event_type,details,created_at) VALUES(?,?,'created',?,?)",
                (sale_id, user["id"], "Venda cadastrada", now),
            )
        audit(user["id"], "sale.create", "sale", sale_id, {"profile_id": pid, "client": client_name}, self.client_ip())
        self.trigger_webhook("sale.created", {"sale_id": sale_id, "client_name": client_name})
        self.send_json(201, {"ok": True, "id": sale_id, "message": "Venda cadastrada."})

    def api_sale_update(self: Any, user: dict[str, Any], sale_id: int) -> None:
        pid = current_profile_id(user)
        data = self.read_json()
        with db_connect() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id=? AND profile_id=?", (sale_id, pid)).fetchone()
            if not sale:
                raise ApiError(404, "Venda não encontrada neste perfil.")
            if data.get("plan_id") and not conn.execute("SELECT 1 FROM plans WHERE id=? AND profile_id=? AND active=1", (int(data["plan_id"]), pid)).fetchone():
                raise ApiError(400, "Plano inválido para este perfil.")
            if data.get("seller_id"):
                membership = conn.execute("SELECT team_id FROM profile_users WHERE profile_id=? AND user_id=? AND active=1", (pid, int(data["seller_id"]))).fetchone()
                if not membership:
                    raise ApiError(400, "Vendedor inválido para este perfil.")
                conn.execute("UPDATE users SET team_id=? WHERE id=?", (membership["team_id"], int(data["seller_id"])))
        return original_sale_update(self, user, sale_id)

    def api_sale_workflow(self: Any, user: dict[str, Any], sale_id: int) -> None:
        pid = current_profile_id(user)
        data = self.read_json()
        with db_connect() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id=? AND profile_id=?", (sale_id, pid)).fetchone()
            if not sale:
                raise ApiError(404, "Venda não encontrada neste perfil.")
            if data.get("bko_user_id"):
                target = int(data["bko_user_id"])
                member = conn.execute(
                    """SELECT r.base_role FROM profile_users pu JOIN roles r ON r.code=pu.role_code
                       WHERE pu.profile_id=? AND pu.user_id=? AND pu.active=1""",
                    (pid, target),
                ).fetchone()
                if not member or member["base_role"] not in {"bko", "manager"}:
                    raise ApiError(400, "Responsável BKO inválido para este perfil.")
                conn.execute("UPDATE users SET role_code=? WHERE id=?", (member["base_role"], target))
        return original_sale_workflow(self, user, sale_id)

    # ------------------------- ranking e análise -------------------------
    def api_ranking(self: Any, query: dict[str, list[str]]) -> None:
        user, _, _ = self.require_user()
        if not (has_permission(user, "ranking.all") or has_permission(user, "ranking.own")):
            raise ApiError(403, "Sem permissão para visualizar o ranking.")
        pid = current_profile_id(user)
        period = (query.get("period") or ["month"])[0]
        prefix = date.today().strftime("%Y-%m") if period == "month" else None
        date_clause = "AND substr(s.created_at,1,7)=?" if prefix else ""
        params: list[Any] = [pid]
        if prefix:
            params.append(prefix)
        with db_connect() as conn:
            rows = conn.execute(
                f"""SELECT u.id,u.name,COALESCE(t.name,'Sem equipe') AS team_name,
                    COUNT(s.id) AS total,
                    SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed,
                    SUM(CASE WHEN s.status='cancelada' THEN 1 ELSE 0 END) AS cancelled,
                    COALESCE(SUM(s.plan_price_snapshot),0) AS revenue
                    FROM profile_users pu JOIN users u ON u.id=pu.user_id
                    JOIN roles r ON r.code=pu.role_code
                    LEFT JOIN teams t ON t.id=pu.team_id AND t.profile_id=pu.profile_id
                    LEFT JOIN sales s ON s.seller_id=u.id AND s.profile_id=pu.profile_id {date_clause}
                    WHERE pu.profile_id=? AND pu.active=1 AND r.base_role='seller'
                    GROUP BY u.id,u.name,t.name""",
                ([prefix, pid] if prefix else [pid]),
            ).fetchall()
        ranking = []
        for row in rows:
            item = dict(row)
            total = item["total"] or 0
            installed = item["installed"] or 0
            item["conversion"] = round(installed * 100 / total, 1) if total else 0
            item["points"] = installed * 100 + total * 10 - (item["cancelled"] or 0) * 5
            ranking.append(item)
        ranking.sort(key=lambda item: (item["points"], item["installed"], item["total"]), reverse=True)
        for index, item in enumerate(ranking, 1):
            item["position"] = index
        if not has_permission(user, "ranking.all"):
            ranking = [item for item in ranking if item["id"] == user["id"]]
        self.send_json(200, {"ok": True, "period": period, "ranking": ranking})

    def api_daily_analysis(self: Any, query: dict[str, list[str]]) -> None:
        user = self.require_permission("daily.view")
        pid = current_profile_id(user)
        selected = (query.get("date") or [local_today()])[0]
        if not ns["validate_iso_date"](selected, False):
            raise ApiError(400, "Data inválida.")
        with db_connect() as conn:
            teams = conn.execute(
                """SELECT COALESCE(t.name,'Sem equipe') AS team_name,COUNT(s.id) AS sales,
                   SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed,
                   SUM(CASE WHEN s.status='cancelada' THEN 1 ELSE 0 END) AS cancelled
                   FROM sales s LEFT JOIN teams t ON t.id=s.team_id AND t.profile_id=s.profile_id
                   WHERE s.profile_id=? AND substr(s.created_at,1,10)=?
                   GROUP BY COALESCE(t.name,'Sem equipe') ORDER BY sales DESC""",
                (pid, selected),
            ).fetchall()
            sellers = conn.execute(
                """SELECT u.name AS seller_name,COALESCE(t.name,'Sem equipe') AS team_name,COUNT(s.id) AS sales,
                   SUM(CASE WHEN s.installation_status IN ('instalado','instalado_regra_pdv') THEN 1 ELSE 0 END) AS installed
                   FROM sales s JOIN users u ON u.id=s.seller_id
                   LEFT JOIN teams t ON t.id=s.team_id AND t.profile_id=s.profile_id
                   WHERE s.profile_id=? AND substr(s.created_at,1,10)=?
                   GROUP BY u.id,u.name,t.name ORDER BY sales DESC,u.name""",
                (pid, selected),
            ).fetchall()
        self.send_json(200, {"ok": True, "date": selected, "teams": [dict(row) for row in teams], "sellers": [dict(row) for row in sellers]})

    # ------------------------- caixa -------------------------
    def api_cash(self: Any, query: dict[str, list[str]]) -> None:
        user = self.require_permission("cash.view")
        pid = current_profile_id(user)
        date_from = (query.get("date_from") or [""])[0]
        date_to = (query.get("date_to") or [""])[0]
        filters = ["profile_id=?", "active=1"]
        params: list[Any] = [pid]
        if date_from:
            filters.append("transaction_date>=?")
            params.append(date_from)
        if date_to:
            filters.append("transaction_date<=?")
            params.append(date_to)
        where = " AND ".join(filters)
        with db_connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM cash_transactions WHERE {where} ORDER BY transaction_date DESC,id DESC LIMIT 1000",
                params,
            ).fetchall()
            summary = conn.execute(
                f"""SELECT
                   COALESCE(SUM(CASE WHEN transaction_type='entry' THEN amount ELSE 0 END),0) AS entries,
                   COALESCE(SUM(CASE WHEN transaction_type='exit' THEN amount ELSE 0 END),0) AS exits
                   FROM cash_transactions WHERE {where}""",
                params,
            ).fetchone()
        entries = float(summary["entries"] or 0)
        exits = float(summary["exits"] or 0)
        self.send_json(200, {"ok": True, "summary": {"entries": entries, "exits": exits, "balance": entries - exits}, "transactions": [dict(row) for row in rows]})

    def api_cash_create(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "cash.manage"):
            raise ApiError(403, "Sem permissão para administrar o caixa.")
        pid = current_profile_id(actor)
        data = self.read_json()
        transaction_type = str(data.get("transaction_type") or "").strip()
        category = str(data.get("category") or "").strip()
        description = str(data.get("description") or "").strip()
        amount = float(data.get("amount") or 0)
        transaction_date = str(data.get("transaction_date") or local_today()).strip()
        if transaction_type not in {"entry", "exit"} or not category or len(description) < 2 or amount <= 0:
            raise ApiError(400, "Tipo, categoria, descrição e valor positivo são obrigatórios.")
        if not ns["validate_iso_date"](transaction_date, False):
            raise ApiError(400, "Data inválida.")
        now = utc_now()
        with db_connect() as conn:
            cur = conn.execute(
                """INSERT INTO cash_transactions
                   (profile_id,transaction_type,category,description,amount,transaction_date,payment_method,notes,created_by,active,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,1,?,?)""",
                (pid, transaction_type, category, description, amount, transaction_date,
                 str(data.get("payment_method") or "").strip() or None,
                 str(data.get("notes") or "").strip()[:1000] or None,
                 actor["id"], now, now),
            )
        audit(actor["id"], "cash.create", "cash_transaction", cur.lastrowid, {"profile_id": pid, "type": transaction_type, "amount": amount}, self.client_ip())
        self.send_json(201, {"ok": True, "id": cur.lastrowid, "message": "Lançamento criado."})

    def api_cash_update(self: Any, actor: dict[str, Any], transaction_id: int) -> None:
        if not has_permission(actor, "cash.manage"):
            raise ApiError(403, "Sem permissão para administrar o caixa.")
        pid = current_profile_id(actor)
        data = self.read_json()
        allowed = {"transaction_type", "category", "description", "amount", "transaction_date", "payment_method", "notes", "active"}
        updates = {key: data[key] for key in allowed if key in data}
        if not updates:
            raise ApiError(400, "Nenhuma alteração enviada.")
        if "transaction_type" in updates and updates["transaction_type"] not in {"entry", "exit"}:
            raise ApiError(400, "Tipo de lançamento inválido.")
        if "amount" in updates:
            updates["amount"] = float(updates["amount"] or 0)
            if updates["amount"] <= 0:
                raise ApiError(400, "O valor deve ser positivo.")
        if "active" in updates:
            updates["active"] = 1 if bool(updates["active"]) else 0
        updates["updated_at"] = utc_now()
        with db_connect() as conn:
            if not conn.execute("SELECT 1 FROM cash_transactions WHERE id=? AND profile_id=?", (transaction_id, pid)).fetchone():
                raise ApiError(404, "Lançamento não encontrado.")
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE cash_transactions SET {assignments} WHERE id=? AND profile_id=?", [*updates.values(), transaction_id, pid])
        audit(actor["id"], "cash.update", "cash_transaction", transaction_id, {"profile_id": pid, "fields": list(updates)}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Lançamento atualizado."})

    # ------------------------- dashboard por tipo -------------------------
    def api_dashboard(self: Any) -> None:
        user = self.require_permission("dashboard.view")
        if user.get("profile_type") == "cash_control":
            pid = current_profile_id(user)
            today = local_today()
            month = today[:7]
            with db_connect() as conn:
                summary = conn.execute(
                    """SELECT
                       COALESCE(SUM(CASE WHEN transaction_type='entry' AND active=1 THEN amount ELSE 0 END),0) AS entries,
                       COALESCE(SUM(CASE WHEN transaction_type='exit' AND active=1 THEN amount ELSE 0 END),0) AS exits,
                       COALESCE(SUM(CASE WHEN transaction_type='entry' AND active=1 AND substr(transaction_date,1,7)=? THEN amount ELSE 0 END),0) AS month_entries,
                       COALESCE(SUM(CASE WHEN transaction_type='exit' AND active=1 AND substr(transaction_date,1,7)=? THEN amount ELSE 0 END),0) AS month_exits
                       FROM cash_transactions WHERE profile_id=?""",
                    (month, month, pid),
                ).fetchone()
                recent = conn.execute(
                    "SELECT * FROM cash_transactions WHERE profile_id=? AND active=1 ORDER BY transaction_date DESC,id DESC LIMIT 8",
                    (pid,),
                ).fetchall()
            entries = float(summary["entries"] or 0)
            exits = float(summary["exits"] or 0)
            self.send_json(200, {
                "ok": True,
                "profile_type": "cash_control",
                "cash": {
                    "entries": entries,
                    "exits": exits,
                    "balance": entries - exits,
                    "month_entries": float(summary["month_entries"] or 0),
                    "month_exits": float(summary["month_exits"] or 0),
                },
                "recent_transactions": [dict(row) for row in recent],
            })
            return
        return original_dashboard(self)

    # ------------------------- auditoria e integrações por perfil -------------------------
    def api_audit(self: Any, query: dict[str, list[str]]) -> None:
        user = self.require_permission("audit.view")
        pid = current_profile_id(user)
        limit = min(1000, max(1, int((query.get("limit") or ["300"])[0])))
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT a.*,u.name AS user_name FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id
                   WHERE a.profile_id=? ORDER BY a.id DESC LIMIT ?""",
                (pid, limit),
            ).fetchall()
        self.send_json(200, {"ok": True, "logs": [dict(row) for row in rows]})

    def profile_setting_rows(profile_id: int, keys: dict[str, bool]) -> dict[str, dict[str, Any]]:
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT key,value,secret,updated_at FROM profile_settings WHERE profile_id=? AND key IN (%s)" % ",".join("?" for _ in keys),
                (profile_id, *keys.keys()),
            ).fetchall()
        return {row["key"]: dict(row) for row in rows}

    def api_integrations_get(self: Any) -> None:
        actor, _, _ = self.require_user()
        if not (has_permission(actor, "integrations.manage") or has_permission(actor, "integrations.view")):
            raise ApiError(403, "Sem permissão para visualizar integrações.")
        pid = current_profile_id(actor)
        saved = profile_setting_rows(pid, self.INTEGRATION_KEYS)
        result: dict[str, Any] = {}
        for key, secret in self.INTEGRATION_KEYS.items():
            row = saved.get(key)
            result[key] = {
                "configured": bool(row and row["value"]),
                "value": "••••••••" if secret and row and row["value"] else (row["value"] if row else ""),
            }
        ai_status = ns["public_ai_status"](
            provider_override=result.get("ai_provider", {}).get("value") or "",
            groq_model_override=result.get("groq_model", {}).get("value") or "",
            openai_model_override=result.get("openai_model", {}).get("value") or "",
        )
        result["ai"] = ai_status
        result["groq"] = ai_status.get("providers", {}).get("groq", {})
        result["openai"] = ai_status.get("providers", {}).get("openai", {})
        self.send_json(200, {"ok": True, "integrations": result, "notes": {"scope": "Estas configurações pertencem somente ao perfil atual."}})

    def api_integrations_update(self: Any, actor: dict[str, Any]) -> None:
        if not has_permission(actor, "integrations.manage"):
            raise ApiError(403, "Sem permissão para administrar integrações.")
        pid = current_profile_id(actor)
        data = self.read_json()
        changed = []
        now = utc_now()
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
                conn.execute(
                    """INSERT INTO profile_settings(profile_id,key,value,secret,updated_by,updated_at)
                       VALUES(?,?,?,?,?,?)
                       ON CONFLICT(profile_id,key) DO UPDATE SET value=excluded.value,secret=excluded.secret,
                       updated_by=excluded.updated_by,updated_at=excluded.updated_at""",
                    (pid, key, value, 1 if secret else 0, actor["id"], now),
                )
                changed.append(key)
        audit(actor["id"], "integrations.update", "settings", pid, {"keys": changed}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Integrações do perfil atualizadas."})

    def api_powerbi_get(self: Any) -> None:
        actor = self.require_permission("powerbi.view")
        pid = current_profile_id(actor)
        with db_connect() as conn:
            row = conn.execute("SELECT value FROM profile_settings WHERE profile_id=? AND key='powerbi_embed_url'", (pid,)).fetchone()
        self.send_json(200, {"ok": True, "embed_url": row["value"] if row else ""})

    def trigger_webhook(self: Any, event: str, payload: dict[str, Any]) -> None:
        profile_id = getattr(REQUEST_CONTEXT, "profile_id", None)
        if not profile_id:
            return original_trigger_webhook(self, event, payload)
        with db_connect() as conn:
            row = conn.execute("SELECT value FROM profile_settings WHERE profile_id=? AND key='generic_webhook_url'", (profile_id,)).fetchone()
        if not row or not row["value"]:
            return
        # Reusa o mecanismo original colocando temporariamente a URL no contexto global seria inseguro;
        # envia diretamente com o mesmo formato.
        import urllib.request
        import threading as _threading
        body = json.dumps({"event": event, "app": ns["APP_NAME"], "version": ns["APP_VERSION"], "timestamp": utc_now(), "profile_id": profile_id, "data": payload}, ensure_ascii=False).encode("utf-8")
        def send() -> None:
            try:
                request = urllib.request.Request(row["value"], data=body, headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(request, timeout=6) as response:
                    ns["log"](f"Webhook {event} perfil {profile_id}: HTTP {response.status}")
            except Exception as exc:
                ns["log"](f"Webhook {event} perfil {profile_id} falhou: {exc}")
        _threading.Thread(target=send, daemon=True).start()

    # ------------------------- IA por perfil -------------------------
    def ai_settings_overrides(self: Any) -> dict[str, str]:
        user, _, _ = self.require_user()
        pid = current_profile_id(user)
        with db_connect() as conn:
            rows = conn.execute(
                "SELECT key,value FROM profile_settings WHERE profile_id=? AND key IN ('ai_provider','groq_model','openai_model')",
                (pid,),
            ).fetchall()
        saved = {str(row["key"]): str(row["value"] or "").strip() for row in rows}
        return {"provider": saved.get("ai_provider", ""), "groq_model": saved.get("groq_model", ""), "openai_model": saved.get("openai_model", "")}

    def record_ai_usage(self: Any, *, user_id: int, sale_id: int | None, status: str,
                        provider: str = "", model: str = "", response_id: str = "",
                        fallback_used: bool = False, question_length: int = 0,
                        usage: dict[str, Any] | None = None, error_code: str = "") -> None:
        usage = usage or {}
        profile_id = getattr(REQUEST_CONTEXT, "profile_id", None)
        try:
            with db_connect() as conn:
                conn.execute(
                    """INSERT INTO ai_usage_logs
                    (profile_id,user_id,sale_id,response_id,provider,model,fallback_used,question_length,input_tokens,output_tokens,status,error_code,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (profile_id, user_id, sale_id, response_id or None, provider or None, model or None,
                     1 if fallback_used else 0, max(0, int(question_length)),
                     max(0, int(usage.get("input_tokens") or 0)), max(0, int(usage.get("output_tokens") or 0)),
                     status, error_code or None, utc_now()),
                )
        except Exception as exc:
            ns["log"](f"Falha ao registrar uso da IA: {exc}")

    original_build_ai_context = Handler._build_ai_context

    def build_ai_context(self: Any, user: dict[str, Any], sale_id: int | None = None) -> dict[str, Any]:
        if user.get("profile_type") != "cash_control":
            context = original_build_ai_context(self, user, sale_id)
            context["perfil"] = {"nome": user.get("profile_name"), "tipo": user.get("profile_type")}
            return context
        pid = current_profile_id(user)
        with db_connect() as conn:
            summary = conn.execute(
                """SELECT
                   COALESCE(SUM(CASE WHEN transaction_type='entry' AND active=1 THEN amount ELSE 0 END),0) AS entradas,
                   COALESCE(SUM(CASE WHEN transaction_type='exit' AND active=1 THEN amount ELSE 0 END),0) AS saidas,
                   COUNT(*) AS quantidade
                   FROM cash_transactions WHERE profile_id=?""",
                (pid,),
            ).fetchone()
            categories = conn.execute(
                """SELECT category,
                   COALESCE(SUM(CASE WHEN transaction_type='entry' THEN amount ELSE 0 END),0) AS entradas,
                   COALESCE(SUM(CASE WHEN transaction_type='exit' THEN amount ELSE 0 END),0) AS saidas,
                   COUNT(*) AS quantidade
                   FROM cash_transactions WHERE profile_id=? AND active=1
                   GROUP BY category ORDER BY quantidade DESC LIMIT 30""",
                (pid,),
            ).fetchall()
            recent = conn.execute(
                """SELECT transaction_type,category,description,amount,transaction_date,payment_method
                   FROM cash_transactions WHERE profile_id=? AND active=1
                   ORDER BY transaction_date DESC,id DESC LIMIT 20""",
                (pid,),
            ).fetchall()
        entries = float(summary["entradas"] or 0)
        exits = float(summary["saidas"] or 0)
        return {
            "data_atual": local_today(),
            "perfil": {"nome": user.get("profile_name"), "tipo": "controle_de_caixa"},
            "usuario": {"cargo": user.get("role_name")},
            "indicadores_financeiros": {"entradas": entries, "saidas": exits, "saldo": entries - exits, "lancamentos": int(summary["quantidade"] or 0)},
            "categorias": [dict(row) for row in categories],
            "lancamentos_recentes": [dict(row) for row in recent],
        }

    Handler._ai_settings_overrides = ai_settings_overrides
    Handler._record_ai_usage = record_ai_usage
    Handler._build_ai_context = build_ai_context

    # ------------------------- rotas -------------------------
    def route_get(self: Any) -> None:
        parsed = ns["urlparse"](self.path)
        path = parsed.path.rstrip("/") or "/"
        query = ns["parse_qs"](parsed.query)
        if path == "/api/profiles":
            return self.api_profiles()
        if path == "/api/cash":
            return self.api_cash(query)
        return original_route_get(self)

    def route_write(self: Any, method: str) -> None:
        parsed = ns["urlparse"](self.path)
        path = parsed.path.rstrip("/") or "/"
        if path in {"/api/setup", "/api/login", "/api/logout"}:
            return original_route_write(self, method)
        user, csrf, _ = self.require_user()
        self.check_csrf(csrf)
        if method == "POST" and path == "/api/profiles":
            return self.api_profile_create(user)
        if method == "PUT" and path.startswith("/api/profiles/") and path != "/api/profiles/switch":
            return self.api_profile_update_business(user, int(path.rsplit("/", 1)[1]))
        if method == "POST" and path == "/api/profiles/switch":
            return self.api_profile_switch(user)
        if method == "POST" and path == "/api/cash":
            return self.api_cash_create(user)
        if method == "PUT" and path.startswith("/api/cash/"):
            return self.api_cash_update(user, int(path.rsplit("/", 1)[1]))
        return original_route_write(self, method)

    # Instala métodos e sobrescritas.
    Handler.route_get = route_get
    Handler.route_write = route_write
    Handler.api_profiles = api_profiles
    Handler.api_profile_create = api_profile_create
    Handler.api_profile_update_business = api_profile_update_business
    Handler.api_profile_switch = api_profile_switch
    Handler.api_users_list = api_users_list
    Handler.api_user_create = api_user_create
    Handler.api_user_update = api_user_update
    Handler.api_teams_list = api_teams_list
    Handler.api_team_create = api_team_create
    Handler.api_team_update = api_team_update
    Handler.api_plans_list = api_plans_list
    Handler.api_plan_create = api_plan_create
    Handler.api_plan_update = api_plan_update
    Handler.api_catalogs = api_catalogs
    Handler.api_catalog_create = api_catalog_create
    Handler.api_catalog_update = api_catalog_update
    Handler.api_roles = api_roles
    Handler.api_role_create = api_role_create
    Handler.api_role_update = api_role_update
    Handler.api_sale_create = api_sale_create
    Handler.api_sale_update = api_sale_update
    Handler.api_sale_workflow = api_sale_workflow
    Handler.api_ranking = api_ranking
    Handler.api_daily_analysis = api_daily_analysis
    Handler.api_cash = api_cash
    Handler.api_cash_create = api_cash_create
    Handler.api_cash_update = api_cash_update
    Handler.api_dashboard = api_dashboard
    Handler.api_audit = api_audit
    Handler.api_integrations_get = api_integrations_get
    Handler.api_integrations_update = api_integrations_update
    Handler.api_powerbi_get = api_powerbi_get
    Handler.trigger_webhook = trigger_webhook

