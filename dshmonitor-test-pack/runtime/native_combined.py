"""Same composite native scenario and assertions on Linux/Wayland and Windows/UIA."""
import argparse,json,os,secrets,signal,subprocess,sys,time,traceback
from pathlib import Path
from types import SimpleNamespace as N
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from focus_demo.collectors import Collector
from focus_demo.supervisor import Supervisor
from focus_demo.common import write_json
from focus_demo.evidence_export import user_export,user_verify,user_cleanup
from support import *
from dsh_test_harness.scenario import ScenarioEngine
from native_actions import NativeActions


def until(fn,timeout=25):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=fn()
            if value:return value
        except (OSError,ValueError):pass
        time.sleep(.15)
    raise TimeoutError('Fixture/desktop condition not reached')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--case',type=Path,default=ROOT/'dshmonitor-test-pack/cases/native-combined.json');parser.add_argument('--human-review',action='store_true');args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    processes=[];collector=core=None;bus_pid=None;checks=[];samples=[]
    log=(out/'process.log').open('w',encoding='utf-8')
    original_env=os.environ.copy()
    def start(argv,env=None):
        p=subprocess.Popen(argv,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log);processes.append(p);return p
    try:
        win=sys.platform=='win32'
        from dsh_test_harness.desktop import Desktop
        Desktop().setup(out,start,visible=args.human_review)
        fixture_dir=out/'fixture';fixture_dir.mkdir(exist_ok=True)
        fixture=start([sys.executable if win else '/usr/bin/python3',str(ROOT/'dshmonitor-test-pack/fixtures/native-combined'/('windows.py' if win else 'linux.py')),str(fixture_dir)])
        ready=until(lambda:json.loads((fixture_dir/'ready.json').read_text(encoding='utf-8')))
        collector=Collector('windows' if win else 'gnome',49998,49999,N(data_dir=str(out),screenshots=True,ui_text=True,detail_interval=0,browser_text=False,browser_skill=False,log_root=[str(fixture_dir)],system_logs=False))
        class Sensor:
            def call(self,op,payload=None):
                if op=='capture':
                    s=collector.capture();samples.append(s);write_json(out/'samples.json',samples);return s
                if op=='minimize':return collector.minimize_window_verified(payload)
                if op=='export':return user_export(payload)
                if op=='verify_export':return user_verify(payload)
                if op=='cleanup_export':return user_cleanup(payload)
                if op=='cleanup_capture':collector.suspend();return {'removed':True}
                raise ValueError(op)
        core=Supervisor(out/'backend',N(enable=lambda:None),Sensor(),interval=2,sample=3,test_mode=True)
        case=json.loads(args.case.read_text(encoding='utf-8'))
        actions=NativeActions(core,collector,fixture_dir,out,ready,samples)
        engine=ScenarioEngine(case,out,{'project':str(out)},actions.registry())
        engine.run()
        checks=[{'id':step['id'],'passed':step['status']=='passed'} for step in engine.steps if step['op']=='assert']
        result={'status':'passed','checks':checks,'real_model_called':False,'transport':'direct production Supervisor; not DSH chat','platform':sys.platform}
    except Exception as error:
        checks=[{'id':step['id'],'passed':step['status']=='passed'} for step in engine.steps if step['op']=='assert'] if 'engine' in locals() else checks
        result={'status':'failed','checks':checks,'error':str(error),'traceback':traceback.format_exc(),'platform':sys.platform};raise
    finally:
        if 'result' in locals():write_json(out/'result.json',result)
        if core:core.store.close()
        if collector:collector.suspend()
        for p in reversed(processes):
            if p.poll() is None:p.terminate();p.wait(timeout=10)
        if bus_pid:os.kill(bus_pid,signal.SIGTERM)
        log.close()


if __name__=='__main__':main()
