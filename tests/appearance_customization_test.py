from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
css = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
server = (ROOT / "one_crm_server.py").read_text(encoding="utf-8")
profiles = (ROOT / "one_crm_profiles.py").read_text(encoding="utf-8")
theme = (ROOT / "static" / "theme-init.js").read_text(encoding="utf-8")

assert "data-accent-choice" in app
assert "open-accent-studio" in app
assert "openAccentColorStudio" in app
assert 'type="color"' not in app
assert "data-background-choice" in app
assert "/api/me/appearance" in app
assert "accent_preference" in server
assert "background_preference" in server
assert "api_appearance_update" in server
assert "accent_preference" in profiles
assert "background_preference" in profiles
assert 'data-accent="emerald"' in css
assert 'data-accent="violet"' in css
assert 'data-background="obsidian"' in css
assert "--accent-glow" in css
assert "one-crm-accent" in theme
assert "one-crm-background" in theme
print("Appearance customization: OK")
