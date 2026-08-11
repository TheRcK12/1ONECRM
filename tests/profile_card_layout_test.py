from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")

# A grade de perfis de negócio não pode reutilizar a grade do perfil pessoal.
assert '<div class="business-profile-grid">' in APP
assert '<div class="profile-grid">' in APP  # Meu perfil continua usando seu layout próprio.
assert '.business-profile-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr))' in CSS
assert '@media(max-width:1500px){.business-profile-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}' in CSS
assert '@media(max-width:1080px){.business-profile-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}' in CSS
assert '@media(max-width:680px){.business-profile-grid{grid-template-columns:1fr}' in CSS

# Cards mantêm ações alinhadas no rodapé e não apagam o conteúdo inteiro quando bloqueados.
assert 'class="business-profile-actions"' in APP
assert "class=\"business-profile-card ${profile.active?'':'is-blocked'}\"" in APP
assert '.business-profile-card.is-blocked{' in CSS
assert '.profile-card.inactive{opacity:.62}' not in CSS
assert "data-profile-enter=\"${profile.id}\" ${profile.active?'':'disabled title=\"Ative o perfil para entrar.\"'}" in APP

print("Profile card layout test: OK")
