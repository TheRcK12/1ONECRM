from __future__ import annotations
import os, sqlite3, subprocess, sys, tempfile, time, urllib.request, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as td:
    env=os.environ.copy(); env.update({'ONE_CRM_DATA_DIR':td,'ONE_CRM_NO_BROWSER':'1','ONE_CRM_PORT':'18991','ONE_CRM_REQUIRE_SETUP_TOKEN':'0','ONE_CRM_REQUIRE_PERSISTENT_STORAGE':'0'})
    proc=subprocess.Popen([sys.executable,str(ROOT/'one_crm_server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18991/api/health',timeout=.5) as r:
                    assert r.status==200; break
            except Exception: time.sleep(.1)
        else: raise AssertionError('Servidor não iniciou')
        db=Path(td)/'one_crm.db'; assert db.exists()
        with sqlite3.connect(db) as conn:
            tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required={'account_tokens','tasks','notifications','automation_rules','custom_forms','custom_form_entries','attachments','dashboard_views','security_alerts'}
        assert required <= tables, required-tables
        with urllib.request.urlopen('http://127.0.0.1:18991/api/bootstrap') as r:
            payload=json.load(r); assert payload['version']=='2.6.7-beta.1'
        print('PRODUCTIVITY SUITE TEST: OK')
    finally:
        proc.terminate(); proc.wait(timeout=10)
