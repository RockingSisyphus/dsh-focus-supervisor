"""Bringing the DSH window forward is bounded, one-shot and never guesses a window."""
import importlib.util,json,os,sys,time
from pathlib import Path

spec=importlib.util.spec_from_file_location('monitor_focus_window',Path(__file__).resolve().parents[1]/'deploy/focus_window.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def _snapshot(directory,windows):
    (directory/'gnome-snapshot.json').write_text(json.dumps({'windows':windows},ensure_ascii=False),encoding='utf-8')


def test_request_matches_the_extension_contract(tmp_path):
    _snapshot(tmp_path,[{'id':'gnome:1','title':'终端'},{'id':'gnome:42','title':'论文审核 · DeepSeek Harness'}])
    window=module.snapshot_window(tmp_path)
    assert window=={'id':'gnome:42','title':'论文审核 · DeepSeek Harness'}, '只挑 DSH 页面那个窗口'
    now=1000.0
    result=module.request_gnome_focus(tmp_path,window,now=now)
    assert result['backend']=='gnome' and result['raised'] is True
    payload=json.loads((tmp_path/'focus-request.json').read_text(encoding='utf-8'))
    assert payload['window_id']=='gnome:42', '扩展按稳定窗口编号精确定位'
    assert payload['marker']=='DeepSeek Harness'
    assert payload['title'].startswith('论文审核')
    assert now<payload['expires_at']<=now+3, '只接受短时有效请求'
    assert len(payload['id'])>=16, '一次性编号用于拒绝重放'
    if os.name=='posix':
        assert (tmp_path/'focus-request.json').stat().st_mode&0o777==0o600, '请求文件只给本人可读'


def test_missing_or_unrelated_snapshot_never_writes_a_request(tmp_path,monkeypatch):
    assert module.snapshot_window(tmp_path) is None
    _snapshot(tmp_path,[{'id':'gnome:1','title':'终端'}])
    assert module.snapshot_window(tmp_path) is None
    monkeypatch.setattr(module,'raise_x11',lambda *a,**k:{'backend':'x11','raised':False,'reason':'无 X 窗口'})
    monkeypatch.setattr(module,'raise_windows',lambda *a,**k:{'backend':'win32','raised':False,'reason':'无窗口'})
    result=module.raise_dsh_window(directory=tmp_path)
    assert result['raised'] is False and result['backend']==('win32' if os.name=='nt' else 'x11'), '平台后备不得谎报成功'
    assert not (tmp_path/'focus-request.json').exists(), '没找到窗口就不写请求'


def test_oversized_or_broken_snapshot_is_ignored(tmp_path):
    (tmp_path/'gnome-snapshot.json').write_bytes(b'x'*(module.MAX_SNAPSHOT_BYTES+1))
    assert module.snapshot_window(tmp_path) is None
    (tmp_path/'gnome-snapshot.json').write_text('{不是 JSON',encoding='utf-8')
    assert module.snapshot_window(tmp_path) is None


def _tagged(tmp_path,focused=False):
    _snapshot(tmp_path,[{'id':'gnome:249','title':'论文审核 · DeepSeek Harness [DSH-ab12]','focused':focused}])
    return '[DSH-ab12]'


def test_a_tagged_tab_is_only_claimed_raised_once_the_window_is_really_focused(tmp_path,monkeypatch):
    marker=_tagged(tmp_path,focused=False)
    monkeypatch.setattr(module,'select_browser_tab',lambda value:True)
    monkeypatch.setattr(module,'raise_x11',lambda *a,**k:{'backend':'x11','raised':False,'reason':'无 X 窗口'})
    monkeypatch.setattr(module,'FOCUS_VERIFY_SECONDS',.2)
    result=module.raise_tagged_tab(tmp_path,marker)
    assert result['raised'] is False, '扩展没动作就不能谎报已置前'
    assert '扩展没在运行' in result['reason'] or '扩展没有处理' in result['reason'], result['reason']
    payload=json.loads((tmp_path/'focus-request.json').read_text(encoding='utf-8'))
    assert payload['window_id']=='gnome:249' and payload['marker']==marker, '仍然是按标记精确请求'
    _snapshot(tmp_path,[{'id':'gnome:249','title':'论文审核 · DeepSeek Harness [DSH-ab12]','focused':True}])
    assert module.raise_tagged_tab(tmp_path,marker)['raised'] is True, '窗口真的到前台才报成功'


def test_a_tagged_tab_that_never_appears_is_not_reported_as_raised(tmp_path,monkeypatch):
    monkeypatch.setattr(module,'select_browser_tab',lambda value:True)
    monkeypatch.setattr(module,'raise_x11',lambda *a,**k:{'backend':'x11','raised':False,'reason':'无 X 窗口'})
    monkeypatch.setattr(module,'FOCUS_WINDOW_SECONDS',.1)
    result=module.raise_tagged_tab(tmp_path,'[DSH-missing]')
    assert result['raised'] is False and '快照里也没有对应窗口' in result['reason']
    assert not (tmp_path/'focus-request.json').exists(), '找不到窗口就绝不写请求'


def test_windows_foreground_is_verified_instead_of_assumed(monkeypatch):
    class FakeGui:
        @staticmethod
        def GetForegroundWindow():return 99
    monkeypatch.setitem(sys.modules,'win32gui',FakeGui)
    monkeypatch.setattr(module,'FOCUS_VERIFY_SECONDS',.05)
    assert module.windows_foreground(42) is False, '前台是别的窗口就不能报成功'
    FakeGui.GetForegroundWindow=staticmethod(lambda:42)
    assert module.windows_foreground(42) is True


def test_raise_never_throws_and_survives_a_missing_backend(tmp_path,monkeypatch):
    def explode(*a,**k):raise RuntimeError('X 连接失败')
    monkeypatch.setattr(module,'raise_x11',explode)
    monkeypatch.setattr(module,'raise_windows',explode)
    result=module.raise_dsh_window(directory=tmp_path)
    assert result['raised'] is False and 'X 连接失败' in result['reason'], '置前失败只记录，不抛异常'


def test_another_window_of_the_same_browser_is_not_the_target(tmp_path, monkeypatch):
    """同进程的无关窗口不得作为目标窗口或成功证据。"""
    (tmp_path/'gnome-snapshot.json').write_text(json.dumps({'ts':time.time(),'code_version':module.EXTENSION_CODE_VERSION,
        'windows':[{'id':'gnome:7','title':'某个别的标签页','pid':4242,'focused':True,'minimized':False}]},ensure_ascii=False),encoding='utf-8')
    monkeypatch.setattr(module,'select_browser_tab',lambda value:False)
    monkeypatch.setattr(module,'raise_x11',lambda *a,**k:{'backend':'x11','raised':False,'reason':'无 X 窗口'})
    result=module.raise_tagged_tab(tmp_path,'[DSH-ab12]',pids=[4242])
    assert result['raised'] is False, result
    assert not (tmp_path/module.REQUEST_NAME).exists()


def test_a_failed_activation_ends_without_a_second_request(tmp_path, monkeypatch):
    """未观察到目标获得焦点就结束失败，不凭假设再排入一次激活。"""
    (tmp_path/'gnome-snapshot.json').write_text(json.dumps({'ts':time.time(),'code_version':module.EXTENSION_CODE_VERSION,
        'windows':[{'id':'gnome:9','title':'β 会话 [DSH-ab12]','pid':5150,'focused':False,'minimized':False}]},ensure_ascii=False),encoding='utf-8')
    (tmp_path/'extension-state.json').write_text(json.dumps({'at':time.time(),'code_version':module.EXTENSION_CODE_VERSION}),encoding='utf-8')
    monkeypatch.setattr(module,'select_browser_tab',lambda value:True)
    monkeypatch.setattr(module,'raise_x11',lambda *a,**k:{'backend':'x11','raised':False,'reason':'无 X 窗口'})
    monkeypatch.setattr(module,'wait_for_focus',lambda *a,**k:False)
    result=module.raise_tagged_tab(tmp_path,'[DSH-ab12]',pids=[5150])
    requests=[s for s in result['steps'] if s['step'].startswith('focus-request')]
    assert result['raised'] is False and len(requests)==1, result


def test_extension_health_separates_not_running_from_wrong_version(tmp_path):
    assert module.extension_health(tmp_path)['running'] is False, '没有快照就是没在跑'
    (tmp_path/'gnome-snapshot.json').write_text(json.dumps({'ts':time.time()-600,'code_version':module.EXTENSION_CODE_VERSION,'windows':[]}),encoding='utf-8')
    health=module.extension_health(tmp_path)
    assert health['running'] is False and health['age']>3, health
    (tmp_path/'gnome-snapshot.json').write_text(json.dumps({'ts':time.time(),'code_version':'old-1','windows':[]}),encoding='utf-8')
    (tmp_path/'extension-state.json').write_text(json.dumps({'at':time.time(),'code_version':'old-1','last_error':None}),encoding='utf-8')
    health=module.extension_health(tmp_path)
    assert health['running'] is True and health['version_matches'] is False, health
    (tmp_path/'extension-disabled.json').write_text(json.dumps({'at':time.time(),'code_version':'old-1','uptime_seconds':42}),encoding='utf-8')
    assert module.extension_health(tmp_path)['disabled_uptime']==42, '扩展被停掉（锁屏）要能看出来'


def test_the_focus_request_carries_the_browser_pid(tmp_path):
    window={'id':'gnome:11','title':'β 会话 [DSH-xy]'}
    module.request_gnome_focus(tmp_path,window,'[DSH-xy]',pid=777)
    payload=json.loads((tmp_path/'focus-request.json').read_text(encoding='utf-8'))
    assert payload['pid']==777 and payload['window_id']=='gnome:11'
    module.request_gnome_focus(tmp_path,window,'[DSH-xy]')
    assert 'pid' not in json.loads((tmp_path/'focus-request.json').read_text(encoding='utf-8')), '没有候选进程号时不写这个字段'


def test_browser_process_ids_skips_renderers(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix"))
    class Listing:
        stdout='111\n222\n333\n'
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:Listing())
    cmdlines={111:b'/opt/google/chrome/chrome',222:b'/opt/google/chrome/chrome --type=renderer',333:b'/usr/bin/chromium --type=gpu-process'}
    monkeypatch.setattr(module.Path,'read_bytes',lambda self:cmdlines[int(self.parts[-2])])
    assert module.browser_process_ids()==[111], '只保留浏览器 UI 进程作为候选'


def test_windows_activation_is_nudged_and_verified(monkeypatch):
    state={'foreground':0,'pos':0,'alt':0}
    class Gui:
        @staticmethod
        def IsWindowVisible(hwnd):return True
        @staticmethod
        def GetWindowText(hwnd):return '论文审核 · DeepSeek Harness'
        @staticmethod
        def EnumWindows(visit,_):visit(99,None)
        @staticmethod
        def IsIconic(hwnd):return False
        @staticmethod
        def SetForegroundWindow(hwnd):state['foreground']+=1
        @staticmethod
        def SetWindowPos(*a,**k):state['pos']+=1
    class Con:
        SW_RESTORE=9; HWND_TOP=0; SWP_NOMOVE=2; SWP_NOSIZE=1; SWP_SHOWWINDOW=0x40; VK_MENU=0x12; KEYEVENTF_KEYUP=2
    class Api:
        @staticmethod
        def keybd_event(*a):state['alt']+=1
    monkeypatch.setitem(sys.modules,'win32gui',Gui)
    monkeypatch.setitem(sys.modules,'win32con',Con)
    monkeypatch.setitem(sys.modules,'win32api',Api)
    monkeypatch.setattr(module,'windows_foreground',lambda hwnd,seconds=2.5: state['pos']>0, raising=False)
    result=module.raise_windows()
    assert result['raised'] is True and result['attempts']==2, result
    assert state['pos']==1 and state['alt']==2, '第一次被拒后要用标准两步解除前台锁定再试'


def test_native_focus_is_not_completion_until_own_request_was_consumed(tmp_path,monkeypatch):
    """CDP may focus first; a queued compositor request must not fire after completion."""
    monkeypatch.setattr(module,'focused_window',lambda *a:True)
    (tmp_path/'last-focus.json').write_text(json.dumps({'request_id':'older'}))
    assert not module.wait_for_focus(tmp_path,'gnome:9',seconds=.02,request_id='current')
    (tmp_path/'last-focus.json').write_text(json.dumps({'request_id':'current','acted':True}))
    assert module.wait_for_focus(tmp_path,'gnome:9',seconds=.02,request_id='current')


def test_atspi_tab_search_requests_native_accessibility_before_children(monkeypatch):
    """A default Chrome frame exists before its tab tree is enabled on demand."""
    import focus_demo.atspi_dbus as atspi
    from types import SimpleNamespace
    monkeypatch.setattr(module, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(module,'_select_connected_tab',lambda *_:False)
    monkeypatch.setattr(module,'browser_process_ids',lambda:[123])
    calls=[]
    class Bus:
        def __init__(self,*args):self.deadline=time.monotonic()+4;self.enabled=False
        def close(self):pass
        def call(self,name,path,interface,method,*args):
            calls.append((path,method))
            if method=='ListNames':return [':1.1']
            if method=='GetConnectionUnixProcessID':return 123
            if method=='GetAttributes':self.enabled=True;return {}
            if method=='GetRoleName':return 'application' if path==atspi.ROOT else 'page tab'
            if method=='GetChildren':return [(':1.1','/tab')] if self.enabled else []
            if method=='GetAll':return {'Name':{'data':'[DSH-demand]'}}
            if method=='DoAction':return True
            raise AssertionError(method)
    monkeypatch.setattr(atspi,'Bus',Bus)
    assert module._select_browser_tab('[DSH-demand]') is True
    assert calls.index((atspi.ROOT,'GetAttributes'))<calls.index((atspi.ROOT,'GetChildren'))


def test_isolated_popup_can_load_bounded_tab_worker(tmp_path):
    """The installed popup imports the helper outside the service's sys.path."""
    import subprocess
    import sys
    from pathlib import Path
    helper = Path(__file__).resolve().parents[1] / 'deploy/focus_window.py'
    source = (
        'import importlib.util;'
        f's=importlib.util.spec_from_file_location("focus",{str(helper)!r});'
        'm=importlib.util.module_from_spec(s);s.loader.exec_module(m);'
        'assert m.select_browser_tab("invalid-marker") is False'
    )
    result = subprocess.run([sys.executable, '-I', '-c', source], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_selected_native_identity_survives_stale_window_title(monkeypatch):
    from types import SimpleNamespace
    calls=[]
    monkeypatch.setitem(sys.modules,'win32gui',SimpleNamespace(
        IsWindow=lambda h:True, IsIconic=lambda h:False,
        GetForegroundWindow=lambda:42,
        EnumWindows=lambda *a: (_ for _ in ()).throw(AssertionError('must not rediscover by title')),
        SetForegroundWindow=lambda h:calls.append(h)))
    monkeypatch.setitem(sys.modules,'win32con',SimpleNamespace())
    monkeypatch.setitem(sys.modules,'win32process',SimpleNamespace(GetWindowThreadProcessId=lambda h:(1,123)))
    result=module.raise_windows('[DSH-stale]',target={'window_id':'win:42','pid':123,'selected':True})
    assert result['raised'] and result['window_id']=='win:42'
    assert calls==[], 'already foreground must not be reactivated'


def test_selected_window_identity_is_forwarded(monkeypatch):
    from types import SimpleNamespace
    target={'selected':True,'window_id':'win:42','pid':123,'tab_id':'page-1'}
    monkeypatch.setattr(module,'os',SimpleNamespace(name='nt'))
    monkeypatch.setattr(module,'select_browser_tab',lambda *a:target)
    monkeypatch.setattr(module,'raise_windows',lambda marker,**kw:{'raised':kw.get('target')==target})
    assert module.raise_dsh_window('[DSH-stale]',directory='/tmp')['raised']


def test_cdp_window_mapping_does_not_choose_an_arbitrary_same_process_window(monkeypatch):
    from types import SimpleNamespace
    rectangles={11:(0,0,800,600),22:(100,100,1000,800)}
    monkeypatch.setitem(sys.modules,'win32gui',SimpleNamespace(
        EnumWindows=lambda cb,arg:[cb(h,arg) for h in rectangles],IsWindowVisible=lambda h:True,
        GetClassName=lambda h:'Chrome_WidgetWin_1',GetWindowRect=lambda h:rectangles[h]))
    monkeypatch.setitem(sys.modules,'win32process',SimpleNamespace(GetWindowThreadProcessId=lambda h:(1,123)))
    bounds={'left':100,'top':100,'width':900,'height':700}
    assert module._windows_browser_handle(123,bounds)==22
    rectangles[11]=rectangles[22]
    assert module._windows_browser_handle(123,bounds) is None
    assert module._windows_browser_handle(999,bounds) is None


def test_selected_native_window_cannot_be_reused_by_another_process(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules,'win32gui',SimpleNamespace(IsWindow=lambda h:True))
    monkeypatch.setitem(sys.modules,'win32con',SimpleNamespace())
    monkeypatch.setitem(sys.modules,'win32process',SimpleNamespace(GetWindowThreadProcessId=lambda h:(1,999)))
    result=module.raise_windows('[DSH-stale]',target={'window_id':'win:42','pid':123})
    assert not result['raised'] and result['stage']=='locate'


def test_connected_window_query_failure_allows_native_fallback(monkeypatch):
    from types import SimpleNamespace
    from io import BytesIO
    import urllib.request,psutil,websocket
    import focus_demo.browser_targets as targets
    replies=iter([b'[{"type":"page","title":"[DSH-request]","id":"tab-1"}]',b''])
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:BytesIO(next(replies))))
    monkeypatch.setattr(module,'browser_process_ids',lambda:[123])
    monkeypatch.setattr(psutil,'Process',lambda pid:SimpleNamespace(cmdline=lambda:['chrome','--remote-debugging-port=1234']))
    monkeypatch.setattr(module,'os',SimpleNamespace(name='nt'))
    monkeypatch.setattr(targets,'get',lambda *a:{'webSocketDebuggerUrl':'ws://unused'})
    def unavailable(*args):raise websocket.WebSocketTimeoutException('connection unavailable')
    monkeypatch.setattr(targets,'rpc',unavailable)
    assert module._select_connected_tab('[DSH-request]') is False


def test_linux_connected_selection_does_not_require_websocket(monkeypatch):
    import builtins
    from types import SimpleNamespace
    from io import BytesIO
    import urllib.request,psutil
    original=builtins.__import__
    def without_websocket(name,*args,**kwargs):
        if name=='websocket':raise ModuleNotFoundError(name)
        return original(name,*args,**kwargs)
    replies=iter([b'[{"type":"page","title":"[DSH-request]","id":"tab-1"}]',b''])
    monkeypatch.setattr(builtins,'__import__',without_websocket)
    monkeypatch.setattr(module,'os',SimpleNamespace(name='posix'))
    monkeypatch.setattr(module,'browser_process_ids',lambda:[123])
    monkeypatch.setattr(psutil,'Process',lambda pid:SimpleNamespace(cmdline=lambda:['chrome','--remote-debugging-port=1234']))
    monkeypatch.setattr(urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:BytesIO(next(replies))))
    assert module._select_connected_tab('[DSH-request]') is True
