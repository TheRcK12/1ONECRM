from __future__ import annotations
import base64, http.cookiejar, json, os, shutil, socket, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=''

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); return s.getsockname()[1]

class Client:
    def __init__(self):
        self.jar=http.cookiejar.CookieJar(); self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar)); self.csrf=''
    def request(self,path,method='GET',data=None,expected=200):
        body=json.dumps(data).encode() if data is not None else None
        headers={'Accept':'application/json','Connection':'close'}
        if data is not None: headers['Content-Type']='application/json'
        if method!='GET' and self.csrf: headers['X-CSRF-Token']=self.csrf
        req=urllib.request.Request(BASE+path,data=body,method=method,headers=headers)
        try:
            with self.opener.open(req,timeout=20) as r:
                payload=json.loads(r.read().decode() or '{}'); assert r.status==expected,(path,r.status,payload)
        except urllib.error.HTTPError as e:
            payload=json.loads(e.read().decode() or '{}'); assert e.code==expected,(path,e.code,payload)
        if payload.get('csrf_token'): self.csrf=payload['csrf_token']
        return payload
    def download(self,path,expected=200):
        req=urllib.request.Request(BASE+path,method='GET',headers={'Connection':'close'})
        with self.opener.open(req,timeout=20) as r:
            data=r.read(); assert r.status==expected,(path,r.status); return data, dict(r.headers)
    def refresh(self):
        b=self.request('/api/bootstrap'); self.csrf=b['csrf_token']; return b['user']
    def login(self,email,password):
        self.request('/api/login','POST',{'email':email,'password':password}); return self.refresh()

def wait(proc):
    for _ in range(120):
        if proc.poll() is not None: raise RuntimeError('Servidor encerrou')
        try: urllib.request.urlopen(BASE+'/api/health',timeout=.4).close(); return
        except Exception: time.sleep(.08)
    raise RuntimeError('Servidor não iniciou')

def token_from_invite(url:str)->str:
    frag=urllib.parse.urlparse(url).fragment
    query=frag.split('?',1)[1] if '?' in frag else ''
    return urllib.parse.parse_qs(query)['token'][0]

