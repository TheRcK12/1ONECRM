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
    audit = ns["audit"]
    original_init_database = ns["init_database"]
    original_route_get = Handler.route_get
    original_route_write = Handler.route_write

    extra_permissions = [
        ("tasks.view", "Produtividade", "Visualizar tarefas e notificações"),
        ("tasks.manage", "Produtividade", "Criar e administrar tarefas"),
        ("automations.manage", "Automação", "Criar regras automáticas"),
        ("forms.manage", "Personalização", "Criar formulários e campos personalizados"),
        ("attachments.manage", "Documentos", "Enviar e administrar anexos"),
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
        if permission not in set(user.get("permissions") or []):
            raise ApiError(403, "Seu cargo não possui permissão para esta ação.")

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

    def create_notification(profile_id: int, user_id: int, title: str, message: str, level: str="info", link: str="") -> None:
        with db_connect() as conn:
            conn.execute("INSERT INTO notifications(profile_id,user_id,title,message,level,link,created_at) VALUES(?,?,?,?,?,?,?)",
                         (profile_id,user_id,title,message,level,link,utc_now()))

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
                    now = utc_now()
                    with db_connect() as conn:
                        conn.execute("INSERT INTO tasks(profile_id,title,description,status,priority,due_at,assigned_user_id,created_by,related_type,related_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (profile_id,action.get("title") or rule["name"],action.get("description") or "",'pending',action.get("priority") or 'normal',action.get("due_at"),int(action["assigned_user_id"]),int(rule["created_by"]),context.get("entity_type"),context.get("entity_id"),now,now))
            with db_connect() as conn:
                conn.execute("UPDATE automation_rules SET last_run_at=? WHERE id=?", (utc_now(),rule["id"]))
            executed += 1
        return executed

    # ---------- endpoints ----------
    def api_invite(self: Any, actor: dict[str, Any]) -> None:
        require_perm(actor,"invitations.manage")
        data=self.read_json(); email=str(data.get("email") or "").strip().lower(); name=str(data.get("name") or "").strip()
        if "@" not in email or len(name)<2: raise ApiError(400,"Informe nome e e-mail válidos.")
        with db_connect() as conn:
            row=conn.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE",(email,)).fetchone()
            if row: user_id=int(row[0])
            else:
                temp=secrets.token_urlsafe(32)
                cur=conn.execute("INSERT INTO users(name,email,password_hash,role_code,active,must_change_password,created_at,updated_at,profile_id) VALUES(?,?,?,'seller',0,1,?,?,?)",
                                 (name,email,ns["hash_password"](temp),utc_now(),utc_now(),pid(actor)))
                user_id=int(cur.lastrowid)
        raw=create_account_token(email,"invite",user_id,actor["id"],48)
        link=f"{app_base_url(self)}/#/?token={raw}&action=accept-invite"
        sent,msg=send_email(email,"Convite para o ONE CRM",f"Você foi convidado para o ONE CRM.\n\nAbra: {link}\n\nO link expira em 48 horas.")
        audit(actor["id"],"user.invite","user",user_id,{"email":email,"email_sent":sent},self.client_ip())
        self.send_json(201,{"ok":True,"message":msg,"invite_url":link if not sent else "","email_sent":sent})

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

    def api_tasks_list(self: Any, user: dict[str,Any]) -> None:
        require_perm(user,"tasks.view"); profile_id=pid(user)
        with db_connect() as conn:
            if user.get("is_platform_owner") or "tasks.manage" in set(user.get("permissions") or []):
                rows=conn.execute("SELECT t.*,u.name assigned_name FROM tasks t LEFT JOIN users u ON u.id=t.assigned_user_id WHERE t.profile_id=? ORDER BY CASE t.status WHEN 'pending' THEN 0 ELSE 1 END,t.due_at,t.id DESC",(profile_id,)).fetchall()
            else:
                rows=conn.execute("SELECT t.*,u.name assigned_name FROM tasks t LEFT JOIN users u ON u.id=t.assigned_user_id WHERE t.profile_id=? AND t.assigned_user_id=? ORDER BY t.due_at,t.id DESC",(profile_id,user["id"])).fetchall()
        self.send_json(200,{"ok":True,"tasks":[public_task(r) for r in rows]})

    def api_task_create(self: Any, actor: dict[str,Any]) -> None:
        require_perm(actor,"tasks.manage"); data=self.read_json(); title=str(data.get("title") or "").strip()
        if len(title)<3: raise ApiError(400,"Informe o título da tarefa.")
        now=utc_now(); profile_id=pid(actor); assigned=int(data.get("assigned_user_id") or actor["id"])
        with db_connect() as conn:
            cur=conn.execute("INSERT INTO tasks(profile_id,title,description,status,priority,due_at,assigned_user_id,created_by,related_type,related_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (profile_id,title,str(data.get("description") or ""),"pending",str(data.get("priority") or "normal"),data.get("due_at") or None,assigned,actor["id"],data.get("related_type") or None,data.get("related_id") or None,now,now))
            task_id=int(cur.lastrowid)
        create_notification(profile_id,assigned,"Nova tarefa",title,"info","#/tasks")
        run_automations(profile_id,"task.created",{"entity_type":"task","entity_id":task_id,"priority":data.get("priority") or "normal"})
        audit(actor["id"],"task.create","task",task_id,{"title":title},self.client_ip())
        self.send_json(201,{"ok":True,"id":task_id})

    def api_task_update(self: Any, actor: dict[str,Any], task_id:int) -> None:
        data=self.read_json(); profile_id=pid(actor)
        with db_connect() as conn:
            row=conn.execute("SELECT * FROM tasks WHERE id=? AND profile_id=?",(task_id,profile_id)).fetchone()
            if not row: raise ApiError(404,"Tarefa não encontrada.")
            if int(row["assigned_user_id"] or 0)!=int(actor["id"]) and not (actor.get("is_platform_owner") or "tasks.manage" in set(actor.get("permissions") or [])):
                raise ApiError(403,"Sem permissão para alterar esta tarefa.")
            status=str(data.get("status") or row["status"]); completed=utc_now() if status=="done" else None
            conn.execute("UPDATE tasks SET title=?,description=?,status=?,priority=?,due_at=?,assigned_user_id=?,completed_at=?,updated_at=? WHERE id=?",
                (str(data.get("title") or row["title"]),str(data.get("description") if "description" in data else row["description"]),status,str(data.get("priority") or row["priority"]),data.get("due_at") if "due_at" in data else row["due_at"],int(data.get("assigned_user_id") or row["assigned_user_id"] or actor["id"]),completed,utc_now(),task_id))
        run_automations(profile_id,"task.updated",{"entity_type":"task","entity_id":task_id,"status":status})
        self.send_json(200,{"ok":True})

    def api_notifications(self: Any, user: dict[str,Any]) -> None:
        with db_connect() as conn: rows=conn.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 100",(user["id"],)).fetchall()
        self.send_json(200,{"ok":True,"notifications":[dict(r) for r in rows],"unread":sum(1 for r in rows if not r["read_at"])})

    def api_notification_read(self: Any,user:dict[str,Any],notification_id:int) -> None:
        with db_connect() as conn: conn.execute("UPDATE notifications SET read_at=? WHERE id=? AND user_id=?",(utc_now(),notification_id,user["id"]))
        self.send_json(200,{"ok":True})

    def api_automations(self: Any,user:dict[str,Any]) -> None:
        require_perm(user,"automations.manage")
        with db_connect() as conn: rows=conn.execute("SELECT * FROM automation_rules WHERE profile_id=? ORDER BY id DESC",(pid(user),)).fetchall()
        result=[]
        for r in rows:
            d=dict(r); d["conditions"]=json.loads(d.pop("conditions_json") or "{}"); d["actions"]=json.loads(d.pop("actions_json") or "[]"); result.append(d)
        self.send_json(200,{"ok":True,"rules":result})

    def api_automation_save(self: Any,actor:dict[str,Any]) -> None:
        require_perm(actor,"automations.manage"); data=self.read_json(); now=utc_now(); rule_id=int(data.get("id") or 0)
        payload=(str(data.get("name") or "Automação"),str(data.get("trigger_event") or "task.created"),json.dumps(data.get("conditions") or {},ensure_ascii=False),json.dumps(data.get("actions") or [],ensure_ascii=False),1 if data.get("active",True) else 0,now)
        with db_connect() as conn:
            if rule_id:
                conn.execute("UPDATE automation_rules SET name=?,trigger_event=?,conditions_json=?,actions_json=?,active=?,updated_at=? WHERE id=? AND profile_id=?",(*payload,rule_id,pid(actor)))
            else:
                cur=conn.execute("INSERT INTO automation_rules(profile_id,name,trigger_event,conditions_json,actions_json,active,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",(pid(actor),*payload[:-1],actor["id"],now,now)); rule_id=int(cur.lastrowid)
        self.send_json(200,{"ok":True,"id":rule_id})

    def api_forms(self: Any,user:dict[str,Any]) -> None:
        require_perm(user,"forms.manage")
        with db_connect() as conn: rows=conn.execute("SELECT * FROM custom_forms WHERE profile_id=? ORDER BY name",(pid(user),)).fetchall()
        out=[]
        for r in rows: d=dict(r); d["schema"]=json.loads(d.pop("schema_json") or "[]"); out.append(d)
        self.send_json(200,{"ok":True,"forms":out})

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

    def api_form_entry(self: Any,actor:dict[str,Any],form_id:int) -> None:
        data=self.read_json(); profile_id=pid(actor)
        with db_connect() as conn:
            form=conn.execute("SELECT * FROM custom_forms WHERE id=? AND profile_id=? AND active=1",(form_id,profile_id)).fetchone()
            if not form: raise ApiError(404,"Formulário não encontrado.")
            schema=json.loads(form["schema_json"] or "[]"); values=data.get("data") or {}
            for field in schema:
                if field.get("required") and values.get(field["key"]) in (None,"",[]): raise ApiError(400,f"O campo {field.get('label') or field['key']} é obrigatório.")
            now=utc_now(); cur=conn.execute("INSERT INTO custom_form_entries(profile_id,form_id,data_json,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?)",(profile_id,form_id,json.dumps(values,ensure_ascii=False),actor["id"],now,now)); entry_id=int(cur.lastrowid)
        run_automations(profile_id,"form.submitted",{"entity_type":"custom_form","entity_id":entry_id,"form_id":form_id})
        self.send_json(201,{"ok":True,"id":entry_id})

    ATTACH_DIR=DATA_DIR/"attachments"; ATTACH_DIR.mkdir(parents=True,exist_ok=True)
    def api_attachment_upload(self:Any,actor:dict[str,Any]) -> None:
        require_perm(actor,"attachments.manage"); data=self.read_json(); raw=str(data.get("content_base64") or "")
        try: content=base64.b64decode(raw,validate=True)
        except Exception: raise ApiError(400,"Arquivo inválido.")
        if not content or len(content)>5*1024*1024: raise ApiError(413,"O anexo deve ter no máximo 5 MB.")
        original=Path(str(data.get("filename") or "arquivo.bin")).name; ext=Path(original).suffix.lower()
        allowed={".pdf",".png",".jpg",".jpeg",".webp",".txt",".csv",".xlsx",".docx"}
        if ext not in allowed: raise ApiError(400,"Tipo de arquivo não permitido.")
        profile_id=pid(actor); stored=f"{profile_id}_{secrets.token_hex(16)}{ext}"; path=ATTACH_DIR/stored; path.write_bytes(content)
        sha=hashlib.sha256(content).hexdigest(); ctype=mimetypes.guess_type(original)[0] or "application/octet-stream"
        with db_connect() as conn:
            cur=conn.execute("INSERT INTO attachments(profile_id,entity_type,entity_id,original_name,stored_name,content_type,size_bytes,sha256,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(profile_id,str(data.get("entity_type") or "general"),int(data.get("entity_id") or 0),original,stored,ctype,len(content),sha,actor["id"],utc_now())); attachment_id=int(cur.lastrowid)
        audit(actor["id"],"attachment.upload","attachment",attachment_id,{"name":original,"sha256":sha},self.client_ip())
        self.send_json(201,{"ok":True,"id":attachment_id})

    def api_attachments(self:Any,user:dict[str,Any],query:dict[str,list[str]]) -> None:
        entity_type=(query.get("entity_type") or [""])[0]; entity_id=int((query.get("entity_id") or ["0"])[0] or 0)
        sql="SELECT * FROM attachments WHERE profile_id=?"; params=[pid(user)]
        if entity_type: sql+=" AND entity_type=?"; params.append(entity_type)
        if entity_id: sql+=" AND entity_id=?"; params.append(entity_id)
        with db_connect() as conn: rows=conn.execute(sql+" ORDER BY id DESC",params).fetchall()
        self.send_json(200,{"ok":True,"attachments":[dict(r) for r in rows]})

    def api_attachment_download(self:Any,user:dict[str,Any],attachment_id:int) -> None:
        with db_connect() as conn: row=conn.execute("SELECT * FROM attachments WHERE id=? AND profile_id=?",(attachment_id,pid(user))).fetchone()
        if not row: raise ApiError(404,"Anexo não encontrado.")
        path=ATTACH_DIR/row["stored_name"]
        if not path.is_file(): raise ApiError(404,"Arquivo não encontrado no armazenamento.")
        data=path.read_bytes(); self.send_response(200); self.send_header("Content-Type",row["content_type"]); self.send_header("Content-Disposition",f'attachment; filename="{row["original_name"].replace(chr(34),"")}"'); self.send_header("Content-Length",str(len(data))); self.send_security_headers(); self.end_headers(); self.wfile.write(data)

    def api_security_alerts(self:Any,user:dict[str,Any]) -> None:
        require_perm(user,"security.alerts")
        with db_connect() as conn: rows=conn.execute("SELECT * FROM security_alerts WHERE profile_id IS NULL OR profile_id=? ORDER BY created_at DESC LIMIT 200",(pid(user),)).fetchall()
        out=[]
        for r in rows: d=dict(r); d["details"]=json.loads(d.pop("details_json") or "{}"); out.append(d)
        self.send_json(200,{"ok":True,"alerts":out})

    def api_dashboards(self:Any,user:dict[str,Any]) -> None:
        require_perm(user,"reports.manage")
        with db_connect() as conn: rows=conn.execute("SELECT * FROM dashboard_views WHERE profile_id=? AND (owner_user_id IS NULL OR owner_user_id=?) ORDER BY is_default DESC,name",(pid(user),user["id"])).fetchall()
        out=[]
        for r in rows: d=dict(r); d["config"]=json.loads(d.pop("config_json") or "{}"); out.append(d)
        self.send_json(200,{"ok":True,"dashboards":out})

    def api_dashboard_save(self:Any,actor:dict[str,Any]) -> None:
        require_perm(actor,"reports.manage"); data=self.read_json(); now=utc_now(); view_id=int(data.get("id") or 0)
        config=data.get("config") or {}; name=str(data.get("name") or "Meu dashboard").strip()
        with db_connect() as conn:
            if view_id: conn.execute("UPDATE dashboard_views SET name=?,config_json=?,is_default=?,updated_at=? WHERE id=? AND profile_id=?",(name,json.dumps(config,ensure_ascii=False),1 if data.get("is_default") else 0,now,view_id,pid(actor)))
            else:
                cur=conn.execute("INSERT INTO dashboard_views(profile_id,owner_user_id,name,config_json,is_default,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",(pid(actor),None if data.get("shared") else actor["id"],name,json.dumps(config,ensure_ascii=False),1 if data.get("is_default") else 0,actor["id"],now,now)); view_id=int(cur.lastrowid)
        self.send_json(200,{"ok":True,"id":view_id})

    def route_get(self:Any) -> None:
        from urllib.parse import urlparse,parse_qs
        parsed=urlparse(self.path); path=parsed.path.rstrip("/") or "/"; query=parse_qs(parsed.query)
        if path=="/api/tasks": user,_,_=self.require_user(); return api_tasks_list(self,user)
        if path=="/api/notifications": user,_,_=self.require_user(); return api_notifications(self,user)
        if path=="/api/automations": user,_,_=self.require_user(); return api_automations(self,user)
        if path=="/api/custom-forms": user,_,_=self.require_user(); return api_forms(self,user)
        if path=="/api/attachments": user,_,_=self.require_user(); return api_attachments(self,user,query)
        if path.startswith("/api/attachments/"):
            user,_,_=self.require_user(); return api_attachment_download(self,user,int(path.rsplit("/",1)[1]))
        if path=="/api/security-alerts": user,_,_=self.require_user(); return api_security_alerts(self,user)
        if path=="/api/custom-dashboards": user,_,_=self.require_user(); return api_dashboards(self,user)
        return original_route_get(self)

    def route_write(self:Any,method:str) -> None:
        from urllib.parse import urlparse
        path=urlparse(self.path).path.rstrip("/") or "/"
        if method=="POST" and path=="/api/password/request": self.check_request_origin(); return api_password_request(self)
        if method=="POST" and path=="/api/account/token-complete": self.check_request_origin(); return api_token_complete(self)
        if path.startswith("/api/") and path not in {"/api/login","/api/setup"}:
            self.check_request_origin(); user,csrf,_=self.require_user(); self.check_csrf(csrf)
            if method=="POST" and path=="/api/invitations": return api_invite(self,user)
            if method=="POST" and path=="/api/tasks": return api_task_create(self,user)
            if method=="PUT" and path.startswith("/api/tasks/"): return api_task_update(self,user,int(path.rsplit("/",1)[1]))
            if method=="PUT" and path.startswith("/api/notifications/"): return api_notification_read(self,user,int(path.rsplit("/",1)[1]))
            if method=="POST" and path=="/api/automations": return api_automation_save(self,user)
            if method=="POST" and path=="/api/custom-forms": return api_form_save(self,user)
            if method=="POST" and re.fullmatch(r"/api/custom-forms/\d+/entries",path): return api_form_entry(self,user,int(path.split("/")[3]))
            if method=="POST" and path=="/api/attachments": return api_attachment_upload(self,user)
            if method=="POST" and path=="/api/custom-dashboards": return api_dashboard_save(self,user)
        return original_route_write(self,method)

    Handler.route_get=route_get
    Handler.route_write=route_write
