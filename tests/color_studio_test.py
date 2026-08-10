from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
app = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
css = (ROOT / 'static' / 'app.css').read_text(encoding='utf-8')
assert 'type="color"' not in app, 'Seletor nativo de cor ainda presente no app.js'
for token in ['openAccentColorStudio', 'color-sv-board', 'color-hue-track', 'color-hex-input', 'apply-accent-studio']:
    assert token in app, f'Elemento do editor ausente: {token}'
for token in ['.color-studio', '.color-sv-board', '.color-hue-track', '.color-quick-list']:
    assert token in css, f'Estilo do editor ausente: {token}'
print('Color Studio Test: OK')
