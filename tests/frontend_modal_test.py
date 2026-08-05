from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')

assert 'onclick=' not in APP_JS, 'Ainda existem manipuladores inline incompatíveis com CSP.'
assert '<div class="modal-backdrop">' in APP_JS, 'O backdrop do modal não está no formato seguro.'
assert '<div class="modal-backdrop" data-close-modal>' not in APP_JS, 'O backdrop não pode usar data-close-modal.'
assert 'if (event.target === backdrop) closeModal();' in APP_JS, 'O modal precisa fechar somente no clique direto do fundo.'
assert "bindOverlayClose('.modal-backdrop')" in APP_JS
assert "bindOverlayClose('.drawer-backdrop')" in APP_JS
assert "$$('[data-close-modal]', root)" in APP_JS
assert '[data-route],[data-render-route],[data-sale-detail]' in APP_JS, 'Ações dinâmicas precisam usar delegação compatível com CSP.'

print('FRONTEND MODAL/CSP TEST: OK')
