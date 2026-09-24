"""Protocol and idle lifecycle regression; no simulated desktop pass claims."""
import json,time,sys
from types import SimpleNamespace
import pytest
from focus_demo import desktop_bridge as bridge
from focus_demo.collectors import GnomeDesktop
from focus_demo.supervisor import Supervisor

@pytest.fixture
def wire(monkeypatch):
    calls=[]
    class Bus:
        def call(self,name,path,interface,method,signature,values,timeout):
            request=json.loads(values[0]);calls.append(request)
            return json.dumps({'request_id':request['id'],'code_version':bridge.VERSION,'windows':[],'screen':[0,0,100,100],'backend':'gnome','available':True,'ts':time.time()})
        def close(self):pass
    monkeypatch.setattr(bridge,'NativeBus',Bus)
    return calls

def test_metadata_does_not_request_pixels(wire):
    desktop=GnomeDesktop()
    desktop.request_capture(True)
    assert [r['op'] for r in wire]==['snapshot']
    desktop.request_capture(True,wait=True)
    assert wire[-1]['op']=='capture'
    desktop.release()

def test_status_never_requests_snapshot(wire):
    bridge.call('status');assert wire[0]['op']=='status'

def test_wrong_reply_rejected(monkeypatch):
    class Bus:
        def call(self,*args):return json.dumps({'request_id':'other','code_version':bridge.VERSION})
        def close(self):pass
    monkeypatch.setattr(bridge,'NativeBus',Bus)
    with pytest.raises(RuntimeError,match='编号'):bridge.call('minimize',{'window_id':'gnome:1','pid':42})

@pytest.mark.parametrize('status,standby',[('scheduled',False),('verified_waiting',False),('active',True)])
def test_inactive_task_does_not_capture(tmp_path,status,standby):
    operations=[]
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None),SimpleNamespace(call=lambda op,*args:operations.append(op)))
    try:
        core.store.save('task',{'id':'task','status':status,'standby':standby})
        core.capture();assert operations==[]
        core.collecting=True;core.capture();core.capture()
        assert operations==['cleanup_capture']
    finally:core.store.close()


def test_delayed_gio_lifecycle():
    import shutil,subprocess
    from pathlib import Path
    node=shutil.which('node')
    if not node:pytest.skip('Node is needed for the GJS protocol simulation')
    subprocess.run([node,str(Path(__file__).with_name('desktop_bridge_runtime.mjs'))],check=True,timeout=20)


def test_capture_connection_lives_until_pixels_released(monkeypatch):
    connections=[]
    class Bus:
        def __init__(self):self.closed=False;connections.append(self)
        def call(self,*args):
            request=json.loads(args[-2][0])
            return json.dumps({'request_id':request['id'],'code_version':bridge.VERSION})
        def close(self):self.closed=True
    monkeypatch.setattr(bridge,'NativeBus',Bus)
    bridge.call('capture')
    assert len(connections)==1 and not connections[0].closed
    bridge.call('release')
    assert len(connections)==1 and connections[0].closed


def test_slow_status_disk_does_not_block_control_and_coalesces(tmp_path,monkeypatch):
    import threading
    import focus_demo.status_writer as module
    started=threading.Event();release=threading.Event();written=[]
    def slow(path,value):
        started.set();assert release.wait(5);written.append(value)
    monkeypatch.setattr(module,'write_json',slow)
    writer=module.StatusWriter()
    try:
        writer.submit(tmp_path/'status.json',0);assert started.wait(2)
        for number in range(1,1001):writer.submit(tmp_path/'status.json',number)
        assert len(writer.pending)==1
    finally:release.set();writer.close()
    assert written==[0,1000]


def test_idle_ticks_do_not_rewrite_unchanged_status(tmp_path):
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None))
    writes=[];core.publisher=SimpleNamespace(submit=lambda *args:writes.append(args),error=None)
    try:
        core.tick();core.tick();core.tick()
        assert len(writes)==1
    finally:core.store.close()


