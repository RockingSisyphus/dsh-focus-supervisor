"""External client of the installed product service; no in-process Supervisor."""
import http.client,json,os,socket,subprocess,sys,time
from pathlib import Path
from support import *
from dsh_test_harness.wait import until
from dsh_test_harness.desktop import Desktop
ROOT=Path(__file__).resolve().parents[2]

class ReadStore:
    def __init__(self,backend):self.backend=backend
    def read(self,kind,identifier=None):
        request={'path':str(self.backend.directory/'events.sqlite3'),'kind':kind,'id':identifier}
        argv=[sys.executable,str(ROOT/'test-support/dsh_test_harness/read_store.py')]
        if os.name!='nt':argv=['sudo',*argv]
        result=subprocess.run(argv,input=json.dumps(request),capture_output=True,text=True,encoding='utf-8',check=True)
        return json.loads(result.stdout)
    def all(self,kind):return self.read(kind)
    def get(self,kind,identifier):return self.read(kind,identifier)

class ObservedCore:
    def __init__(self,backend):self.backend=backend;self.store=ReadStore(backend)
    def settings(self):return self.backend.settings()
    def state(self):return self.backend.state()
    def capture(self):
        # Wait for the service's own sampler; never replace its samples.
        time.sleep(self.backend.state().get('sample',2));return None
    def report_tool(self,request):return self.backend.request('/report',request)

