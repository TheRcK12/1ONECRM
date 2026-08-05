from __future__ import annotations

import os
import pwd
import sys
from pathlib import Path

APP_USER = os.getenv("ONE_CRM_RUNTIME_USER", "onecrm")
APP_UID = int(os.getenv("ONE_CRM_RUNTIME_UID", "10001"))
APP_GID = int(os.getenv("ONE_CRM_RUNTIME_GID", "10001"))


def log(message: str) -> None:
    print(f"[railway-entrypoint] {message}", flush=True)


def target_directories() -> list[Path]:
    volume = (os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "").strip()
    data = (os.getenv("ONE_CRM_DATA_DIR") or volume or "/app/data").strip()
    log_dir = (os.getenv("ONE_CRM_LOG_DIR") or str(Path(data) / "logs")).strip()
    return [Path(data), Path(data) / "backups", Path(log_dir)]


def prepare_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.geteuid() != 0:
        return

    # Railway monta volumes como root. Corrigimos a propriedade antes de
    # abandonar privilégios, preservando os arquivos já existentes.
    for root, dirs, files in os.walk(path):
        root_path = Path(root)
        try:
            os.chown(root_path, APP_UID, APP_GID)
        except FileNotFoundError:
            continue
        for name in dirs:
            try:
                os.chown(root_path / name, APP_UID, APP_GID)
            except FileNotFoundError:
                pass
        for name in files:
            try:
                os.chown(root_path / name, APP_UID, APP_GID)
            except FileNotFoundError:
                pass


def drop_privileges() -> None:
    if os.geteuid() != 0:
        return
    try:
        pwd.getpwuid(APP_UID)
    except KeyError as exc:
        raise RuntimeError(f"Usuário de runtime UID {APP_UID} não existe na imagem.") from exc

    os.setgroups([])
    os.setgid(APP_GID)
    os.setuid(APP_UID)
    os.environ["HOME"] = f"/home/{APP_USER}"
    log(f"Processo executando sem privilégios como UID/GID {APP_UID}:{APP_GID}.")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Nenhum comando informado ao entrypoint.")

    for directory in target_directories():
        prepare_directory(directory)

    drop_privileges()
    command = sys.argv[1:]
    log("Iniciando: " + " ".join(command))
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