@pytest.mark.skipif(sys.platform!='linux',reason='Linux privileged service desktop pipe')
def test_slow_screenshot_persistence_does_not_hold_desktop_channel(tmp_path,monkeypatch):
    import io,threading
    from deploy.chat_service import Sensor
    entered,release=threading.Event(),threading.Event()
    sensor=Sensor(None,tmp_path)
    sensor.process=SimpleNamespace(poll=lambda:None,stdin=io.StringIO(),stdout=io.StringIO(json.dumps({'result':{'images':{},'sample':{'ts':1}}})+'\n'))
    monkeypatch.setattr('deploy.chat_service.select.select',lambda *a:([sensor.process.stdout],[],[]))
    def save(images):
        entered.set();assert release.wait(2)
    monkeypatch.setattr(sensor,'save_images',save)
    result=[]
    worker=threading.Thread(target=lambda:result.append(sensor.call('capture')))
    worker.start()
    try:
        assert entered.wait(1)
        assert sensor.lock.acquire(timeout=.1)
        sensor.lock.release()
    finally:
        release.set();worker.join(2)
    assert len(result)==1 and result[0]['ts']==1
    assert set(result[0]['capture_timings'])=={'sensor_exchange','save_images'}


def test_sample_commit_does_not_block_status(tmp_path,monkeypatch):
    import threading
    entered,release=threading.Event(),threading.Event()
    now=time.time()
    sample={'ts':now,'mono':time.monotonic(),'desktop':{'available':True,'windows':[]}}
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None),SimpleNamespace(call=lambda *a:sample))
    task={'id':'task','status':'active'}
    core.store.save('task',task)
    original=core.store.add_sample
    def slow(task_id,value):
        entered.set();assert release.wait(3)
        return original(task_id,value)
    monkeypatch.setattr(core.store,'add_sample',slow)
    worker=threading.Thread(target=core.capture)
    worker.start()
    try:
        assert entered.wait(1)
        started=time.monotonic()
        assert core.state()['live'][0]['id']=='task'
        assert time.monotonic()-started<.5
    finally:
        release.set();worker.join(3);core.store.close()


def test_ended_task_rejects_late_sample_at_write_boundary(tmp_path):
    from focus_demo.store import Store
    store=Store(tmp_path/'store.sqlite3')
    try:
        store.save('task',{'id':'task','status':'cancelled'})
        assert store.add_live_sample('task',{'ts':1,'mono':1}) is None
        assert store.samples('task')==[]
    finally:store.close()


def test_successful_settings_write_does_not_hide_status_write_failure(tmp_path,monkeypatch):
    import threading
    from focus_demo import status_writer
    settings_written=threading.Event()
    def write(path,value,**kwargs):
        if path.name=='status.json':raise OSError('injected disk full')
        settings_written.set()
    monkeypatch.setattr(status_writer,'write_json',write)
    writer=status_writer.StatusWriter()
    writer.submit(tmp_path/'status.json',{})
    writer.submit(tmp_path/'settings.json',{})
    assert settings_written.wait(2)
    with pytest.raises(RuntimeError,match='disk full'):writer.close()


def test_away_idle_counter_does_not_cause_periodic_status_writes(tmp_path):
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None));writes=[]
    core.publisher=SimpleNamespace(submit=lambda *args:writes.append(args),error=None)
    try:
        core.store.save('task',{'id':'away','status':'active','standby':True})
        for seconds in range(60):
            core.presence={'available':True,'observed_at':100+seconds,'idle_seconds':seconds,'last_input_at':100+seconds%2*.003}
            core.publish()
        assert len(writes)==1
        assert core.state()['presence']['idle_seconds']==59
        core.presence={'available':False,'error':'interface disconnected'};core.publish()
        assert len(writes)==2
    finally:core.store.close()