class Backend:
    def __init__(self,directory,definition=None):
        self.out=Path(directory).parent;self.errors=[];self.notification_processes={};self.last_notification_pid=None
        self.definition=definition or {}
        if os.name=='nt':
            config_path=Path(os.environ.get('DSH_TEST_SERVICE_CONFIG',str(Path(os.environ['PROGRAMDATA'])/'Dafeiyu/config.json')))
            self.config=json.loads(config_path.read_text(encoding='utf-8-sig')) if config_path.exists() else {'data_dir':str(config_path.parent/'data'),'port':18769,'token':'','task_name':'Dafeiyu-Supervisor','starter_task':'Dafeiyu-Supervisor-Start'}
            self.config_path=config_path
            self.directory=Path(self.config['data_dir']);self.socket='http://127.0.0.1:'+str(self.config['port']);self.token=self.config['token']
        else:
            path=Path('/etc/dafeiyu/config.json')
            self.config=json.loads(path.read_text()) if path.exists() else {'data_dir':'/var/lib/dafeiyu','socket':'/run/dafeiyu/agent.sock'}
            self.directory=Path(self.config['data_dir']);self.socket=self.config['socket'];self.token=''
        self.core=ObservedCore(self)
        self.original_tasks={t['id'] for t in self.state().get('live',[])}
        self.original_settings=self.settings()
        (self.out/'cleanup-state.json').write_text(json.dumps({'original_tasks':list(self.original_tasks),'original_settings':self.original_settings}),encoding='utf-8')
    def track_notification(self,pid):
        import psutil
        self.last_notification_pid=pid
        try:self.notification_processes[pid]=psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:pass
    def desktop_windows(self):
        from dsh_test_harness.entities import Entities
        return Entities(None).snapshot()['windows']
    @property
    def plugin_config(self):
        if os.name=='nt' and not self.config_path.exists():return {}
        result={'socketPath':self.socket,'backendToken':self.token,'stateDirectory':str(self.directory)}
        if os.name=='nt':result.update(windowsTask=self.config['task_name'],windowsStarter=self.config.get('starter_task',''))
        return result
    def settings(self):
        p=self.directory/'settings.json'
        return json.loads(p.read_text(encoding='utf-8')) if p.exists() else json.loads((ROOT/'dsh-plugin/default-prompts.json').read_text(encoding='utf-8'))
    def state(self):
        try:
            result=self.request('/state',{})
            self.state_observation={'source':'service','observed_at':time.time()}
            return result
        except (OSError,ConnectionError) as error:
            self.state_observation={'source':'persisted-status','observed_at':time.time(),'error':str(error)}
            p=self.directory/'status.json'
            if p.exists():return json.loads(p.read_text(encoding='utf-8'))
            return {'live':[],'tasks':[],'reports':[],'alerts':[]}
    def request(self,route,payload):
        # Fresh installation creates the real endpoint/token after this observer
        # was constructed. Read that configuration before talking to the service.
        if os.name=='nt' and self.config_path.exists():
            self.config=json.loads(self.config_path.read_text(encoding='utf-8-sig'))
            self.directory=Path(self.config['data_dir'])
            self.socket='http://127.0.0.1:'+str(self.config['port'])
            self.token=self.config['token']
        if self.socket.startswith('http:'):conn=http.client.HTTPConnection('127.0.0.1',int(self.socket.rsplit(':',1)[1]),timeout=40)
        else:
            path=self.socket
            class Unix(http.client.HTTPConnection):
                def connect(self):self.sock=socket.socket(socket.AF_UNIX);self.sock.settimeout(40);self.sock.connect(path)
            conn=Unix('localhost')
        try:
            conn.request('POST',route,json.dumps(payload),{'Content-Type':'application/json','Authorization':'Bearer '+self.token})
            response=conn.getresponse();value=json.loads(response.read())
            if response.status!=200:raise RuntimeError(value)
            return value
        finally:conn.close()
    def pause(self,seconds):
        if os.name=='nt':
            from dsh_test_harness.vm.input import request
            request('task_pause',timeout=seconds+30,port=self.config['port'],seconds=seconds)
        else:
            subprocess.run(['sudo','systemctl','kill','--signal=STOP','--kill-whom=main','dafeiyu-supervisor.service'],check=True,capture_output=True)
            try:time.sleep(seconds)
            finally:subprocess.run(['sudo','systemctl','kill','--signal=CONT','--kill-whom=main','dafeiyu-supervisor.service'],check=True,capture_output=True)
        return self.core.state()
    def restart(self):
        if os.name=='nt':
            from dsh_test_harness.vm.input import request
            request('task_restart',timeout=30,name=self.config['task_name'],port=self.config['port'])
        else:
            subprocess.run(['sudo','systemctl','kill','--signal=KILL','--kill-whom=main','dafeiyu-supervisor.service'],check=True,capture_output=True)
        def available():
            try:return self.request('/state',{})
            except OSError:return None
        return until(available,45)
    def close(self,*args):
        for window in getattr(self,'reopened_windows',[]):
            from dsh_test_harness.entities import Entities
            current=next((w for w in Entities(None).snapshot()['windows'] if w['id']==window['id']),None)
            # The default browser can restore the user's old tabs. Close only
            # the newly opened, still-selected DSH tab after observations.
            if current and 'DeepSeek Harness' in current.get('title',''):
                Desktop().activate(current)
                if os.name=='nt':
                    from dsh_test_harness.vm.input import request
                    request('keys',keys='ctrl-w')
                else:
                    from dsh_test_harness.gnome import call
                    call('keys',{'keys':['Control_L','w']})
        # Cleanup happens after scenario assertions, and never ends pre-existing tasks.
        for task in self.state().get('live',[]):
            if task['id'] not in self.original_tasks and Path(task.get('project_dir','')) == Path(os.environ.get('DSH_TEST_SESSION_DIRECTORY',str(self.out)))/'project':
                def finish_owned_task():
                    try:
                        result=self.request('/finish',{'task_id':task['id'],'session_id':task['session_id'],'verdict':'cancelled','reason':'测试结束，清理本轮测试任务'})
                        return result if result.get('status') not in ('active','scheduled','awaiting_extension','verified_waiting') else None
                    except OSError:
                        # A restart or final idle exit can close a connection. Read
                        # the actual task before retrying this idempotent cleanup.
                        stored=self.core.store.get('task',task['id'])
                        return stored if stored and stored.get('status') not in ('active','scheduled','awaiting_extension','verified_waiting') else None
                until(finish_owned_task,45)

        allowed={'instructions','instructions_full','heartbeat_prompt','mascot_size','away_heartbeats','sampling','reporting','protect_task_changes'}
        current=self.settings()
        patch={k:v for k,v in self.original_settings.items() if k in allowed and current.get(k)!=v}
        if patch and not getattr(self,'defer_settings_restore',False):self.request('/settings/ui',{'patch':patch})

        import psutil
        cleanup=[]
        profile=getattr(self,'browser_profile',None)
        if profile:
            expected='--user-data-dir='+str(profile)
            for process in psutil.process_iter(['pid','cmdline']):
                if expected in (process.info['cmdline'] or []):self.notification_processes[process.pid]=process.create_time()
        # Only notifications whose PID was returned by this test's own tool calls.
        for pid,created_at in self.notification_processes.items():
            try:
                process=psutil.Process(pid)
                if process.create_time()!=created_at:continue
                if os.name=='nt':cleanup.append({'pid':pid,'created_at':created_at})
                else:process.terminate()
            except psutil.NoSuchProcess:pass
        if cleanup:
            (self.out/'cleanup-processes.json').write_text(json.dumps(cleanup),encoding='utf-8')
            from dsh_test_harness.vm.input import request
            request('cleanup_processes',processes=cleanup)


def cleanup_interrupted(out):
    """Restore this run's state after its scenario process exceeded the deadline."""
    out=Path(out);saved=json.loads((out/'cleanup-state.json').read_text(encoding='utf-8'))
    backend=Backend(out/'backend')
    backend.original_tasks=set(saved['original_tasks']);backend.original_settings=saved['original_settings']
    backend.close()
    return {'status':'cleaned','project':str(out/'project')}
