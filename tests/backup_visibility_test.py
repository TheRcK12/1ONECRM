from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
SERVER = (ROOT / "one_crm_server.py").read_text(encoding="utf-8")
VERSION = (ROOT / "version.json").read_text(encoding="utf-8")

assert "['profiles', 'platform-access', 'backups'].includes(route)" in APP_JS
assert "{id:'backups',label:'Backups',icon:'database',test:()=>isPlatformOwner()}" in APP_JS
assert "if (!isPlatformOwner()) return navigate('dashboard');" in APP_JS
assert 'self.require_platform_owner()' in SERVER
assert 'APP_VERSION = "2.7.0-beta.1"' in SERVER
assert '"version": "2.7.0-beta.1"' in VERSION

print("BACKUP VISIBILITY TEST: OK")
