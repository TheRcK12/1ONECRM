from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
theme = (ROOT / "static" / "theme-init.js").read_text(encoding="utf-8")
server = (ROOT / "one_crm_server.py").read_text(encoding="utf-8")

assert "const DARK_BACKGROUND = 'obsidian';" in app
assert "data-background-choice" not in app
assert "Fundo do modo escuro" not in app
assert "background:DARK_BACKGROUND" in app
assert "document.documentElement.dataset.background = 'obsidian'" in theme
assert "localStorage.setItem('one-crm-background', 'obsidian')" in theme
assert 'html[data-theme="dark"][data-background="obsidian"]' in css
for old in ('data-background="graphite"', 'data-background="midnight"', 'data-background="forest"'):
    assert old not in css, f"Preset antigo de fundo ainda presente: {old}"
assert 'background = "obsidian"' in server
assert "UPDATE users SET background_preference='obsidian'" in server
print("Dark background Obsidian: OK")
assert 'obsidian' not in app.split("const LEGACY_ACCENTS = {", 1)[1].split("};", 1)[0].lower(), "Obsidiana não pode virar cor de destaque"
