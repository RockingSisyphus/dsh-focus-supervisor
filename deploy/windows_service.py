"""Task-bound Windows desktop supervisor, restarted by Windows Task Scheduler."""
import argparse,json,os,subprocess,sys,threading,time
from pathlib import Path
def startup_event(phase):
    try:
        config=Path(sys.argv[sys.argv.index('--config')+1])
        with config.with_name('service-startup.jsonl').open('a',encoding='utf-8') as log:
            log.write(json.dumps({'phase':phase,'at':time.time(),'pid':os.getpid()})+'\n')
    except (OSError,ValueError,IndexError):pass
startup_event('interpreter')
# pythonw has no console; retain real startup failures for installer/service diagnostics.
def startup_error(kind,error,tb):
    import traceback
    try:
        config=Path(sys.argv[sys.argv.index('--config')+1])
        config.with_name('service-error.log').write_text(''.join(traceback.format_exception(kind,error,tb)),encoding='utf-8')
    except (OSError,ValueError,IndexError):pass
    finally:sys.__excepthook__(kind,error,tb)
sys.excepthook=startup_error
from http.server import ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from focus_demo.supervisor import Supervisor
from focus_demo.http_api import Handler
from focus_demo.collectors import Collector
from focus_demo.windows_evidence import deliver
from types import SimpleNamespace
startup_event('imports_ready')

class Lifecycle:
    def __init__(self,config):self.config=config
    def switch(self,enabled):
        subprocess.run(['schtasks','/Change','/TN',self.config['task_name'],'/ENABLE' if enabled else '/DISABLE'],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    def enable(self):self.switch(True)
    def disable(self):self.switch(False)
    def wake_dsh(self):
        name=self.config.get('dsh_task')
        if name:subprocess.run(['schtasks','/Run','/TN',name],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)

class Sensor:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.lock=threading.Lock()
        self.collector=Collector('auto',49998,49999,SimpleNamespace(data_dir=str(directory),screenshots=True,ui_text=True,detail_interval=10,browser_text=False,browser_skill=True,log_root=[],system_logs=True))
    def call(self,operation,payload=None):
        # These operations use their own OS/file state, not the Collector. A
        # slow UIA capture must not hold up report delivery or presence queries
        # while the Supervisor is serving the chat's state request.
        if operation=='presence':
            from focus_demo.presence import read_presence
            return read_presence()
        if operation in ('export','verify_export','cleanup_export'):return deliver(operation,payload)
        if operation=='notify':
            with (self.directory/'notification-error.log').open('ab') as errors:
                child=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('desktop_notify.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW)
            child.stdin.write(json.dumps(payload)+'\n');child.stdin.close()
            return json.loads(child.stdout.readline())
        with self.lock:
            if operation=='capture':
                self.collector.configure((payload or {}).get('sampling',{}))
                return self.collector.capture()
            if operation=='minimize':return self.collector.minimize_window_verified(payload)
            if operation=='force_close':
                from focus_demo.close_actions import force_close
                return force_close(self.collector,payload['expected'],payload.get('target_kind','process'),
                                   force_kill=payload.get('force_kill',False))
            if operation=='cleanup_capture':self.collector.suspend();return {'removed':True}
            raise ValueError(operation)

def main():
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args();config=json.loads(Path(a.config).read_text(encoding='utf-8-sig'))
    directory=Path(config['data_dir']);directory.mkdir(parents=True,exist_ok=True)
    lifecycle=Lifecycle(config);sensor=Sensor(directory)
    startup_event('sensor_ready')
    server=ThreadingHTTPServer(('127.0.0.1',config['port']),Handler)
    server.api_token=config['token']
    core=Supervisor(directory,lifecycle,sensor,interval=config.get('interval',600),sample=config.get('sample',2))
    import ctypes
    core.execution={'platform':'windows','elevated':bool(ctypes.windll.shell32.IsUserAnAdmin()),'force_close_executor':'elevated desktop supervisor'}
    if not core.execution['elevated']:raise PermissionError('Install/start the supervisor with the Highest scheduled-task privilege')
    from focus_demo.status_writer import StatusWriter
    core.publisher=StatusWriter()
    server.core=core;core.publish_settings();core.publish();stop=threading.Event()
    threading.Thread(target=server.serve_forever,daemon=True).start()
    startup_event('listening')
    def sample():
        next_sample=next_presence=0
        while not stop.is_set():
            now=time.monotonic()
            if now>=next_presence:
                core.poll_presence();next_presence=now+(5 if core.capture_state()=='away' else 2)
            if core.capture_state()!='collecting':
                core.capture()  # Suspend immediately, even with a long sampling interval.
                next_sample=0
            elif now>=next_sample:
                delay=max(0,now-next_sample) if next_sample else 0
                core.capture()
                if core.settings()['debug_mode']:
                    with (directory/'capture-debug.jsonl').open('a',encoding='utf-8') as log:
                        log.write(json.dumps({'event':'capture_cycle','at':time.time(),
                                              'schedule_delay':round(delay,3),
                                              'timings':core.last_capture_timings},ensure_ascii=False)+'\n')
                next_sample=time.monotonic()+core.sample
            stop.wait(.25)
    worker=threading.Thread(target=sample,daemon=True);worker.start();wake_at=0
    try:
        while not stop.wait(1):
            core.tick()
            with core.lock:
                if core.live():
                    if core.needs_dsh() and time.time()>=wake_at:
                        try:lifecycle.wake_dsh();core.notices_woken()
                        except Exception as e:core.store.log('dsh_wake_failed',{'error':str(e)})
                        wake_at=time.time()+15
                elif core.empty_since is not None and time.time()-core.empty_since>=10:
                    startup_event('idle_exit')
                    core.shutting_down=True;lifecycle.disable();break
    finally:
        stop.set();server.shutdown();server.server_close();worker.join(timeout=35);sensor.collector.suspend();core.publisher.close();core.store.close()

if __name__=='__main__':main()
