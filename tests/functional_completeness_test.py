from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / 'static' / 'app.js').read_text(encoding='utf-8')
SERVER = (ROOT / 'one_crm_server.py').read_text(encoding='utf-8')
PROFILES = (ROOT / 'one_crm_profiles.py').read_text(encoding='utf-8')
PRODUCTIVITY = (ROOT / 'one_crm_productivity.py').read_text(encoding='utf-8')
INDEX = (ROOT / 'static' / 'index.html').read_text(encoding='utf-8')

checks = {
    'task lifecycle UI': all(token in APP for token in ['data-task-status', 'data-next-status="done"', 'data-next-status="in_progress"', 'data-next-status="pending"']),
    'task lifecycle backend': all(token in PRODUCTIVITY for token in ['"in_progress"', '"done"', '"cancelled"', 'is_assignee']),
    'assigned tasks universal': 'Qualquer integrante ativo do perfil pode consultar as próprias tarefas' in PRODUCTIVITY,
    'notification completion': '/api/notifications/read-all' in APP and 'api_notifications_read_all' in PRODUCTIVITY,
    'custom form submission': 'openCustomFormEntryForm' in APP and 'api_form_entry' in PRODUCTIVITY,
    'custom form entries': 'openCustomFormEntries' in APP and 'api_form_entries' in PRODUCTIVITY,
    'documents screen': 'async function renderDocuments' in APP and "documents: renderDocuments" in APP,
    'document delete': "method:'DELETE'" in APP and 'api_attachment_delete' in PRODUCTIVITY,
    'invite token UI': 'openAccountTokenCompletion' in APP and '/api/account/token-complete' in APP,
    'invite profile membership': 'INSERT INTO profile_users' in PRODUCTIVITY and 'Cargo inválido para o perfil atual.' in PRODUCTIVITY,
    'backup download': 'data-backup-download' in APP and 'api_backup_download' in PRODUCTIVITY,
    'security alert resolve': 'data-security-alert' in APP and 'api_security_alert_update' in PRODUCTIVITY,
    'dashboard delete': 'delete-dashboard-view' in APP and 'api_dashboard_delete' in PRODUCTIVITY,
    'generic dashboard permissions': 'can_view_record_module(user, module)' in PROFILES,
    'generic record assignees': '"assignees": assignees' in PROFILES and 'profileRecordAssignees' in APP,
    'cash manager can read': 'has_permission(user, "cash.view") or has_permission(user, "cash.manage")' in PROFILES,
    'user manager can read list': 'has_permission(actor, "users.view") or has_permission(actor, "users.manage")' in PROFILES,
    'team manager candidates': '"manager_candidates": manager_candidates' in PROFILES and 'teamManagerCandidates' in APP,
    'generic/cash global search': "profileModules.has('cash')" in APP and '/api/profile-records?' in APP,
    'unsupported evolution labelled': "badge('Não homologada','amber')" in APP,
    'http delete support': 'def do_DELETE(self)' in SERVER,
    'body supports 5MB base64': 'MAX_BODY = 8 * 1024 * 1024' in SERVER,
    'failed login commit fix': 'o erro é levantado somente depois' in SERVER.lower(),
    'asset cache version': 'v=2.7.0' in INDEX,
}

failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise AssertionError('Fluxos incompletos: ' + ', '.join(failed))
print('FUNCTIONAL COMPLETENESS TEST: OK')
