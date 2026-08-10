from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
DOCKER = (ROOT / "Dockerfile").read_text(encoding="utf-8")

# Nenhum construtor novo pode exigir JSON manual do usuário.
for forbidden in ("Condições (JSON)", "Ações (JSON)", "Campos (JSON)", "Configuração dos widgets (JSON)"):
    assert forbidden not in APP, f"UX ainda expõe configuração técnica: {forbidden}"

assert "automationConditionEditor" in APP
assert "automationActionCard" in APP
assert "customFieldCard" in APP
assert "widget-picker" in APP
assert "work-center-hero" in APP
assert "profile-select-control" in APP
assert ".work-metrics" in CSS
assert ".builder-form" in CSS
assert ".profile-select-control" in CSS
assert "/static/app.css?v=2.6.7" in INDEX
assert "/static/app.js?v=2.6.7" in INDEX
assert "one_crm_productivity.py" in DOCKER
assert 'org.opencontainers.image.version="2.6.7-beta.1"' in DOCKER

print("PRODUCTIVITY UX TEST: OK")
