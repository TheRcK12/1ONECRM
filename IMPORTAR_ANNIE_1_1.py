from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from tkinter import Tk, filedialog, messagebox, simpledialog

from one_crm_server import DB_PATH, BACKUP_DIR, hash_password, init_database, utc_now

BASE = Path(__file__).resolve().parent
PID = BASE / "server.pid"
ROLE_MAP = {
    "owner": "owner", "dono": "owner", "proprietario": "owner", "proprietário": "owner",
    "gerente": "manager", "manager": "manager", "bko": "bko", "backoffice": "bko",
    "back-office": "bko", "vendedor": "seller", "seller": "seller",
}


def normalize_date(value):
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def code_like(value, mapping, default):
    text = str(value or "").strip().lower()
    for needle, code in mapping:
        if needle in text:
            return code
    return default


def main() -> int:
    root = Tk(); root.withdraw()
    if PID.exists():
        messagebox.showerror("ONE CRM", "Feche o ONE CRM antes da importação.")
        return 1
    init_database()
    with sqlite3.connect(DB_PATH) as current:
        if current.execute("SELECT COUNT(*) FROM users WHERE role_code='owner' AND active=1").fetchone()[0] == 0:
            messagebox.showerror("ONE CRM", "Inicie o ONE CRM e crie o primeiro Dono antes de importar.")
            return 1
    legacy_path = filedialog.askopenfilename(
        title="Selecione o banco do ANNIE 1.1 (aanie.db)",
        filetypes=[("Banco SQLite", "*.db"), ("Todos os arquivos", "*.*")],
    )
    if not legacy_path:
        return 0
    temporary_password = simpledialog.askstring(
        "Senha temporária",
        "Defina a senha temporária para os usuários importados.\nEles serão obrigados a trocá-la no primeiro acesso.",
        show="*",
    )
    if not temporary_password or len(temporary_password) < 8 or not any(c.isdigit() for c in temporary_password):
        messagebox.showerror("ONE CRM", "A senha precisa ter ao menos 8 caracteres e um número.")
        return 1

    legacy = sqlite3.connect(legacy_path); legacy.row_factory = sqlite3.Row
    required = {r[0] for r in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"users", "sales", "teams"}.issubset(required):
        messagebox.showerror("ONE CRM", "O arquivo selecionado não parece ser um banco do ANNIE 1.1.")
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup = BACKUP_DIR / f"one_crm_antes_importacao_{datetime.now():%Y%m%d_%H%M%S}.db"
    if DB_PATH.exists(): shutil.copy2(DB_PATH, backup)

    current = sqlite3.connect(DB_PATH); current.row_factory = sqlite3.Row
    now = utc_now(); team_map = {}; user_map = {}; imported = {"teams":0,"users":0,"sales":0,"skipped_sales":0}
    try:
        current.execute("BEGIN")
        # Equipes
        for row in legacy.execute("SELECT * FROM teams ORDER BY id"):
            existing = current.execute("SELECT id FROM teams WHERE name=? COLLATE NOCASE", (row["nome"],)).fetchone()
            if existing:
                new_id = existing[0]
            else:
                cur = current.execute(
                    "INSERT INTO teams(name,monthly_target,active,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (row["nome"], int(row["meta_mensal"] or 0), int(row["ativo"] or 0), now, now),
                )
                new_id = cur.lastrowid; imported["teams"] += 1
            team_map[row["id"]] = new_id

        owner_id = current.execute("SELECT id FROM users WHERE role_code='owner' AND active=1 ORDER BY id LIMIT 1").fetchone()[0]
        # Usuários
        for row in legacy.execute("SELECT * FROM users ORDER BY id"):
            email = str(row["email"] or f"legado_{row['id']}@annie.local").strip().lower()
            existing = current.execute("SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)).fetchone()
            if existing:
                new_id = existing[0]
            else:
                role = ROLE_MAP.get(str(row["perfil"] or "").strip().lower(), "seller")
                cur = current.execute(
                    """INSERT INTO users(name,email,password_hash,role_code,team_id,active,must_change_password,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,1,?,?)""",
                    (row["nome"] or f"Usuário legado {row['id']}", email, hash_password(temporary_password), role,
                     team_map.get(row["time_id"]), int(row["ativo"] or 0), now, now),
                )
                new_id = cur.lastrowid; imported["users"] += 1
            user_map[row["id"]] = new_id

        # Gerentes das equipes
        for row in legacy.execute("SELECT id,gerente_id FROM teams"):
            if row["gerente_id"] and row["gerente_id"] in user_map:
                current.execute("UPDATE teams SET manager_id=? WHERE id=?", (user_map[row["gerente_id"]], team_map[row["id"]]))

        # Vendas
        for row in legacy.execute("SELECT * FROM sales ORDER BY id"):
            phone = "".join(c for c in str(row["telefone"] or "") if c.isdigit())
            created = str(row["created_at"] or now).replace(" ", "T")
            if not created.endswith("Z"): created += "Z"
            duplicate = current.execute(
                "SELECT id FROM sales WHERE phone=? AND client_name=? AND substr(created_at,1,10)=?",
                (phone, row["cliente_nome"], created[:10]),
            ).fetchone()
            if duplicate:
                imported["skipped_sales"] += 1
                continue
            plan_name = row["plano"] or "Plano legado"
            plan = current.execute("SELECT id FROM plans WHERE name=? COLLATE NOCASE", (plan_name,)).fetchone()
            if plan:
                plan_id = plan[0]
            else:
                cur = current.execute(
                    """INSERT INTO plans(provider,service,name,speed,price,benefits,sort_order,active,created_at,updated_at)
                    VALUES('LEGADO','Fibra',?,?,?,?,999,1,?,?)""",
                    (plan_name, row["velocidade"], float(row["plano_valor"] or 0), row["beneficios"], now, now),
                )
                plan_id = cur.lastrowid
            status = code_like(row["status"], [("cancel", "cancelada"),("instalad", "instalada"),("trat", "em_tratamento")], "nova")
            activation = code_like(row["ativacao_status"], [("pinga", "ativado_pinga"),("trash", "ativado_trash"),("ativad", "ativado_pinga"),("não", "nao_ativado"),("nao", "nao_ativado")], "aguardando_ativacao")
            biometric = code_like(row["biometria_status"], [("ok", "biometria_ok"),("bko", "biometria_bko"),("retorno", "retorno_biometria"),("prometeu", "prometeu_biometria"),("sem", "nao_cadastrado")], "biometria_pendente")
            installation = code_like(row["instalacao_status"], [("regra", "instalado_regra_pdv"),("instalad", "instalado"),("não", "nao_instalado"),("nao", "nao_instalado"),("reagend", "solicitar_reagendamento")], "aguardando_instalacao")
            seller_id = user_map.get(row["vendedor_id"], owner_id)
            team_id = team_map.get(row["time_id"])
            if not team_id:
                seller_team = current.execute("SELECT team_id FROM users WHERE id=?", (seller_id,)).fetchone()
                team_id = seller_team[0] if seller_team else None
            notes = row["observacoes"] or ""
            if row["referencia"]: notes = (notes + "\nReferência: " + row["referencia"]).strip()
            cur = current.execute(
                """INSERT INTO sales(person_type,client_name,cpf_cnpj,birth_date,mother_name,phone,contact_phone,email,
                cep,address,address_number,complement,neighborhood,city,uf,plan_id,plan_name_snapshot,plan_price_snapshot,
                provider,service,due_day,channel,notes,seller_id,team_id,status,activation_status,biometric_status,
                installation_status,appointment_date,os_number,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row["tipo_pessoa"] or "CPF", row["cliente_nome"], row["cpf"], normalize_date(row["data_nascimento"]),
                 row["nome_mae"], phone, row["telefone_contato"], row["email"], row["cep"], row["endereco"],
                 row["numero"], row["complemento"], row["bairro"], row["cidade"], row["uf"], plan_id, plan_name,
                 float(row["plano_valor"] or 0), "LEGADO", "Fibra", row["vencimento"], row["origem"], notes,
                 seller_id, team_id, status, activation, biometric, installation, normalize_date(row["data_instalacao"]),
                 row["os"], created, now),
            )
            sale_id = cur.lastrowid
            current.execute(
                "INSERT INTO sale_history(sale_id,user_id,event_type,details,created_at) VALUES(?,?,'imported',?,?)",
                (sale_id, owner_id, f"Importada do ANNIE 1.1 · ID legado {row['id']}", now),
            )
            imported["sales"] += 1
        current.execute(
            "INSERT INTO audit_logs(user_id,action,entity_type,details,created_at) VALUES(?, 'legacy.import', 'system', ?, ?)",
            (owner_id, str(imported), now),
        )
        current.commit()
    except Exception:
        current.rollback()
        raise
    finally:
        current.close(); legacy.close()

    messagebox.showinfo(
        "Importação concluída",
        f"Equipes: {imported['teams']}\nUsuários: {imported['users']}\nVendas: {imported['sales']}\nVendas já existentes: {imported['skipped_sales']}\n\nSenha temporária definida para usuários importados.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
