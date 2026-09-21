"""Fault injection contracts: never report a live process as terminated."""
import os
import pytest
import psutil
from focus_demo.actions import kill_verified_process
from focus_demo.platforms import process_info

def test_kill_signal_without_exit_is_not_success(monkeypatch):
    import subprocess,sys
    child=subprocess.Popen([sys._base_executable,'-c','import time;time.sleep(60)'])
    real_kill=psutil.Process.kill
    try:
        monkeypatch.setattr(psutil.Process,'kill',lambda self:None)
        monkeypatch.setattr(psutil,'wait_procs',lambda processes,timeout:([],processes))
        result=kill_verified_process(child.pid,process_info(child.pid)['identity'])
        assert result['closed'] is False
        assert child.pid in result['alive_pids']
    finally:
        real_kill(psutil.Process(child.pid));child.wait()


def test_missing_desktop_is_not_an_already_closed_window(monkeypatch):
    from types import SimpleNamespace
    from focus_demo.actions import force_close_authorization
    expected={'id':'gnome:1','process':{'pid':123,'identity':'old'}}
    monkeypatch.setattr('focus_demo.actions.process_info',lambda pid:{'identity':'new'})
    collector=SimpleNamespace(_capture=lambda:{'desktop':{'available':False,'windows':[]}})
    assert not force_close_authorization(collector,expected)['authorized']


def test_window_failure_escalates_once_and_keeps_actual_scope(monkeypatch):
    from focus_demo.close_actions import force_close
    monkeypatch.setattr('focus_demo.actions.force_close_authorization',lambda *a:{'authorized':True,'pid':987654,'identity':'test'})
    monkeypatch.setattr('focus_demo.close_actions.close_window',lambda *a:{'closed':False,'requested':True})
    calls=[]
    def kill(pid,identity):calls.append(pid);return {'closed':True,'forced':True,'alive_pids':[]}
    monkeypatch.setattr('focus_demo.actions.kill_verified_process',kill)
    result=force_close(None,{'id':'win:3','process':{'pid':987654}},'window')
    assert result['closed'] and result['actual_scope']=='process'
    assert calls==[987654]
    assert [a['scope'] for a in result['attempts']]==['window','process']


def test_already_closed_never_reaches_privileged_kill(monkeypatch):
    from focus_demo.close_actions import force_close,finish_process_fallback
    monkeypatch.setattr('focus_demo.actions.force_close_authorization',lambda *a:{'authorized':True,'already_closed':True,'pid':987654,'identity':'test'})
    monkeypatch.setattr('focus_demo.actions.kill_verified_process',lambda *a:(_ for _ in ()).throw(AssertionError('must not kill')))
    for kind in ('process','window','browser_tab'):
        result=finish_process_fallback(force_close(None,{},kind,defer_kill=True))
        assert result['closed'] and result['already_closed']


def test_minimize_unavailable_is_failure():
    from types import SimpleNamespace
    import threading
    from focus_demo.actions import request_window_minimize
    collector=SimpleNamespace(lock=threading.RLock(),details=None,_capture=lambda:{'desktop':{'available':False,'windows':[]}})
    assert request_window_minimize(collector,{'id':'missing'})['minimized'] is False


def test_browser_rpc_closes_plain_websocket(monkeypatch):
    from focus_demo.browser_targets import rpc
    class Connection:
        closed=False
        def send(self,value):pass
        def recv(self):return '{"id":1,"result":{"windowId":42}}'
        def close(self):self.closed=True
    connection=Connection()
    monkeypatch.setattr('focus_demo.browser_targets.websocket.create_connection',lambda *a,**kw:connection)
    assert rpc('ws://localhost','Browser.getWindowForTarget')['windowId']==42
    assert connection.closed


def test_access_denied_keeps_live_process_failure(monkeypatch):
    import subprocess,sys
    child=subprocess.Popen([sys._base_executable,'-c','import time;time.sleep(60)'])
    real_kill=psutil.Process.kill
    try:
        monkeypatch.setattr(psutil.Process,'kill',lambda self:(_ for _ in ()).throw(psutil.AccessDenied(self.pid)))
        monkeypatch.setattr(psutil,'wait_procs',lambda processes,timeout:([],processes))
        result=kill_verified_process(child.pid,process_info(child.pid)['identity'])
        assert not result['closed'] and child.pid in result['alive_pids']
        assert {row['pid'] for row in result['errors']}==set(result['alive_pids'])
    finally:real_kill(psutil.Process(child.pid));child.wait()


def test_empty_window_and_tab_metadata_remain_report_targets():
    from focus_demo.prompts import timeline
    window={'id':'gnome:5','title':'No body','app':'browser','pid':12,'process':{'pid':12,'identity':'instance'},'mapped':False,'minimized':True,'visible':False,'focused':False}
    tab={**window,'id':'tab:12:abc','kind':'browser_tab','native_window_id':'gnome:5','tab_id':'abc','browser_instance_id':'12:instance'}
    sample={'sample_id':1,'mono':1,'ts':1,'desktop':{'available':True,'windows':[window]},'browser':{'available':True,'pages':[],'action_targets':[tab]}}
    result=timeline([sample],2)
    assert {r['kind'] for r in result['evidence'].values()}=={'window','browser_tab'}
    assert all(r['process']['identity']=='instance' for r in result['evidence'].values())


