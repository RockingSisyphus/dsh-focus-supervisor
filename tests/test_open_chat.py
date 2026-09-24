"""Handoff protocol contracts; actual UI acceptance lives in the VM JSON cases."""
import importlib.util,json,socket,sys,types
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('monitor_open_chat',Path(__file__).resolve().parents[1]/'deploy/open_chat.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

@pytest.fixture
def harness(monkeypatch):
    opened=[];calls=[];raised=[];state={'claimed':True,'session_ready':True,'marker':'[DSH-r]'}
    monkeypatch.setattr(module,'CLAIM_WAIT_SECONDS',.03)
    monkeypatch.setattr(module,'THAW_WAIT_SECONDS',.03)
    monkeypatch.setattr(module,'COLD_WAIT_SECONDS',.03)
    monkeypatch.setattr(module,'CLAIM_POLL_SECONDS',.001)
    monkeypatch.setattr(module.os,'startfile',lambda url:opened.append(url),raising=False)
    monkeypatch.setattr(module.subprocess,'Popen',lambda args,**kw:opened.append(args[-1]))
    def native(*args,**kwargs):raised.append((args,kwargs));return {'raised':True,'steps':[{'step':'verify','ok':True}]}
    monkeypatch.setitem(sys.modules,'focus_window',types.SimpleNamespace(raise_dsh_window=native,wake_existing_dsh_window=lambda:{'found':False}))
    def call(origin,route,payload=None,**kwargs):
        calls.append((origin,route,payload))
        if route=='/focus/open-request':return {'id':'r','open_page':True}
        if route=='/focus/open-result':return {'completed':payload['raised']}
        return dict(state)
    monkeypatch.setattr(module,'_plugin_call',call)
    return types.SimpleNamespace(opened=opened,calls=calls,raised=raised,state=state,call=call)

URL='http://127.0.0.1:3080/focus/open?session=session-x'

def test_existing_page_completes_native_operation_without_duplicate(harness):
    assert module.open_chat(URL)=='[DSH-r]'
    assert not harness.opened
    assert harness.raised==[(('[DSH-r]',),{'request_context':{'origin':'http://127.0.0.1:3080','id':'r'}})]
    assert harness.calls[-1][1]=='/focus/open-result'

def test_frozen_existing_window_is_restored_before_cold_open(harness,monkeypatch):
    harness.state.clear();harness.state.update(claimed=False,session_ready=False)
    def wake():
        harness.state.update(claimed=True,session_ready=True,marker='[DSH-r]')
        return {'found':True,'raised':True,'window_id':'gnome:4'}
    monkeypatch.setattr(sys.modules['focus_window'],'wake_existing_dsh_window',wake)
    assert module.open_chat(URL)=='[DSH-r]'
    assert not harness.opened
    assert len([c for c in harness.calls if c[1]=='/focus/open-request'])==1


def test_existing_window_restore_failure_does_not_open_duplicate(harness,monkeypatch):
    harness.state.clear();harness.state.update(claimed=False,session_ready=False)
    monkeypatch.setattr(sys.modules['focus_window'],'wake_existing_dsh_window',
        lambda:{'found':True,'raised':False,'reason':'桌面接口失效'})
    with pytest.raises(module.RaiseFailed,match='桌面接口失效'):module.open_chat(URL)
    assert not harness.opened


def test_restored_window_without_page_claim_reports_failure_not_new_tab(harness,monkeypatch):
    harness.state.clear();harness.state.update(claimed=False,session_ready=False)
    monkeypatch.setattr(sys.modules['focus_window'],'wake_existing_dsh_window',
        lambda:{'found':True,'raised':True,'window_id':'gnome:4'})
    with pytest.raises(RuntimeError,match='未新建重复标签页'):module.open_chat(URL)
    assert not harness.opened


def test_delivery_without_completion_does_not_open_duplicate(harness):
    harness.state.clear();harness.state.update(claimed=True,session_ready=False)
    with pytest.raises(RuntimeError,match='仍在切换'):module.open_chat(URL)
    assert not harness.opened and not harness.raised
    assert harness.calls[-1][2]['raised'] is False

def test_failed_existing_page_never_opens_more_tabs(harness):
    harness.state['error']='unknown session'
    with pytest.raises(RuntimeError,match='unknown session'):module.open_chat(URL)
    assert not harness.opened

def test_connection_loss_after_claim_does_not_open_duplicate(harness,monkeypatch):
    count=0
    def call(origin,route,payload=None,**kw):
        nonlocal count
        if '?' in route:
            count+=1
            if count>1:raise OSError('connection lost')
            return {'claimed':True,'session_ready':False}
        return harness.call(origin,route,payload,**kw)
    monkeypatch.setattr(module,'_plugin_call',call)
    with pytest.raises(RuntimeError,match='连接中断'):module.open_chat(URL)
    assert not harness.opened

def test_failed_native_result_is_reported_and_never_opens_duplicate(harness,monkeypatch):
    monkeypatch.setitem(sys.modules,'focus_window',types.SimpleNamespace(raise_dsh_window=lambda *a,**kw:{'raised':False,'reason':'扩展未运行','steps':[{'step':'verify','ok':False}]}))
    with pytest.raises(module.RaiseFailed,match='扩展未运行') as error:module.open_chat(URL)
    assert error.value.raise_result['steps'] and not harness.opened
    assert harness.calls[-1][2]['raised'] is False

def test_replaced_request_does_not_activate(harness):
    harness.state['expired']=True;harness.state['replaced']=True
    with pytest.raises(RuntimeError,match='替代'):module.open_chat(URL)
    assert not harness.raised and not harness.opened

def test_cold_browser_preserves_request_and_waits_for_native_completion(harness,monkeypatch,tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));listener.listen()
        origin='http://127.0.0.1:'+str(listener.getsockname()[1])
        registry=tmp_path/'endpoint.json';registry.write_text(json.dumps({'origin':origin}))
        def call(where,route,payload=None,**kw):
            if '?' in route and not harness.opened:return {'claimed':False,'session_ready':False}
            return harness.call(where,route,payload,**kw)
        monkeypatch.setattr(module,'_plugin_call',call)
        assert module.open_chat(URL,str(registry))=='[DSH-r]'
        assert harness.opened==[origin+'/focus/open?session=session-x&request=r']
        assert len([c for c in harness.calls if c[1]=='/focus/open-request'])==1
        assert len(harness.raised)==1

def test_stale_registry_uses_reminder_origin(harness,monkeypatch,tmp_path):
    registry=tmp_path/'endpoint.json';registry.write_text('{"origin":"http://127.0.0.1:9"}')
    def call(origin,*args,**kwargs):
        if origin.endswith(':9'):raise OSError('old address')
        return harness.call(origin,*args,**kwargs)
    monkeypatch.setattr(module,'_plugin_call',call)
    assert module.open_chat(URL,str(registry))=='[DSH-r]'
    assert not harness.opened
