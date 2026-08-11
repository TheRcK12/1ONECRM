from __future__ import annotations

"""Extensões de produtividade e governança do ONE CRM 2.6.

Inclui: convites/reset por e-mail, tarefas/notificações, automações,
formulários personalizados, auditoria de segurança, anexos e dashboards.
"""

import base64
import hashlib
import json
import mimetypes
import os
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any


def install_productivity(ns: dict[str, Any]) -> None:
    db_connect = ns["db_connect"]
    utc_now = ns["utc_now"]
    ApiError = ns["ApiError"]
    Handler = ns["OneCRMHandler"]
    DATA_DIR: Path = ns["DATA_DIR"]
    BACKUP_DIR: Path = ns["BACKUP_DIR"]
    audit = ns["audit"]
    original_init_database = ns["init_database"]
    original_route_get = Handler.route_get
    original_route_write = Handler.route_write

    extra_permissions = [
        ("tasks.view", "Produtividade", "Visualizar tarefas e notificações"),
        ("tasks.manage", "Produtividade", "Criar e administrar tarefas"),
        ("automations.manage", "Automação", "Criar regras automáticas"),
        ("forms.view", "Personalização", "Visualizar formulários disponíveis"),
        ("forms.submit", "Personalização", "Preencher e enviar formulários"),
        ("forms.manage", "Personalização", "Criar formulários, campos e consultar envios"),
        ("attachments.manage", "Documentos", "Enviar e administrar documentos e anexos"),
        ("reports.manage", "Relatórios", "Criar dashboards e relatórios personalizados"),
        ("security.alerts", "Segurança", "Visualizar alertas de segurança"),
        ("invitations.manage", "Pessoas", "Convidar usuários e reenviar convites"),
    ]
    existing = {item[0] for item in ns["PERMISSIONS"]}
    ns["PERMISSIONS"].extend(item for item in extra_permissions if item[0] not in existing)

    def init_productivity_schema() -> None:
        original_init_database()
        with db_connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS account_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                email TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                purpose TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_by INTEGER,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_account_tokens_email ON account_tokens(email,purpose,expires_at);

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'normal',
                due_at TEXT,
                assigned_user_id INTEGER,
                created_by INTEGER NOT NULL,
                related_type TEXT,
                related_id INTEGER,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_profile ON tasks(profile_id,status,due_at);

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                level TEXT NOT NULL DEFAULT 'info',
                link TEXT NOT NULL DEFAULT '',
                read_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,read_at,created_at);
            CREATE INDEX IF NOT EXISTS idx_notifications_profile_user ON notifications(profile_id,user_id,read_at,created_at);

            CREATE TABLE IF NOT EXISTS automation_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                trigger_event TEXT NOT NULL,
                conditions_json TEXT NOT NULL DEFAULT '{}',
                actions_json TEXT NOT NULL DEFAULT '[]',
                active INTEGER NOT NULL DEFAULT 1,
                last_run_at TEXT,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS custom_forms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                schema_json TEXT NOT NULL DEFAULT '[]',
                active INTEGER NOT NULL DEFAULT 1,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(profile_id,code)
            );

            CREATE TABLE IF NOT EXISTS custom_form_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                form_id INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_custom_form_entries_profile_form ON custom_form_entries(profile_id,form_id,created_at);

            CREATE TABLE IF NOT EXISTS attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                uploaded_by INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_attachments_profile ON attachments(profile_id,created_at);

            CREATE TABLE IF NOT EXISTS dashboard_views (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL,
                owner_user_id INTEGER,
                name TEXT NOT NULL,
                config_json TEXT NOT NULL DEFAULT '{}',
                is_default INTEGER NOT NULL DEFAULT 0,
                created_by INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS security_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER,
                user_id INTEGER,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                title TEXT NOT NULL,
                details_json TEXT NOT NULL DEFAULT '{}',
                resolved_at TEXT,
                resolved_by INTEGER,
                created_at TEXT NOT NULL
            );
            """)
    ns["init_database"] = init_productivity_schema

    def pid(user: dict[str, Any]) -> int:
        value = int(user.get("profile_id") or 0)
        if not value:
            raise ApiError(409, "Selecione um perfil ativo.")
        return value

    def require_perm(user: dict[str, Any], permission: str) -> None:
        if user.get("is_platform_owner") or user.get("role_code") == "owner":
            return
        permission_check = ns.get("has_permission")
        if callable(permission_check):
            if permission_check(user, permission):
                return
        elif permission in set(user.get("permissions") or []):
            return
        raise ApiError(403, "Seu cargo não possui permissão para esta ação.")

    def has_perm(user: dict[str, Any], permission: str) -> bool:
        if user.get("is_platform_owner") or user.get("role_code") == "owner":
            return True
        permission_check = ns.get("has_permission")
        if callable(permission_check):
            return bool(permission_check(user, permission))
        return permission in set(user.get("permissions") or [])

    def require_any_perm(user: dict[str, Any], *permissions: str) -> None:
        if any(has_perm(user, permission) for permission in permissions):
            return
        raise ApiError(403, "Seu cargo não possui permissão para esta ação.")

    def user_can_receive_in_profile(profile_id: int, user_id: int) -> bool:
        """Impede tarefas/notificações de atravessarem perfis por IDs reaproveitados ou regras antigas."""
        if not profile_id or not user_id:
            return False
        with db_connect() as conn:
            row = conn.execute(
                """SELECT u.active,u.role_code,u.platform_role_code,
                          EXISTS(SELECT 1 FROM profile_users pu
                                 WHERE pu.profile_id=? AND pu.user_id=u.id AND pu.active=1) AS in_profile
                   FROM users u WHERE u.id=?""",
                (profile_id, user_id),
            ).fetchone()
        if not row or not bool(row["active"]):
            return False
        return bool(row["in_profile"]) or str(row["role_code"] or "") == "owner" or str(row["platform_role_code"] or "") == "owner"

    def require_profile_recipient(profile_id: int, user_id: int) -> None:
        if not user_can_receive_in_profile(profile_id, user_id):
            raise ApiError(400, "O responsável selecionado não pertence ao perfil atual.")

    def profile_user_options(profile_id: int) -> list[dict[str, Any]]:
        """Lista mínima de pessoas do perfil para seletores operacionais.

        Não depende de users.view: administrar uma tarefa, formulário ou automação
        exige escolher um destinatário, não abrir a ficha completa do funcionário.
        """
        with db_connect() as conn:
            rows = conn.execute(
                """SELECT u.id,u.name,COALESCE(pu.role_code,u.role_code) AS role_code,COALESCE(pu.is_contractor,0) AS is_contractor
                   FROM users u LEFT JOIN profile_users pu ON pu.user_id=u.id AND pu.profile_id=?
                   WHERE u.active=1 AND (pu.active=1 OR u.role_code='owner' OR u.platform_role_code='owner')
                   ORDER BY COALESCE(pu.is_contractor,0) DESC,u.name""",
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def token_hash(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def app_base_url(handler: Any) -> str:
        configured = (os.getenv("ONE_CRM_PUBLIC_URL") or "").strip().rstrip("/")
        return configured or handler.expected_origin()

    def send_email(to_email: str, subject: str, text: str) -> tuple[bool, str]:
        host = (os.getenv("SMTP_HOST") or "").strip()
        user = (os.getenv("SMTP_USER") or "").strip()
        password = os.getenv("SMTP_PASSWORD") or ""
        sender = (os.getenv("SMTP_FROM") or user).strip()
        if not host or not sender:
            return False, "SMTP não configurado; link gerado apenas na resposta administrativa."
        port = int(os.getenv("SMTP_PORT") or "587")
        use_ssl = (os.getenv("SMTP_SSL") or "0").lower() in {"1", "true", "yes"}
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(text)
        context = ssl.create_default_context()
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as smtp:
                if user: smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.ehlo(); smtp.starttls(context=context); smtp.ehlo()
                if user: smtp.login(user, password)
                smtp.send_message(msg)
        return True, "E-mail enviado."

    def create_account_token(email: str, purpose: str, user_id: int | None, created_by: int | None, hours: int) -> str:
        raw = secrets.token_urlsafe(40)
        expires = (datetime.now() + timedelta(hours=hours)).replace(microsecond=0).isoformat()
        with db_connect() as conn:
            conn.execute("UPDATE account_tokens SET used_at=? WHERE email=? AND purpose=? AND used_at IS NULL", (utc_now(), email, purpose))
            conn.execute("INSERT INTO account_tokens(user_id,email,token_hash,purpose,expires_at,created_by,created_at) VALUES(?,?,?,?,?,?,?)",
                         (user_id,email,token_hash(raw),purpose,expires,created_by,utc_now()))
        return raw

    def public_task(row: Any) -> dict[str, Any]:
        d = dict(row)
        d["overdue"] = bool(d.get("due_at") and d.get("status") != "done" and d["due_at"] < utc_now())
        return d

    def create_notification(profile_id: int, user_id: int, title: str, message: str, level: str="info", link: str="") -> bool:
        if not user_can_receive_in_profile(profile_id, user_id):
            return False
        with db_connect() as conn:
            conn.execute("INSERT INTO notifications(profile_id,user_id,title,message,level,link,created_at) VALUES(?,?,?,?,?,?,?)",
                         (profile_id,user_id,title,message,level,link,utc_now()))
        return True

    def run_automations(profile_id: int, event: str, context: dict[str, Any]) -> int:
        executed = 0
        with db_connect() as conn:
            rules = conn.execute("SELECT * FROM automation_rules WHERE profile_id=? AND active=1 AND trigger_event=?", (profile_id,event)).fetchall()
        for rule in rules:
            conditions = json.loads(rule["conditions_json"] or "{}")
            if any(str(context.get(k, "")) != str(v) for k,v in conditions.items()):
                continue
            actions = json.loads(rule["actions_json"] or "[]")
            for action in actions:
                kind = action.get("type")
                if kind == "notify" and action.get("user_id"):
                    create_notification(profile_id,int(action["user_id"]),action.get("title") or rule["name"],action.get("message") or "Automação executada.",action.get("level") or "info",action.get("link") or "")
                elif kind == "task" and action.get("assigned_user_id"):
                    assigned_user_id = int(action["assigned_user_id"])
                    if not user_can_receive_in_profile(profile_id, assigned_user_id):
                        continue
                    now = utc_now()
                    with db_connect() as conn:
                        conn.execute("INSERT INTO tasks(profile_id,title,description,status,priority,due_at,assigned_user_id,created_by,related_type,related_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (profile_id,action.get("title") or rule["name"],action.get("description") or "",'pending',action.get("priority") or 'normal',action.get("due_at"),assigned_user_id,int(rule["created_by"]),context.get("entity_type"),context.get("entity_id"),now,now))
            with db_connect() as conn:
                conn.execute("UPDATE automation_rules SET last_run_at=? WHERE id=?", (utc_now(),rule["id"]))
            executed += 1
        return executed

    # ---------- endpoints ----------
    def api_invite(self: Any, actor: dict[str, Any]) -> None:
        require_any_perm(actor, "invitations.manage", "users.manage")
        data = self.read_json()
        email = str(data.get("email") or "").strip().lower()
        name = str(data.get("name") or "").strip()
        role_code = str(data.get("role_code") or "seller").strip()
        team_id = int(data.get("team_id") or 0) or None
        profile_id = pid(actor)
        if "@" not in email or len(name) < 2:
            raise ApiError(400, "Informe nome e e-mail válidos.")
        with db_connect() as conn:
            role = conn.execute("SELECT code,base_role FROM roles WHERE code=? AND active=1 AND profile_id=?", (role_code, profile_id)).fetchone()
            if not role:
                profile = conn.execute("SELECT business_type FROM business_profiles WHERE id=?", (profile_id,)).fetchone()
                if profile and profile["business_type"] == "internet_sales":
                    role = conn.execute(
                        "SELECT code,base_role FROM roles WHERE code=? AND active=1 AND is_system=1 AND code IN ('manager','bko','seller')",
                        (role_code,),
                    ).fetchone()
            if not role:
                raise ApiError(400, "Cargo inválido para o perfil atual.")
            if str(role["base_role"] or "") == "owner" and not (actor.get("is_platform_owner") or actor.get("role_code") == "owner" or actor.get("platform_role_code") == "owner"):
                raise ApiError(403, "Somente o Dono da plataforma pode convidar outro Dono.")
            if team_id and not conn.execute("SELECT 1 FROM teams WHERE id=? AND profile_id=? AND active=1", (team_id, profile_id)).fetchone():
                raise ApiError(400, "Equipe inválida para o perfil atual.")
            row = conn.execute("SELECT id,active,role_code FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
            now = utc_now()
            if row:
                user_id = int(row["id"])
                existing_active = bool(row["active"])
                conn.execute("UPDATE users SET name=COALESCE(NULLIF(?,''),name),updated_at=? WHERE id=?", (name, now, user_id))
            else:
                temp = secrets.token_urlsafe(32)
                cur = conn.execute(
                    """INSERT INTO users(name,email,password_hash,role_code,active,must_change_password,created_at,updated_at)
                       VALUES(?,?,?,?,0,1,?,?)""",
                    (name, email, ns["hash_password"](temp), str(role["base_role"] or "seller"), now, now),
                )
                user_id = int(cur.lastrowid)
                existing_active = False
            conn.execute(
                """INSERT INTO profile_users(profile_id,user_id,role_code,team_id,is_contractor,active,created_at,updated_at)
                   VALUES(?,?,?,?,0,1,?,?)
                   ON CONFLICT(profile_id,user_id) DO UPDATE SET
                   role_code=excluded.role_code,team_id=excluded.team_id,active=1,updated_at=excluded.updated_at""",
                (profile_id, user_id, role_code, team_id, now, now),
            )
        if existing_active:
            link = app_base_url(self) + "/#/dashboard"
            try:
                sent, msg = send_email(email, "Acesso liberado no ONE CRM", f"Seu acesso ao perfil foi liberado no ONE CRM.\n\nAbra: {link}")
            except Exception as exc:
                sent, msg = False, f"Não foi possível enviar o e-mail: {exc}"
            invite_url = link if not sent else ""
        else:
            raw = create_account_token(email, "invite", user_id, actor["id"], 48)
            link = f"{app_base_url(self)}/#/?token={raw}&action=accept-invite"
            try:
                sent, msg = send_email(email, "Convite para o ONE CRM", f"Você foi convidado para o ONE CRM.\n\nAbra: {link}\n\nO link expira em 48 horas.")
            except Exception as exc:
                sent, msg = False, f"Não foi possível enviar o e-mail: {exc}"
            invite_url = link if not sent else ""
        audit(actor["id"], "user.invite", "user", user_id, {"email": email, "profile_id": profile_id, "role": role_code, "email_sent": sent}, self.client_ip())
        self.send_json(201, {"ok": True, "message": msg, "invite_url": invite_url, "email_sent": sent, "user_id": user_id})

    def api_password_request(self: Any) -> None:
        data=self.read_json(); email=str(data.get("email") or "").strip().lower()
        with db_connect() as conn: row=conn.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE AND active=1",(email,)).fetchone()
        if row:
            raw=create_account_token(email,"reset",int(row[0]),None,1)
            link=f"{app_base_url(self)}/#/?token={raw}&action=reset-password"
            try: send_email(email,"Redefinição de senha do ONE CRM",f"Use este link para redefinir sua senha:\n\n{link}\n\nO link expira em 1 hora.")
            except Exception: pass
        self.send_json(200,{"ok":True,"message":"Se a conta existir, as instruções foram enviadas."})

    def api_token_complete(self: Any) -> None:
        data=self.read_json(); raw=str(data.get("token") or ""); password=str(data.get("password") or "")
        err=ns["validate_password"](password)
        if err: raise ApiError(400,err)
        now=utc_now()
        with db_connect() as conn:
            row=conn.execute("SELECT * FROM account_tokens WHERE token_hash=? AND used_at IS NULL AND expires_at>?",(token_hash(raw),now)).fetchone()
            if not row: raise ApiError(400,"Link inválido ou expirado.")
            conn.execute("UPDATE users SET password_hash=?,active=1,must_change_password=0,updated_at=? WHERE id=?",(ns["hash_password"](password),now,row["user_id"]))
            conn.execute("UPDATE account_tokens SET used_at=? WHERE id=?",(now,row["id"]))
            conn.execute("DELETE FROM sessions WHERE user_id=?",(row["user_id"],))
        self.send_json(200,{"ok":True,"message":"Senha definida com sucesso."})

    def api_tasks_list(self: Any, user: dict[str, Any]) -> None:
        # Qualquer integrante ativo do perfil pode consultar as próprias tarefas.
        # tasks.manage continua sendo necessário para enxergar/administrar as demais.
        profile_id = pid(user)
        can_manage = has_perm(user, "tasks.manage")
        with db_connect() as conn:
            if can_manage:
                rows = conn.execute(
                    """SELECT t.*,u.name assigned_name,c.name created_by_name
                       FROM tasks t
                       LEFT JOIN users u ON u.id=t.assigned_user_id
                       LEFT JOIN users c ON c.id=t.created_by
                       WHERE t.profile_id=?
                       ORDER BY CASE t.status WHEN 'in_progress' THEN 0 WHEN 'pending' THEN 1 WHEN 'done' THEN 2 ELSE 3 END,
                                CASE WHEN t.due_at IS NULL OR t.due_at='' THEN 1 ELSE 0 END,t.due_at,t.id DESC""",
                    (profile_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT t.*,u.name assigned_name,c.name created_by_name
                       FROM tasks t
                       LEFT JOIN users u ON u.id=t.assigned_user_id
                       LEFT JOIN users c ON c.id=t.created_by
                       WHERE t.profile_id=? AND t.assigned_user_id=?
                       ORDER BY CASE t.status WHEN 'in_progress' THEN 0 WHEN 'pending' THEN 1 WHEN 'done' THEN 2 ELSE 3 END,
                                t.due_at,t.id DESC""",
                    (profile_id, user["id"]),
                ).fetchall()
        self.send_json(200, {
            "ok": True,
            "tasks": [public_task(r) for r in rows],
            "can_manage": can_manage,
            "current_user_id": int(user["id"]),
            "assignees": profile_user_options(profile_id) if can_manage else [],
        })

    def api_task_create(self: Any, actor: dict[str, Any]) -> None:
        require_perm(actor, "tasks.manage")
        data = self.read_json()
        title = str(data.get("title") or "").strip()
        priority = str(data.get("priority") or "normal")
        if len(title) < 3:
            raise ApiError(400, "Informe o título da tarefa.")
        if priority not in {"low", "normal", "high", "urgent"}:
            raise ApiError(400, "Prioridade inválida.")
        now = utc_now()
        profile_id = pid(actor)
        assigned = int(data.get("assigned_user_id") or actor["id"])
        require_profile_recipient(profile_id, assigned)
        with db_connect() as conn:
            cur = conn.execute(
                """INSERT INTO tasks(profile_id,title,description,status,priority,due_at,assigned_user_id,created_by,related_type,related_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (profile_id, title, str(data.get("description") or ""), "pending", priority, data.get("due_at") or None,
                 assigned, actor["id"], data.get("related_type") or None, data.get("related_id") or None, now, now),
            )
            task_id = int(cur.lastrowid)
        create_notification(profile_id, assigned, "Nova tarefa", title, "info", "#/work-center")
        run_automations(profile_id, "task.created", {"entity_type": "task", "entity_id": task_id, "priority": priority, "status": "pending"})
        audit(actor["id"], "task.create", "task", task_id, {"title": title, "profile_id": profile_id, "assigned_user_id": assigned}, self.client_ip())
        self.send_json(201, {"ok": True, "id": task_id, "message": "Tarefa criada."})

    def api_task_update(self: Any, actor: dict[str, Any], task_id: int) -> None:
        data = self.read_json()
        profile_id = pid(actor)
        allowed_statuses = {"pending", "in_progress", "done", "cancelled"}
        can_manage = has_perm(actor, "tasks.manage")
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id=? AND profile_id=?", (task_id, profile_id)).fetchone()
            if not row:
                raise ApiError(404, "Tarefa não encontrada.")
            is_assignee = int(row["assigned_user_id"] or 0) == int(actor["id"])
            if not can_manage and not is_assignee:
                raise ApiError(403, "Sem permissão para alterar esta tarefa.")
            status = str(data.get("status") if "status" in data else row["status"])
            if status not in allowed_statuses:
                raise ApiError(400, "Status de tarefa inválido.")
            if not can_manage and status == "cancelled":
                raise ApiError(403, "Somente quem administra tarefas pode cancelar uma tarefa.")
            if can_manage:
                title = str(data.get("title") if "title" in data else row["title"]).strip()
                if len(title) < 3:
                    raise ApiError(400, "Informe o título da tarefa.")
                description = str(data.get("description") if "description" in data else row["description"])
                priority = str(data.get("priority") if "priority" in data else row["priority"])
                if priority not in {"low", "normal", "high", "urgent"}:
                    raise ApiError(400, "Prioridade inválida.")
                due_at = data.get("due_at") if "due_at" in data else row["due_at"]
                assigned_user_id = int(data.get("assigned_user_id") or row["assigned_user_id"] or actor["id"])
                require_profile_recipient(profile_id, assigned_user_id)
            else:
                # Um funcionário/contratante designado pode conduzir a própria tarefa,
                # mas não reescrever o título, prazo, prioridade ou responsável.
                title = str(row["title"])
                description = str(row["description"] or "")
                priority = str(row["priority"] or "normal")
                due_at = row["due_at"]
                assigned_user_id = int(row["assigned_user_id"] or actor["id"])
            completed = utc_now() if status == "done" else None
            conn.execute(
                """UPDATE tasks SET title=?,description=?,status=?,priority=?,due_at=?,assigned_user_id=?,completed_at=?,updated_at=?
                   WHERE id=? AND profile_id=?""",
                (title, description, status, priority, due_at, assigned_user_id, completed, utc_now(), task_id, profile_id),
            )
        if status != str(row["status"]):
            if int(row["created_by"] or 0) and int(row["created_by"] or 0) != int(actor["id"]):
                create_notification(profile_id, int(row["created_by"]), "Tarefa atualizada", f"{title}: status alterado para {status}.", "info", "#/work-center")
            if assigned_user_id != int(actor["id"]):
                create_notification(profile_id, assigned_user_id, "Tarefa atualizada", f"{title}: status alterado para {status}.", "info", "#/work-center")
        run_automations(profile_id, "task.updated", {"entity_type": "task", "entity_id": task_id, "status": status, "priority": priority})
        audit(actor["id"], "task.update", "task", task_id, {"profile_id": profile_id, "status": status, "managed": can_manage}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Tarefa atualizada."})

    def api_notifications(self: Any, user: dict[str,Any]) -> None:
        profile_id=pid(user)
        with db_connect() as conn:
            rows=conn.execute("SELECT * FROM notifications WHERE profile_id=? AND user_id=? ORDER BY created_at DESC LIMIT 100",(profile_id,user["id"])).fetchall()
        self.send_json(200,{"ok":True,"profile_id":profile_id,"notifications":[dict(r) for r in rows],"unread":sum(1 for r in rows if not r["read_at"])})

    def api_notification_read(self: Any, user: dict[str, Any], notification_id: int) -> None:
        profile_id = pid(user)
        with db_connect() as conn:
            conn.execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=? AND profile_id=?", (utc_now(), notification_id, user["id"], profile_id))
        self.send_json(200, {"ok": True})

    def api_notifications_read_all(self: Any, user: dict[str, Any]) -> None:
        profile_id = pid(user)
        with db_connect() as conn:
            conn.execute("UPDATE notifications SET read_at=? WHERE profile_id=? AND user_id=? AND read_at IS NULL", (utc_now(), profile_id, user["id"]))
        self.send_json(200, {"ok": True, "message": "Notificações marcadas como lidas."})

    def api_automations(self: Any,user:dict[str,Any]) -> None:
        require_perm(user,"automations.manage")
        with db_connect() as conn: rows=conn.execute("SELECT * FROM automation_rules WHERE profile_id=? ORDER BY id DESC",(pid(user),)).fetchall()
        result=[]
        for r in rows:
            d=dict(r); d["conditions"]=json.loads(d.pop("conditions_json") or "{}"); d["actions"]=json.loads(d.pop("actions_json") or "[]"); result.append(d)
        self.send_json(200,{"ok":True,"rules":result,"recipients":profile_user_options(pid(user))})

    def api_automation_save(self: Any, actor: dict[str, Any]) -> None:
        require_perm(actor, "automations.manage")
        data = self.read_json()
        now = utc_now()
        rule_id = int(data.get("id") or 0)
        profile_id = pid(actor)
        name = str(data.get("name") or "").strip()
        trigger = str(data.get("trigger_event") or "task.created")
        conditions = data.get("conditions") or {}
        actions = data.get("actions") or []
        if len(name) < 3:
            raise ApiError(400, "Informe um nome para a automação.")
        if trigger not in {"task.created", "task.updated", "form.submitted"}:
            raise ApiError(400, "Gatilho inválido.")
        if not isinstance(conditions, dict):
            raise ApiError(400, "Condição inválida.")
        if not isinstance(actions, list) or not actions:
            raise ApiError(400, "Adicione pelo menos uma ação.")
        normalized_actions = []
        for action in actions:
            if not isinstance(action, dict) or action.get("type") not in {"notify", "task"}:
                raise ApiError(400, "Existe uma ação inválida na automação.")
            kind = action["type"]
            target = action.get("assigned_user_id") if kind == "task" else action.get("user_id")
            if not target:
                raise ApiError(400, "Escolha o destinatário de todas as ações.")
            require_profile_recipient(profile_id, int(target))
            clean = dict(action)
            if kind == "task":
                clean["priority"] = str(clean.get("priority") or "normal")
                if clean["priority"] not in {"low", "normal", "high", "urgent"}:
                    raise ApiError(400, "Prioridade inválida em uma ação de tarefa.")
            else:
                clean["level"] = str(clean.get("level") or "info")
                if clean["level"] not in {"info", "warning", "danger"}:
                    raise ApiError(400, "Nível de notificação inválido.")
            normalized_actions.append(clean)
        payload = (name, trigger, json.dumps(conditions, ensure_ascii=False), json.dumps(normalized_actions, ensure_ascii=False), 1 if data.get("active", True) else 0, now)
        with db_connect() as conn:
            if rule_id:
                changed = conn.execute(
                    "UPDATE automation_rules SET name=?,trigger_event=?,conditions_json=?,actions_json=?,active=?,updated_at=? WHERE id=? AND profile_id=?",
                    (*payload, rule_id, profile_id),
                ).rowcount
                if not changed:
                    raise ApiError(404, "Automação não encontrada.")
            else:
                cur = conn.execute(
                    "INSERT INTO automation_rules(profile_id,name,trigger_event,conditions_json,actions_json,active,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (profile_id, *payload[:-1], actor["id"], now, now),
                )
                rule_id = int(cur.lastrowid)
        audit(actor["id"], "automation.save", "automation_rule", rule_id, {"profile_id": profile_id, "trigger": trigger}, self.client_ip())
        self.send_json(200, {"ok": True, "id": rule_id})

    def api_forms(self: Any, user: dict[str, Any]) -> None:
        require_any_perm(user, "forms.view", "forms.submit", "forms.manage")
        profile_id = pid(user)
        can_manage = has_perm(user, "forms.manage")
        can_submit = can_manage or has_perm(user, "forms.submit")
        filters = "f.profile_id=?" if can_manage else "f.profile_id=? AND f.active=1"
        with db_connect() as conn:
            rows = conn.execute(
                f"""SELECT f.*,
                    (SELECT COUNT(*) FROM custom_form_entries e WHERE e.profile_id=f.profile_id AND e.form_id=f.id) AS entries_count
                    FROM custom_forms f WHERE {filters} ORDER BY f.active DESC,f.name""",
                (profile_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["schema"] = json.loads(d.pop("schema_json") or "[]")
            out.append(d)
        self.send_json(200, {
            "ok": True,
            "forms": out,
            "can_manage": can_manage,
            "can_submit": can_submit,
            "user_options": profile_user_options(profile_id) if (can_manage or can_submit) else [],
        })

    def api_form_save(self: Any,actor:dict[str,Any]) -> None:
        require_perm(actor,"forms.manage"); data=self.read_json(); code=re.sub(r"[^a-z0-9_]+","_",str(data.get("code") or data.get("name") or "").lower()).strip("_")
        if not code: raise ApiError(400,"Informe o nome do formulário.")
        schema=data.get("schema") or []
        allowed={"text","textarea","number","currency","date","datetime","email","phone","select","checkbox","user","file"}
        if any(not isinstance(f,dict) or f.get("type") not in allowed or not f.get("key") for f in schema): raise ApiError(400,"Existe campo inválido no formulário.")
        now=utc_now(); form_id=int(data.get("id") or 0)
        with db_connect() as conn:
            if form_id:
                conn.execute("UPDATE custom_forms SET code=?,name=?,description=?,schema_json=?,active=?,updated_at=? WHERE id=? AND profile_id=?",(code,str(data.get("name") or code),str(data.get("description") or ""),json.dumps(schema,ensure_ascii=False),1 if data.get("active",True) else 0,now,form_id,pid(actor)))
            else:
                cur=conn.execute("INSERT INTO custom_forms(profile_id,code,name,description,schema_json,active,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(pid(actor),code,str(data.get("name") or code),str(data.get("description") or ""),json.dumps(schema,ensure_ascii=False),1,actor["id"],now,now)); form_id=int(cur.lastrowid)
        self.send_json(200,{"ok":True,"id":form_id})

    def api_form_entry(self: Any, actor: dict[str, Any], form_id: int) -> None:
        require_any_perm(actor, "forms.submit", "forms.manage")
        data = self.read_json()
        profile_id = pid(actor)
        with db_connect() as conn:
            form = conn.execute("SELECT * FROM custom_forms WHERE id=? AND profile_id=? AND active=1", (form_id, profile_id)).fetchone()
            if not form:
                raise ApiError(404, "Formulário não encontrado.")
            schema = json.loads(form["schema_json"] or "[]")
            values = data.get("data") or {}
            if not isinstance(values, dict):
                raise ApiError(400, "Dados do formulário inválidos.")
            allowed_keys = {str(field.get("key") or "") for field in schema}
            values = {str(key): value for key, value in values.items() if str(key) in allowed_keys}
            for field in schema:
                key = str(field.get("key") or "")
                if field.get("required") and values.get(key) in (None, "", []):
                    raise ApiError(400, f"O campo {field.get('label') or key} é obrigatório.")
            now = utc_now()
            cur = conn.execute(
                "INSERT INTO custom_form_entries(profile_id,form_id,data_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (profile_id, form_id, json.dumps(values, ensure_ascii=False), actor["id"], now, now),
            )
            entry_id = int(cur.lastrowid)
        run_automations(profile_id, "form.submitted", {"entity_type": "custom_form", "entity_id": entry_id, "form_id": form_id})
        audit(actor["id"], "form.submit", "custom_form_entry", entry_id, {"profile_id": profile_id, "form_id": form_id}, self.client_ip())
        self.send_json(201, {"ok": True, "id": entry_id, "message": "Formulário enviado."})

    def api_form_entries(self: Any, actor: dict[str, Any], form_id: int) -> None:
        require_perm(actor, "forms.manage")
        profile_id = pid(actor)
        with db_connect() as conn:
            form = conn.execute("SELECT id,name,schema_json FROM custom_forms WHERE id=? AND profile_id=?", (form_id, profile_id)).fetchone()
            if not form:
                raise ApiError(404, "Formulário não encontrado.")
            rows = conn.execute(
                """SELECT e.*,u.name AS created_by_name
                   FROM custom_form_entries e LEFT JOIN users u ON u.id=e.created_by
                   WHERE e.profile_id=? AND e.form_id=? ORDER BY e.id DESC LIMIT 1000""",
                (profile_id, form_id),
            ).fetchall()
        entries = []
        for row in rows:
            d = dict(row)
            d["data"] = json.loads(d.pop("data_json") or "{}")
            entries.append(d)
        self.send_json(200, {"ok": True, "form": {"id": form["id"], "name": form["name"], "schema": json.loads(form["schema_json"] or "[]")}, "entries": entries})

    ATTACH_DIR = DATA_DIR / "attachments"
    ATTACH_DIR.mkdir(parents=True, exist_ok=True)

    def attachment_access_allowed(user: dict[str, Any], row: Any) -> bool:
        if has_perm(user, "attachments.manage"):
            return True
        if str(row["entity_type"] or "") == "custom_form_entry" and (has_perm(user, "forms.manage") or has_perm(user, "forms.submit")):
            if has_perm(user, "forms.manage"):
                return True
            with db_connect() as conn:
                entry = conn.execute("SELECT created_by FROM custom_form_entries WHERE id=? AND profile_id=?", (int(row["entity_id"] or 0), pid(user))).fetchone()
            return bool(entry and int(entry["created_by"] or 0) == int(user["id"]))
        return False

    def api_attachment_upload(self: Any, actor: dict[str, Any]) -> None:
        data = self.read_json()
        raw = str(data.get("content_base64") or "")
        try:
            content = base64.b64decode(raw, validate=True)
        except Exception:
            raise ApiError(400, "Arquivo inválido.")
        if not content or len(content) > 5 * 1024 * 1024:
            raise ApiError(413, "O anexo deve ter no máximo 5 MB.")
        original = Path(str(data.get("filename") or "arquivo.bin")).name
        ext = Path(original).suffix.lower()
        allowed = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv", ".xlsx", ".docx"}
        if ext not in allowed:
            raise ApiError(400, "Tipo de arquivo não permitido.")
        profile_id = pid(actor)
        entity_type = str(data.get("entity_type") or "general").strip() or "general"
        entity_id = int(data.get("entity_id") or 0)
        if not has_perm(actor, "attachments.manage"):
            if entity_type != "custom_form_entry" or not entity_id or not (has_perm(actor, "forms.submit") or has_perm(actor, "forms.manage")):
                raise ApiError(403, "Sem permissão para enviar documentos.")
            with db_connect() as conn:
                entry = conn.execute("SELECT created_by FROM custom_form_entries WHERE id=? AND profile_id=?", (entity_id, profile_id)).fetchone()
            if not entry or (not has_perm(actor, "forms.manage") and int(entry["created_by"] or 0) != int(actor["id"])):
                raise ApiError(403, "Você não pode anexar arquivos a este envio.")
        stored = f"{profile_id}_{secrets.token_hex(16)}{ext}"
        path = ATTACH_DIR / stored
        path.write_bytes(content)
        sha = hashlib.sha256(content).hexdigest()
        ctype = mimetypes.guess_type(original)[0] or "application/octet-stream"
        with db_connect() as conn:
            cur = conn.execute(
                """INSERT INTO attachments(profile_id,entity_type,entity_id,original_name,stored_name,content_type,size_bytes,sha256,uploaded_by,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (profile_id, entity_type, entity_id, original, stored, ctype, len(content), sha, actor["id"], utc_now()),
            )
            attachment_id = int(cur.lastrowid)
        audit(actor["id"], "attachment.upload", "attachment", attachment_id, {"name": original, "sha256": sha, "profile_id": profile_id}, self.client_ip())
        self.send_json(201, {"ok": True, "id": attachment_id, "message": "Documento enviado."})

    def api_attachments(self: Any, user: dict[str, Any], query: dict[str, list[str]]) -> None:
        profile_id = pid(user)
        entity_type = str((query.get("entity_type") or [""])[0]).strip()
        entity_id = int((query.get("entity_id") or ["0"])[0] or 0)
        if not has_perm(user, "attachments.manage"):
            if entity_type != "custom_form_entry" or not entity_id or not (has_perm(user, "forms.manage") or has_perm(user, "forms.submit")):
                raise ApiError(403, "Sem permissão para visualizar documentos.")
        sql = """SELECT a.*,u.name AS uploaded_by_name FROM attachments a
                 LEFT JOIN users u ON u.id=a.uploaded_by WHERE a.profile_id=?"""
        params: list[Any] = [profile_id]
        if entity_type:
            sql += " AND a.entity_type=?"
            params.append(entity_type)
        if entity_id:
            sql += " AND a.entity_id=?"
            params.append(entity_id)
        with db_connect() as conn:
            rows = conn.execute(sql + " ORDER BY a.id DESC", params).fetchall()
        visible = [dict(row) for row in rows if attachment_access_allowed(user, row)]
        self.send_json(200, {"ok": True, "attachments": visible, "can_manage": has_perm(user, "attachments.manage")})

    def api_attachment_download(self: Any, user: dict[str, Any], attachment_id: int) -> None:
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM attachments WHERE id=? AND profile_id=?", (attachment_id, pid(user))).fetchone()
        if not row or not attachment_access_allowed(user, row):
            raise ApiError(404, "Anexo não encontrado.")
        path = ATTACH_DIR / row["stored_name"]
        if not path.is_file():
            raise ApiError(404, "Arquivo não encontrado no armazenamento.")
        data = path.read_bytes()
        safe_name = str(row["original_name"] or "arquivo").replace('"', "")
        self.send_response(200)
        self.send_header("Content-Type", row["content_type"])
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def api_attachment_delete(self: Any, actor: dict[str, Any], attachment_id: int) -> None:
        require_perm(actor, "attachments.manage")
        profile_id = pid(actor)
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM attachments WHERE id=? AND profile_id=?", (attachment_id, profile_id)).fetchone()
            if not row:
                raise ApiError(404, "Documento não encontrado.")
            conn.execute("DELETE FROM attachments WHERE id=? AND profile_id=?", (attachment_id, profile_id))
        path = ATTACH_DIR / row["stored_name"]
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
        audit(actor["id"], "attachment.delete", "attachment", attachment_id, {"profile_id": profile_id, "name": row["original_name"]}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Documento excluído."})

    def api_security_alerts(self: Any, user: dict[str, Any]) -> None:
        require_perm(user, "security.alerts")
        profile_id = pid(user)
        with db_connect() as conn:
            if user.get("is_platform_owner") or user.get("role_code") == "owner" or user.get("platform_role_code") == "owner":
                rows = conn.execute(
                    "SELECT * FROM security_alerts WHERE profile_id IS NULL OR profile_id=? ORDER BY resolved_at IS NULL DESC,created_at DESC LIMIT 200",
                    (profile_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM security_alerts WHERE profile_id=? ORDER BY resolved_at IS NULL DESC,created_at DESC LIMIT 200",
                    (profile_id,),
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["details"] = json.loads(d.pop("details_json") or "{}")
            out.append(d)
        self.send_json(200, {"ok": True, "alerts": out})

    def api_security_alert_update(self: Any, actor: dict[str, Any], alert_id: int) -> None:
        require_perm(actor, "security.alerts")
        data = self.read_json()
        resolved = bool(data.get("resolved", True))
        profile_id = pid(actor)
        with db_connect() as conn:
            if actor.get("is_platform_owner") or actor.get("role_code") == "owner" or actor.get("platform_role_code") == "owner":
                row = conn.execute("SELECT * FROM security_alerts WHERE id=? AND (profile_id IS NULL OR profile_id=?)", (alert_id, profile_id)).fetchone()
            else:
                row = conn.execute("SELECT * FROM security_alerts WHERE id=? AND profile_id=?", (alert_id, profile_id)).fetchone()
            if not row:
                raise ApiError(404, "Alerta não encontrado.")
            conn.execute("UPDATE security_alerts SET resolved_at=?,resolved_by=? WHERE id=?", (utc_now() if resolved else None, actor["id"] if resolved else None, alert_id))
        audit(actor["id"], "security_alert.resolve" if resolved else "security_alert.reopen", "security_alert", alert_id, {"profile_id": row["profile_id"]}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Alerta atualizado."})

    def api_dashboards(self:Any,user:dict[str,Any]) -> None:
        # Ler uma visão de dashboard é parte do próprio acesso à Dashboard.
        # A criação/edição continua restrita a reports.manage.
        require_perm(user,"dashboard.view")
        with db_connect() as conn:
            rows=conn.execute("SELECT * FROM dashboard_views WHERE profile_id=? AND (owner_user_id IS NULL OR owner_user_id=?) ORDER BY is_default DESC,name",(pid(user),user["id"])).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d["config"]=json.loads(d.pop("config_json") or "{}"); out.append(d)
        self.send_json(200,{"ok":True,"dashboards":out})

    def api_dashboard_save(self:Any,actor:dict[str,Any]) -> None:
        require_perm(actor,"reports.manage")
        data=self.read_json(); now=utc_now(); view_id=int(data.get("id") or 0); profile_id=pid(actor)
        config=data.get("config") or {}; name=str(data.get("name") or "Meu dashboard").strip()
        if len(name)<2: raise ApiError(400,"Informe um nome para a visão.")
        widgets=config.get("widgets") if isinstance(config,dict) else None
        allowed_widgets={"summary","tasks","notifications","automations","forms","security"}
        if not isinstance(widgets,list) or not widgets or any(widget not in allowed_widgets for widget in widgets):
            raise ApiError(400,"Escolha pelo menos um widget válido.")
        shared=bool(data.get("shared")); owner_user_id=None if shared else int(actor["id"]); is_default=1 if data.get("is_default") else 0
        with db_connect() as conn:
            if view_id:
                existing=conn.execute("SELECT id,owner_user_id FROM dashboard_views WHERE id=? AND profile_id=?",(view_id,profile_id)).fetchone()
                if not existing: raise ApiError(404,"Visão de dashboard não encontrada.")
                if existing["owner_user_id"] is not None and int(existing["owner_user_id"])!=int(actor["id"]) and not (actor.get("is_platform_owner") or actor.get("role_code") == "owner" or actor.get("platform_role_code") == "owner"):
                    raise ApiError(403,"Você não pode editar a visão pessoal de outro usuário.")
            if is_default:
                if owner_user_id is None:
                    conn.execute("UPDATE dashboard_views SET is_default=0,updated_at=? WHERE profile_id=? AND owner_user_id IS NULL AND id<>?",(now,profile_id,view_id or -1))
                else:
                    conn.execute("UPDATE dashboard_views SET is_default=0,updated_at=? WHERE profile_id=? AND owner_user_id=? AND id<>?",(now,profile_id,owner_user_id,view_id or -1))
            if view_id:
                conn.execute("UPDATE dashboard_views SET owner_user_id=?,name=?,config_json=?,is_default=?,updated_at=? WHERE id=? AND profile_id=?",(owner_user_id,name,json.dumps(config,ensure_ascii=False),is_default,now,view_id,profile_id))
            else:
                cur=conn.execute("INSERT INTO dashboard_views(profile_id,owner_user_id,name,config_json,is_default,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(profile_id,owner_user_id,name,json.dumps(config,ensure_ascii=False),is_default,actor["id"],now,now)); view_id=int(cur.lastrowid)
        audit(actor["id"],"dashboard.view.save","dashboard_view",view_id,{"name":name,"shared":shared,"is_default":bool(is_default)},self.client_ip())
        self.send_json(200,{"ok":True,"id":view_id})

    def api_dashboard_delete(self: Any, actor: dict[str, Any], view_id: int) -> None:
        require_perm(actor, "reports.manage")
        profile_id = pid(actor)
        with db_connect() as conn:
            row = conn.execute("SELECT * FROM dashboard_views WHERE id=? AND profile_id=?", (view_id, profile_id)).fetchone()
            if not row:
                raise ApiError(404, "Visão de dashboard não encontrada.")
            if row["owner_user_id"] is not None and int(row["owner_user_id"]) != int(actor["id"]) and not (actor.get("is_platform_owner") or actor.get("role_code") == "owner" or actor.get("platform_role_code") == "owner"):
                raise ApiError(403, "Você não pode excluir a visão pessoal de outro usuário.")
            conn.execute("DELETE FROM dashboard_views WHERE id=? AND profile_id=?", (view_id, profile_id))
        audit(actor["id"], "dashboard.view.delete", "dashboard_view", view_id, {"profile_id": profile_id, "name": row["name"]}, self.client_ip())
        self.send_json(200, {"ok": True, "message": "Visão excluída."})

    def api_backup_download(self: Any, actor: dict[str, Any], name: str) -> None:
        if not (actor.get("is_platform_owner") or actor.get("role_code") == "owner" or actor.get("platform_role_code") == "owner"):
            raise ApiError(403, "Somente o Dono da plataforma pode baixar backups.")
        safe_name = Path(name).name
        if safe_name != name or not re.fullmatch(r"[A-Za-z0-9_.-]+\.db", safe_name):
            raise ApiError(400, "Nome de backup inválido.")
        path = (BACKUP_DIR / safe_name).resolve()
        if BACKUP_DIR.resolve() not in path.parents or not path.is_file():
            raise ApiError(404, "Backup não encontrado.")
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_security_headers()
        self.end_headers()
        self.wfile.write(data)

    def route_get(self: Any) -> None:
        from urllib.parse import urlparse, parse_qs, unquote
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        if path == "/api/tasks": user,_,_=self.require_user(); return api_tasks_list(self,user)
        if path == "/api/notifications": user,_,_=self.require_user(); return api_notifications(self,user)
        if path == "/api/automations": user,_,_=self.require_user(); return api_automations(self,user)
        if path == "/api/custom-forms": user,_,_=self.require_user(); return api_forms(self,user)
        match = re.fullmatch(r"/api/custom-forms/(\d+)/entries", path)
        if match:
            user,_,_=self.require_user(); return api_form_entries(self,user,int(match.group(1)))
        if path == "/api/attachments": user,_,_=self.require_user(); return api_attachments(self,user,query)
        match = re.fullmatch(r"/api/attachments/(\d+)", path)
        if match:
            user,_,_=self.require_user(); return api_attachment_download(self,user,int(match.group(1)))
        if path == "/api/security-alerts": user,_,_=self.require_user(); return api_security_alerts(self,user)
        if path == "/api/custom-dashboards": user,_,_=self.require_user(); return api_dashboards(self,user)
        if path.startswith("/api/backups/"):
            user,_,_=self.require_user(); return api_backup_download(self,user,unquote(path[len("/api/backups/"):]))
        return original_route_get(self)

    def route_write(self: Any, method: str) -> None:
        from urllib.parse import urlparse
        path = urlparse(self.path).path.rstrip("/") or "/"
        if method == "POST" and path == "/api/password/request": self.check_request_origin(); return api_password_request(self)
        if method == "POST" and path == "/api/account/token-complete": self.check_request_origin(); return api_token_complete(self)
        if path.startswith("/api/") and path not in {"/api/login", "/api/setup"}:
            self.check_request_origin(); user,csrf,_=self.require_user(); self.check_csrf(csrf)
            if method == "POST" and path == "/api/invitations": return api_invite(self,user)
            if method == "POST" and path == "/api/tasks": return api_task_create(self,user)
            match = re.fullmatch(r"/api/tasks/(\d+)", path)
            if method == "PUT" and match: return api_task_update(self,user,int(match.group(1)))
            if method == "PUT" and path == "/api/notifications/read-all": return api_notifications_read_all(self,user)
            match = re.fullmatch(r"/api/notifications/(\d+)", path)
            if method == "PUT" and match: return api_notification_read(self,user,int(match.group(1)))
            if method == "POST" and path == "/api/automations": return api_automation_save(self,user)
            if method == "POST" and path == "/api/custom-forms": return api_form_save(self,user)
            match = re.fullmatch(r"/api/custom-forms/(\d+)/entries", path)
            if method == "POST" and match: return api_form_entry(self,user,int(match.group(1)))
            if method == "POST" and path == "/api/attachments": return api_attachment_upload(self,user)
            match = re.fullmatch(r"/api/attachments/(\d+)", path)
            if method == "DELETE" and match: return api_attachment_delete(self,user,int(match.group(1)))
            match = re.fullmatch(r"/api/security-alerts/(\d+)", path)
            if method == "PUT" and match: return api_security_alert_update(self,user,int(match.group(1)))
            if method == "POST" and path == "/api/custom-dashboards": return api_dashboard_save(self,user)
            match = re.fullmatch(r"/api/custom-dashboards/(\d+)", path)
            if method == "DELETE" and match: return api_dashboard_delete(self,user,int(match.group(1)))
        return original_route_write(self,method)

    Handler.route_get=route_get
    Handler.route_write=route_write
