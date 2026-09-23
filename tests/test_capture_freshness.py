"""Cold GNOME capture uses this request's completed image, including after idle."""
import json
import time
import threading
import subprocess
from types import SimpleNamespace

from PIL import Image
from focus_demo.collectors import Collector
from focus_demo.common import write_json


def test_metadata_does_not_wait_for_image_and_resume_uses_new_image(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_RUNTIME_DIR',str(tmp_path))
    root=tmp_path/'dafeiyu-desktop';root.mkdir()
    entered,release=threading.Event(),threading.Event()
    def call(operation, **kwargs):
        data=dict(ts=time.time(),backend='gnome',available=True,windows=[],screen=[0,0,20,20])
        if operation=='capture':
            entered.set();assert release.wait(2)
            filename=f'screen-{time.monotonic_ns()}.png'
            Image.new('RGB',(20,20),'green').save(root/filename)
            data['screen_capture']=dict(file=filename,captured_at=time.time(),screen=[0,0,20,20])
        return data
    monkeypatch.setattr('focus_demo.desktop_bridge.call',call)
    collector=Collector('gnome',0,0,SimpleNamespace(data_dir=tmp_path/'data',screenshots=True,ui_text=False,detail_interval=60))
    timestamps=[]
    for _ in range(2):
        entered.clear();release.clear()
        try:
            result=collector.capture()['desktop']
            assert result['available'] and not result.get('desktop_screenshot')
            assert entered.wait(1)
            release.set()
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                result=collector.capture()['desktop']
                if result.get('desktop_screenshot'):break
                time.sleep(.02)
            assert result['desktop_screenshot']['scope']=='full_desktop'
            timestamps.append(result['desktop_screenshot']['captured_at'])
        finally:
            release.set();collector.suspend()
    assert timestamps[1]>timestamps[0]


def test_accessibility_helper_imports_outside_project(tmp_path, monkeypatch):
    from focus_demo.details import DetailCollector
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('PYTHONPATH', raising=False)
    real_run = subprocess.run
    calls = []
    def run(argv, **kw):
        # Run the real module/import protocol without requiring a desktop bus.
        kw['input'] = '[]'
        result = real_run(argv, **kw)
        calls.append(result)
        return result
    monkeypatch.setattr('focus_demo.details.run_worker', run)
    details = DetailCollector(SimpleNamespace(data_dir=tmp_path, screenshots=False, ui_text=True, detail_interval=0))
    result = details.enrich({'windows':[dict(id='test', pid=0, title='test', rect=[0,0,20,20])]})
    assert calls, result.get('limitations')
    assert not any('批量读取失败' in n for n in result.get('limitations', []))


def test_missing_bridge_times_out_without_reusing_old_screen(tmp_path,monkeypatch):
    from focus_demo.collectors import GnomeDesktop
    Image.new('RGB',(20,20)).save(tmp_path/'old.png')
    def timeout(*args,**kwargs):raise RuntimeError('capture timeout')
    monkeypatch.setattr('focus_demo.desktop_bridge.call',timeout)
    result=GnomeDesktop().request_capture(True,wait=True,timeout=.1)
    assert not result['available']
    assert not result.get('screen_capture')
    assert any('timeout' in item for item in result['limitations'])


def test_disabled_screenshots_only_request_metadata(monkeypatch):
    from focus_demo.collectors import GnomeDesktop
    calls=[]
    def call(operation,**kwargs):
        calls.append(operation)
        return {'windows':[],'screen':[0,0,20,20],'available':True}
    monkeypatch.setattr('focus_demo.desktop_bridge.call',call)
    assert GnomeDesktop().request_capture(False,wait=True)['available']
    assert calls==['snapshot']


def test_new_window_and_changed_page_are_not_throttled_as_cached(tmp_path):
    from focus_demo.details import DetailCollector
    details=DetailCollector(SimpleNamespace(data_dir=tmp_path,screenshots=False,ui_text=False,detail_interval=60))
    def capture(title):
        return details.enrich({'windows':[{'id':'a','pid':0,'title':title,'rect':[0,0,100,100]}]})['windows'][0]
    first=capture('first')
    same=capture('first')
    changed=capture('second')
    assert same['details_captured_at']==first['details_captured_at']
    assert changed['details_captured_at']>first['details_captured_at']
    assert changed['title']=='second'


def test_completed_details_do_not_attach_to_a_changed_window(tmp_path):
    from focus_demo.details import DetailCollector
    entered,release=threading.Event(),threading.Event()
    old={'available':True,'windows':[{'id':'a','pid':0,'title':'old','rect':[0,0,10,10]}]}
    def provider():
        entered.set();assert release.wait(2)
        return json.loads(json.dumps(old))
    details=DetailCollector(SimpleNamespace(data_dir=tmp_path,screenshots=False,ui_text=False),provider)
    try:
        details.capture(json.loads(json.dumps(old)));assert entered.wait(1)
        changed={'available':True,'windows':[{**old['windows'][0],'title':'new'}]}
        assert 'details_captured_at' not in details.capture(changed)['windows'][0]
        release.set()
        deadline=time.monotonic()+2
        while not details.published and time.monotonic()<deadline:time.sleep(.01)
        assert details.published
        assert 'details_captured_at' not in details.capture(changed)['windows'][0]
    finally:
        release.set();details.suspend()


def test_completed_window_is_published_before_slow_later_window(tmp_path, monkeypatch):
    from focus_demo.details import DetailCollector
    entered, release = threading.Event(), threading.Event()
    details = DetailCollector(SimpleNamespace(data_dir=tmp_path, screenshots=False, ui_text=False))
    def logs(window):
        if window['id'] == 'slow':
            entered.set()
            assert release.wait(2)
        return []
    monkeypatch.setattr(details.generic_logs, 'read', logs)
    def desktop():
        return {'windows':[dict(id=name, pid=0, title=name, rect=[0,0,10,10])
                           for name in ('ready','slow')]}
    try:
        details.capture(desktop())
        assert entered.wait(1)
        observed = details.capture(desktop())['windows']
        assert 'logs_captured_at' in observed[0]
        assert 'logs_captured_at' not in observed[1]
    finally:
        release.set()
        details.suspend()
