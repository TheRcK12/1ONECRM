from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
VERSION = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))
DOCKER = (ROOT / "Dockerfile").read_text(encoding="utf-8")

assert VERSION["version"] == "2.6.6-beta.1"
assert "APP_VERSION = \"2.6.6-beta.1\"" in (ROOT / "one_crm_server.py").read_text(encoding="utf-8")
assert 'org.opencontainers.image.version="2.6.6-beta.1"' in DOCKER
assert "one_crm_productivity.py" in DOCKER

# A versão visual deve continuar servindo assets com cache busting.
assert "app.css?v=2.6.6" in INDEX
assert "app.js?v=2.6.6" in INDEX

# Navegação padronizada em ícones SVG e agrupada.
assert "const UI_ICON_PATHS" in APP
assert "function uiIcon" in APP
assert "{id:'insights-group',label:'Análises'" in APP
assert "{id:'platform-group',label:'Plataforma'" in APP
assert '<span class="top-nav-icon">${uiIcon(item.icon,15)}</span>' in APP

# Dashboard deixa de depender apenas de seis stat-cards iguais.
assert "dashboard-sales-summary" in APP
assert "dashboard-followup-list" in APP
assert "dashboard-conversion-track" in APP
assert "dashboardGreeting()" in APP
assert ".dashboard-overview" in CSS
assert ".dashboard-sales-summary" in CSS
assert ".dashboard-followup-row" in CSS

# O visual 2.6.4 deve remover os enfeites circulares dos stat-cards antigos.
assert ".stat-card:after{display:none}" in CSS

print("Visual refinement test: OK")
