from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
PROFILES = (ROOT / "one_crm_profiles.py").read_text(encoding="utf-8")

# A gestão de perfis precisa permanecer no Administrativo do Dono.
assert "const administrativeNavigationItems = [" in APP
admin = APP.split("const administrativeNavigationItems = [", 1)[1].split("];", 1)[0]
assert "{id:'profiles',label:'Perfis'" in admin
assert "{id:'platform-access',label:'Acessos da Plataforma'" in admin

# Não depender de uma única flag de sessão para reconhecer Dono.
owner_fn = APP.split("const isPlatformOwner = () => Boolean(", 1)[1].split(");", 1)[0]
for marker in (
    "state.user?.is_platform_owner",
    "state.user?.platform_role_code === 'owner'",
    "state.user?.role_code === 'owner'",
    "state.user?.base_role === 'owner'",
):
    assert marker in owner_fn

# O backend também aceita o Dono legado/base.
assert 'user.get("platform_role_code") == "owner" or user.get("role_code") == "owner"' in PROFILES
assert 'Somente o Dono da plataforma pode criar perfis.' in PROFILES

print("Profile navigation visibility: OK")
