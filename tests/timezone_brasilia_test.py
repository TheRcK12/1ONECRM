from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')

assert "const BRASILIA_TIME_ZONE = 'America/Sao_Paulo';" in APP_JS
assert "timeZone: BRASILIA_TIME_ZONE" in APP_JS
assert "String(value).replace('Z','')" not in APP_JS
assert "`${isoLike}Z`" in APP_JS

# Exemplo real do erro observado: 14:03 UTC deve aparecer 11:03 em Brasília.
utc_value = datetime(2026, 8, 6, 14, 3, 24, tzinfo=timezone.utc)
brasilia = utc_value.astimezone(ZoneInfo('America/Sao_Paulo'))
assert brasilia.strftime('%d/%m/%Y, %H:%M:%S') == '06/08/2026, 11:03:24'

# A conversão também deve corrigir a data quando cruza a meia-noite.
utc_value = datetime(2026, 8, 6, 1, 27, 50, tzinfo=timezone.utc)
brasilia = utc_value.astimezone(ZoneInfo('America/Sao_Paulo'))
assert brasilia.strftime('%d/%m/%Y, %H:%M:%S') == '05/08/2026, 22:27:50'

print('TIMEZONE BRASILIA TEST: OK')
