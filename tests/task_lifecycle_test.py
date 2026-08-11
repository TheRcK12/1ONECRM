from __future__ import annotations
import http.cookiejar, json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request
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
            with self.opener.open(req,timeout=15) as r:
                raw=r.read().decode(); payload=json.loads(raw or '{}'); assert r.status==expected,(path,r.status,payload)
        except urllib.error.HTTPError as e:
            payload=json.loads(e.read().decode() or '{}'); assert e.code==expected,(path,e.code,payload)
        if payload.get('csrf_token'): self.csrf=payload['csrf_token']
        return payload
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

def main():
    global BASE
    temp=Path(tempfile.mkdtemp(prefix='onecrm_task_lifecycle_')); port=free_port(); BASE=f'http://127.0.0.1:{port}'
    env=os.environ.copy(); env.update({'ONE_CRM_DATA_DIR':str(temp),'ONE_CRM_PORT':str(port),'ONE_CRM_NO_BROWSER':'1','ONE_CRM_REQUIRE_SETUP_TOKEN':'0','ONE_CRM_REQUIRE_PERSISTENT_STORAGE':'0'})
    proc=subprocess.Popen([sys.executable,str(ROOT/'one_crm_server.py')],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.STDOUT)
    try:
        wait(proc)
        owner=Client(); owner.request('/api/setup','POST',{'name':'Dono','email':'owner@tasks.local','password':'Owner1234'},201); owner_user=owner.refresh()
        worker_id=owner.request('/api/users','POST',{'name':'Funcionário','email':'worker@tasks.local','password':'Worker1234','role_code':'seller','must_change_password':False},201)['id']
        other_id=owner.request('/api/users','POST',{'name':'Outro Funcionário','email':'other@tasks.local','password':'Other1234','role_code':'seller','must_change_password':False},201)['id']
        task_id=owner.request('/api/tasks','POST',{'title':'Concluir relatório','description':'Fechar o relatório diário','assigned_user_id':worker_id,'priority':'high'},201)['id']
        owner.request('/api/tasks','POST',{'title':'Tarefa de outra pessoa','assigned_user_id':other_id,'priority':'normal'},201)

        worker=Client(); user=worker.login('worker@tasks.local','Worker1234')
        # Vendedor padrão não recebe tasks.view; ainda assim tarefas designadas precisam funcionar.
        assert 'tasks.view' not in set(user.get('permissions') or []), user.get('permissions')
        task_data=worker.request('/api/tasks')
        assert [t['id'] for t in task_data['tasks']]==[task_id], task_data
        assert task_data['can_manage'] is False

        worker.request(f'/api/tasks/{task_id}','PUT',{'status':'in_progress'},200)
        current=worker.request('/api/tasks')['tasks'][0]
        assert current['status']=='in_progress'

        # O responsável pode concluir, mas não reescrever dados administrativos.
        worker.request(f'/api/tasks/{task_id}','PUT',{'status':'done','title':'Título adulterado','priority':'urgent'},200)
        current=worker.request('/api/tasks')['tasks'][0]
        assert current['status']=='done' and current['completed_at']
        assert current['title']=='Concluir relatório', current
        assert current['priority']=='high', current

        # Concluída também pode ser reaberta pelo responsável.
        worker.request(f'/api/tasks/{task_id}','PUT',{'status':'pending'},200)
        assert worker.request('/api/tasks')['tasks'][0]['status']=='pending'
        # Responsável não pode cancelar.
        worker.request(f'/api/tasks/{task_id}','PUT',{'status':'cancelled'},403)

        # Dono/gestor consegue concluir/cancelar e recebe lista de destinatários mesmo sem depender da tela de usuários.
        owner_tasks=owner.request('/api/tasks')
        assert {u['id'] for u in owner_tasks['assignees']} >= {worker_id,other_id,int(owner_user['id'])}
        owner.request(f'/api/tasks/{task_id}','PUT',{'status':'done'},200)
        assert next(t for t in owner.request('/api/tasks')['tasks'] if t['id']==task_id)['status']=='done'

        # Contratante também precisa conseguir concluir uma tarefa designada no próprio perfil,
        # mesmo sem receber permissão administrativa de tarefas.
        contractor_id=owner.request('/api/users','POST',{'name':'Contratante','email':'contractor@tasks.local','password':'Contract1234','role_code':'seller','must_change_password':False},201)['id']
        contractor_profile=owner.request('/api/profiles','POST',{'name':'Perfil Contratante','business_type':'cash_control','contractor_user_id':contractor_id},201)['id']
        owner.request('/api/profiles/switch','POST',{'profile_id':contractor_profile},200); owner.refresh()
        contractor_task=owner.request('/api/tasks','POST',{'title':'Validar fechamento','assigned_user_id':contractor_id,'priority':'normal'},201)['id']
        contractor=Client(); contractor_user=contractor.login('contractor@tasks.local','Contract1234')
        assert contractor_user['is_contractor'] is True
        assert [t['id'] for t in contractor.request('/api/tasks')['tasks']]==[contractor_task]
        contractor.request(f'/api/tasks/{contractor_task}','PUT',{'status':'done'},200)
        assert contractor.request('/api/tasks')['tasks'][0]['status']=='done'
        print('TASK LIFECYCLE TEST: OK')
        return 0
    finally:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired: proc.kill()
        shutil.rmtree(temp,ignore_errors=True)

if __name__=='__main__': raise SystemExit(main())