@pytest.mark.parametrize("visibility", ["visible", "hidden"])
def test_same_title_tabs_survive_missing_native_association(monkeypatch, visibility):
    from focus_demo import browser_targets as browser
    monkeypatch.setattr(browser,'endpoint',lambda pid:'http://localhost')
    monkeypatch.setattr(browser,'get',lambda origin,path: {'webSocketDebuggerUrl':'browser'} if path=='/json/version' else [{'type':'page','id':'exact-tab','title':'Same title','webSocketDebuggerUrl':'page'}])
    monkeypatch.setattr(browser,'rpc',lambda url,method,params: {'result':{'value':visibility}} if url=='page' else {'windowId':42,'bounds':{'left':0,'top':0,'width':100,'height':100}})
    windows=[{'id':f'gnome:{i}','pid':12,'process':{'pid':12,'identity':'life'},'title':'Same title','rect':[i,2,3,4]} for i in (1,2)]
    result=browser.capture(windows)
    assert len(result['targets'])==1
    target=result['targets'][0]
    assert target['tab_id']=='exact-tab' and target['process']['identity']=='life'
    assert target['native_window_id'] is None
    assert target['visible'] == (visibility == 'visible')


def test_partial_tree_exit_preserves_surviving_child(monkeypatch):
    import subprocess,sys,json
    parent=subprocess.Popen([sys._base_executable,'-u','-c','import subprocess,sys,time; p=subprocess.Popen([sys._base_executable,"-c","import time;time.sleep(60)"]);print(p.pid,flush=True);time.sleep(60)'],stdout=subprocess.PIPE,text=True)
    child=psutil.Process(int(parent.stdout.readline()))
    real_kill=psutil.Process.kill
    try:
        identity=process_info(parent.pid)['identity']
        monkeypatch.setattr(psutil.Process,'kill',lambda self: None if self.pid==child.pid else real_kill(self))
        monkeypatch.setattr(psutil,'wait_procs',lambda processes,timeout: (parent.wait(timeout=5),[child]))
        result=kill_verified_process(parent.pid,identity)
        assert not result['closed'] and result['alive_pids']==[child.pid]
        assert result['children_seen']==1 and result['killed_children']==0
    finally:
        if parent.poll() is None:real_kill(psutil.Process(parent.pid));parent.wait()
        try:real_kill(child)
        except psutil.NoSuchProcess:pass
        parent.stdout.close()


def test_blocked_browser_worker_is_terminated_before_fallback(monkeypatch,tmp_path):
    import subprocess,sys
    from focus_demo import close_actions
    from focus_demo.process_worker import run_worker as real_run
    pidfile=tmp_path/'worker.pid'
    def blocked(command,**kwargs):
        # Real timeout/termination with a stalled worker; only its program is injected.
        return real_run([sys.executable,'-c',f'import os,time;open({str(pidfile)!r},"w").write(str(os.getpid()));time.sleep(60)'],**{**kwargs,'timeout':.3})
    monkeypatch.setattr(close_actions,'run_worker',blocked)
    result=close_actions.close_tab({'process':{'pid':123}})
    assert not result['closed']
    assert not psutil.pid_exists(int(pidfile.read_text()))


def test_partial_fallback_separates_target_and_process_tree(monkeypatch):
    from focus_demo.close_actions import finish_process_fallback
    monkeypatch.setattr('focus_demo.actions.kill_verified_process',lambda *args:{'closed':False,'alive_pids':[42],'reason':'child alive'})
    for kind in ('window','browser_tab','process'):
        result=finish_process_fallback({'closed':False,'target_kind':kind,'attempts':[],'process_fallback':{'pid':12,'identity':'life'}},lambda:{'closed':True})
        assert result['closed'] is (kind!='process')
        assert not result['process_result']['closed'] and result['alive_pids']==[42]
    def unavailable():raise RuntimeError('observation unavailable')
    result=finish_process_fallback({'closed':False,'target_kind':'window','attempts':[],'process_fallback':{'pid':12,'identity':'life'}},unavailable)
    assert not result['closed'] and result['target_observation']['reason']=='observation unavailable'


def test_exit_between_liveness_and_identity_is_already_closed(monkeypatch):
    import subprocess,sys
    from focus_demo import actions
    target=subprocess.Popen([sys._base_executable,'-c','import time;time.sleep(60)'])
    identity=process_info(target.pid)['identity']
    def disappear(pid):
        target.kill();target.wait()
        return process_info(pid)
    try:
        monkeypatch.setattr(actions,'process_info',disappear)
        result=actions.kill_verified_process(target.pid,identity)
        assert result['closed'] and result['already_closed']
    finally:
        if target.poll() is None:target.kill();target.wait()


def test_one_tab_without_browser_window_does_not_drop_other_tabs(monkeypatch):
    from focus_demo import browser_targets as browser
    monkeypatch.setattr(browser,'endpoint',lambda pid:'http://localhost')
    monkeypatch.setattr(browser,'get',lambda origin,path: {'webSocketDebuggerUrl':'browser'} if path=='/json/version' else [{'type':'page','id':key,'title':'Same title','webSocketDebuggerUrl':key} for key in ('unmapped','target')])
    def rpc(url,method,params):
        if method=='Runtime.evaluate':return {'result':{'value':'visible'}}
        if params['targetId']=='unmapped':raise RuntimeError('Browser window not found')
        return {'windowId':42,'bounds':{'left':0,'top':0,'width':100,'height':100}}
    monkeypatch.setattr(browser,'rpc',rpc)
    result=browser.capture([{'id':'win:1','pid':12,'process':{'pid':12,'identity':'life'},'title':'Same title','rect':[0,0,100,100]}])
    assert [r['tab_id'] for r in result['targets']]==['unmapped','target']
    assert result['targets'][0]['native_window_id'] is None
    assert result['targets'][1]['browser_window_id']==42
    assert result['errors'][0]['tab_id']=='unmapped'
