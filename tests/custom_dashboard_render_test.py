from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
BACKEND = (ROOT / "one_crm_productivity.py").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

for required in (
    "dashboardViewBarHtml", "resolveDashboardView", "renderConfiguredDashboard",
    "dashboardTasksWidgetHtml", "dashboardNotificationsWidgetHtml",
    "dashboardAutomationsWidgetHtml", "dashboardFormsWidgetHtml", "dashboardSecurityWidgetHtml",
):
    assert required in APP, required

assert "Padrão do sistema" in APP
assert "dashboard-custom-hero" in APP
assert "require_perm(user,\"dashboard.view\")" in BACKEND
assert "entries_count" in BACKEND
assert ".dashboard-viewbar" in CSS
assert ".custom-dashboard-grid" in CSS
assert "/static/app.css?v=2.6.8" in INDEX
assert "/static/app.js?v=2.6.8" in INDEX
print("CUSTOM DASHBOARD RENDER TEST: OK")
