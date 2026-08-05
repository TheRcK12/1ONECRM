from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = os.environ.get("PYTHON", "python")


def run_server(env_updates: dict[str, str], timeout: float = 12.0) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in [
        "RAILWAY_VOLUME_MOUNT_PATH",
        "ONE_CRM_DATA_DIR",
        "ONE_CRM_SETUP_TOKEN",
        "ONE_CRM_ALLOW_EPHEMERAL_STORAGE",
    ]:
        env.pop(key, None)
    env.update(
        {
            "RAILWAY_ENVIRONMENT": "production",
            "RAILWAY_PROJECT_ID": "production-test",
            "PORT": "18965",
            "ONE_CRM_SECURE_COOKIES": "1",
            "ONE_CRM_TRUST_PROXY_HEADERS": "1",
            "ONE_CRM_NO_BROWSER": "1",
        }
    )
    env.update(env_updates)
    return subprocess.run(
        [PYTHON, "one_crm_server.py"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main() -> None:
    railway = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    assert railway["build"]["builder"] == "DOCKERFILE"
    assert railway["deploy"]["startCommand"] is None
    assert railway["deploy"]["healthcheckPath"] == "/api/health"
    assert railway["deploy"]["drainingSeconds"] >= 10

    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'ENTRYPOINT ["python", "/app/railway_entrypoint.py"]' in dockerfile
    assert 'CMD ["python", "/app/one_crm_server.py"]' in dockerfile
    assert "python -m compileall" in dockerfile

    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "theme-init.js" in index
    assert "<script>" not in index
    assert (ROOT / "static" / "theme-init.js").is_file()

    # Produção sem Volume deve recusar inicialização, evitando banco descartável.
    with tempfile.TemporaryDirectory(prefix="onecrm-ephemeral-") as temp_dir:
        result = run_server(
            {
                "ONE_CRM_DATA_DIR": temp_dir,
                "ONE_CRM_SETUP_TOKEN": "token-de-producao-abcdefghijklmnopqrstuvwxyz-123456789",
            }
        )
        assert result.returncode != 0
        assert "Nenhum Volume Railway foi detectado" in (result.stdout + result.stderr)

    # Primeiro acesso sem token forte também deve ser recusado.
    with tempfile.TemporaryDirectory(prefix="onecrm-volume-") as volume_dir:
        result = run_server({"RAILWAY_VOLUME_MOUNT_PATH": volume_dir})
        assert result.returncode != 0
        assert "ONE_CRM_SETUP_TOKEN" in (result.stdout + result.stderr)

    print("RAILWAY PRODUCTION TEST: OK")
    print("Docker, Volume obrigatório, token inicial e configuração de deploy foram validados.")


if __name__ == "__main__":
    main()