def main():
    global BASE
    temp=Path(tempfile.mkdtemp(prefix='onecrm_complete_flows_')); port=free_port(); BASE=f'http://127.0.0.1:{port}'
    env=os.environ.copy(); env.update({'ONE_CRM_DATA_DIR':str(temp),'ONE_CRM_PORT':str(port),'ONE_CRM_NO_BROWSER':'1','ONE_CRM_REQUIRE_SETUP_TOKEN':'0','ONE_CRM_REQUIRE_PERSISTENT_STORAGE':'0'})
    proc=subprocess.Popen([sys.executable,str(ROOT/'one_crm_server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
    try:
        wait(proc)
        owner=Client(); owner.request('/api/setup','POST',{'name':'Dono','email':'owner@complete.local','password':'Owner1234'},201); owner_user=owner.refresh(); profile_id=int(owner_user['profile']['id'])

        # Cargo específico para preencher formulários, sem dar acesso administrativo.
        role=owner.request('/api/roles','POST',{
            'name':'Coletor de dados','code':'coletor_dados','base_role':'seller',
            'permissions':['dashboard.view','forms.view','forms.submit']
        },201)['code']

        # Convite precisa criar o vínculo ao perfil e permitir definição de senha pelo token.
        invite=owner.request('/api/invitations','POST',{'name':'Convidado','email':'invite@complete.local','role_code':role},201)
        assert invite['invite_url'], invite
        token=token_from_invite(invite['invite_url'])
        public=Client(); public.request('/api/account/token-complete','POST',{'token':token,'password':'Invite1234'},200)
        invited=Client(); invited_user=invited.login('invite@complete.local','Invite1234')
        assert int(invited_user['profile']['id'])==profile_id
        assert {'forms.view','forms.submit'} <= set(invited_user['permissions'])

        # Formulário realmente preenchível + envio consultável + anexo operacional.
        form_id=owner.request('/api/custom-forms','POST',{
            'name':'Checklist de visita','code':'checklist_visita','description':'Teste de fluxo completo','active':True,
            'schema':[
                {'key':'cliente','label':'Cliente','type':'text','required':True},
                {'key':'responsavel','label':'Responsável','type':'user','required':True},
                {'key':'comprovante','label':'Comprovante','type':'file','required':True},
            ]
        },200)['id']
        form_list=invited.request('/api/custom-forms')
        assert form_list['can_submit'] is True
        assert any(int(u['id'])==int(invited_user['id']) for u in form_list['user_options'])
        entry_id=invited.request(f'/api/custom-forms/{form_id}/entries','POST',{'data':{
            'cliente':'Cliente Teste','responsavel':invited_user['id'],'comprovante':'comprovante.txt'
        }},201)['id']
        payload=b'arquivo de teste do ONE CRM'
        upload=invited.request('/api/attachments','POST',{
            'filename':'comprovante.txt','entity_type':'custom_form_entry','entity_id':entry_id,
            'content_base64':base64.b64encode(payload).decode()
        },201)
        attachments=invited.request(f'/api/attachments?entity_type=custom_form_entry&entity_id={entry_id}')['attachments']
        assert {a['id'] for a in attachments}=={upload['id']}
        downloaded,_=invited.download(f"/api/attachments/{upload['id']}")
        assert downloaded==payload
        entries=owner.request(f'/api/custom-forms/{form_id}/entries')['entries']
        assert entries and entries[0]['data']['cliente']=='Cliente Teste'

        # Documentos gerais: enviar, baixar e excluir.
        doc_payload=b'documento geral'
        doc_id=owner.request('/api/attachments','POST',{
            'filename':'manual.txt','entity_type':'general','entity_id':0,
            'content_base64':base64.b64encode(doc_payload).decode()
        },201)['id']
        got,_=owner.download(f'/api/attachments/{doc_id}'); assert got==doc_payload
        owner.request(f'/api/attachments/{doc_id}','DELETE',{},200)
        owner.request(f'/api/attachments/{doc_id}',expected=404)

        # Dashboard personalizada também precisa poder ser removida.
        view_id=owner.request('/api/custom-dashboards','POST',{'name':'Teste','config':{'widgets':['summary','tasks']},'shared':False,'is_default':False},200)['id']
        assert any(v['id']==view_id for v in owner.request('/api/custom-dashboards')['dashboards'])
        owner.request(f'/api/custom-dashboards/{view_id}','DELETE',{},200)
        assert not any(v['id']==view_id for v in owner.request('/api/custom-dashboards')['dashboards'])

        # Backup manual agora é utilizável pela própria interface: criar e baixar.
        backup=owner.request('/api/backups','POST',{},201)
        backup_bytes,headers=owner.download('/api/backups/'+urllib.parse.quote(backup['name']))
        assert backup_bytes.startswith(b'SQLite format 3') and 'attachment' in headers.get('Content-Disposition','')

        # Tentativas inválidas devem persistir, bloquear e gerar alerta de segurança.
        attacker=Client()
        for _ in range(5):
            attacker.request('/api/login','POST',{'email':'naoexiste@complete.local','password':'Errada123'},401)
        with sqlite3.connect(temp/'one_crm.db') as conn:
            row=conn.execute("SELECT blocked_until FROM login_attempts WHERE identity LIKE '%|naoexiste@complete.local'").fetchone()
            assert row and row[0], row
            alert=conn.execute("SELECT id FROM security_alerts WHERE alert_type='auth.bruteforce' ORDER BY id DESC LIMIT 1").fetchone()
            assert alert
            alert_id=int(alert[0])
        alerts=owner.request('/api/security-alerts')['alerts']; assert any(a['id']==alert_id for a in alerts)
        owner.request(f'/api/security-alerts/{alert_id}','PUT',{'resolved':True},200)
        assert next(a for a in owner.request('/api/security-alerts')['alerts'] if a['id']==alert_id)['resolved_at']

        print('COMPLETED WORKFLOWS RUNTIME TEST: OK')
        return 0
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        shutil.rmtree(temp,ignore_errors=True)

if __name__=='__main__': raise SystemExit(main())
