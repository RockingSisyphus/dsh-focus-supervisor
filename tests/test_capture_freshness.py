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
    snapshot = tmp_path/'gnome-snapshot.json'
    monkeypatch.setenv('FOCUS_GNOME_SNAPSHOT', str(snapshot))
    def publish(meta=None):
        write_json(snapshot, dict(ts=time.time(), backend='gnome', windows=[], screen=[0,0,20,20], screen_capture=meta))
    collector = Collector('gnome',0,0,SimpleNamespace(data_dir=tmp_path/'data',screenshots=True,ui_text=False,detail_interval=60))
    stop = threading.Event()
    release = threading.Event()
    def bridge():
        while not stop.wait(.02):
            if not release.is_set():continue
            filename=f'screen-{time.monotonic_ns()}.png'
            Image.new('RGB',(20,20),'green').save(tmp_path/filename)
            publish(dict(file=filename,captured_at=time.time(),screen=[0,0,20,20]))
    for _ in range(2):
        publish()
        release.clear()
        worker=threading.Thread(target=bridge);worker.start()
        try:
            result=collector.capture()['desktop']
            assert result['available'] and not result.get('desktop_screenshot')
            release.set()
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                result=collector.capture()['desktop']
                if result.get('desktop_screenshot'):break
                time.sleep(.02)
            assert result['desktop_screenshot']['scope']=='full_desktop'
        finally:
            collector.suspend()
            stop.set();worker.join();stop.clear()


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


def test_missing_bridge_times_out_without_reusing_old_screen(tmp_path):
    from focus_demo.collectors import GnomeDesktop
    snapshot = tmp_path/'gnome-snapshot.json'
    Image.new('RGB', (20,20)).save(tmp_path/'old.png')
    write_json(snapshot, dict(ts=time.time(), windows=[], screen_capture=dict(file='old.png', captured_at=time.time()-1)))
    started = time.monotonic()
    result = GnomeDesktop(snapshot).request_capture(True, wait=True, timeout=.1)
    assert time.monotonic()-started < 1
    assert result['screen_capture'] is None
    assert any('超时' in item for item in result['limitations'])


def test_disabled_screenshots_do_not_wait_or_authorize(tmp_path):
    from focus_demo.collectors import GnomeDesktop
    result = GnomeDesktop(tmp_path/'missing.json').request_capture(False, wait=True)
    assert result['available'] is False
    assert json.loads((tmp_path/'capture-request.json').read_text())['screenshots'] is False


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
