"""Prepare a key-free DSH profile and its real OS restart entry in a test guest."""
import argparse,json,os,subprocess,sys,traceback
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--modules',type=Path,required=True);p.add_argument('--home',type=Path,required=True);p.add_argument('--node',required=True);p.add_argument('--service-config',type=Path);p.add_argument('--model-url');p.add_argument('--session-id',default='system-test');a=p.parse_args()
a.home.mkdir(parents=True,exist_ok=True)
try:
    profile=a.home/'profiles/web';profile.mkdir(parents=True,exist_ok=True)
    (profile/'package.json').write_text(json.dumps({'private':True,'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'],'patchReload':'live'}}}),encoding='utf-8')
    for file in ['cordis.yml','cordis.patch.yml']:(profile/file).write_text('[]\n',encoding='utf-8')
    config={}
    if a.service_config:
        installed=json.loads(a.service_config.read_text(encoding='utf-8-sig'))
        config={'socketPath':'http://127.0.0.1:'+str(installed['port']),'backendToken':installed['token'],'stateDirectory':installed['data_dir'],'windowsTask':installed['task_name'],'windowsStarter':installed['starter_task']}
    import yaml
    plugin=Path.cwd()/'dsh-plugin/plugin.mjs'
    patch=[{'insert':[{'id':'focus-supervisor-chat','name':plugin.as_uri(),'config':config}]}]
    if a.model_url:
        patch += [{'id':'session-title-llm','disabled':True},
                  {'id':'llm-deepseek','config':{'apiKeyEnv':'DSH_TEST_KEY','baseURL':a.model_url,'thinking':'enabled','models':[{'id':'test-model','name':'Fixed test','inputModalities':['text','image'],'contextWindow':128000}]}},
                  {'id':'agent-default-model','config':{'provider':'deepseek-official','model':'test-model','reasoningEffort':'high'}},
                  {'insert':[{'name':(Path.cwd()/'test-support/fixtures/native-session.mjs').as_uri(),'config':{'sessionId':a.session_id,'cwd':str(Path.cwd())}}]}]
    (profile/'cordis.patch.yml').write_text(yaml.safe_dump(patch),encoding='utf-8')
    if not (profile/'node_modules').exists():
        if os.name=='nt':subprocess.run(['cmd','/c','mklink','/J',str(profile/'node_modules'),str(a.modules)],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else:(profile/'node_modules').symlink_to(a.modules)
    if os.name!='nt':
        os.environ['XDG_RUNTIME_DIR']='/run/user/'+str(os.getuid())
        os.environ['DBUS_SESSION_BUS_ADDRESS']='unix:path='+os.environ['XDG_RUNTIME_DIR']+'/bus'
    subprocess.run([sys.executable,'scripts/dsh-autostart.py','--modules',str(a.modules),'--home',str(a.home),'--node',a.node],check=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if a.model_url:
        if os.name=='nt':
            launcher=a.home/'start-dsh.ps1';launcher.write_text("$env:DSH_TEST_KEY='local-fixed-not-real'\n"+launcher.read_text(encoding='utf-8'),encoding='utf-8')
        else:
            unit=Path.home()/'.config/systemd/user/dsh-web.service'
            unit.write_text(unit.read_text()+"Environment=DSH_TEST_KEY=local-fixed-not-real\n")
            subprocess.run(['systemctl','--user','daemon-reload'],check=True)
    result={'code':0}
except Exception:result={'code':1,'stderr':traceback.format_exc()}
(a.home/'prepared.json').write_text(json.dumps(result),encoding='utf-8')
raise SystemExit(result['code'])
