from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "static" / "app.css").read_text(encoding="utf-8")
LOGO = (ROOT / "static" / "one-crm-logo.svg").read_text(encoding="utf-8")
VERSION = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))

assert VERSION["version"] == "2.6.8-beta.1"
assert "--bg:#0d1117" in CSS
assert "--surface:#111821" in CSS
assert "--cyan:#6f95c9" in CSS
assert "--cyan-dark:#3f6f99" in CSS
assert "--green:#4eae76" in CSS
assert "--amber:#c99b45" in CSS
assert "--red:#d76772" in CSS
assert "#2CE9E8" not in LOGO
assert "#3978F6" not in LOGO
assert "#7A9BC4" in LOGO and "#496B96" in LOGO
print("Palette refinement test: OK")
