from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from tkinter import Tk, filedialog, messagebox

from one_crm_server import BACKUP_DIR, DB_PATH, PID_PATH


def valid_sqlite(path):
    try:
        with sqlite3.connect(path) as conn:
            return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    except Exception:
        return False


def main():
    root = Tk(); root.withdraw()
    if PID_PATH.exists():
        messagebox.showerror("ONE CRM", "Feche o ONE CRM antes de restaurar um backup.\nUse PARAR_ONE_CRM.bat ou CTRL+C na janela do servidor.")
        return 1
    backup = filedialog.askopenfilename(title="Selecione um backup do ONE CRM", initialdir=str(BACKUP_DIR), filetypes=[("Banco SQLite", "*.db"), ("Todos", "*.*")])
    if not backup:
        return 0
    if not valid_sqlite(backup):
        messagebox.showerror("ONE CRM", "O arquivo escolhido não é um banco SQLite íntegro.")
        return 1
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        safety = BACKUP_DIR / f"one_crm_antes_restauracao_{datetime.now():%Y%m%d_%H%M%S}.db"
        shutil.copy2(DB_PATH, safety)
    shutil.copy2(backup, DB_PATH)
    messagebox.showinfo("ONE CRM", "Backup restaurado com sucesso.\nAgora execute INICIAR.bat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
