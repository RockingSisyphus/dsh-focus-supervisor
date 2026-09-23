"""Bringing the DSH window forward is bounded, one-shot and never guesses a window."""
import importlib.util,json,os,sys,time
from pathlib import Path

spec=importlib.util.spec_from_file_location('monitor_focus_window',Path(__file__).resolve().parents[1]/'deploy/focus_window.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
















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


def test_windows_raise_does_not_require_linux_runtime_directory(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(module,'os',SimpleNamespace(name='nt'))
    monkeypatch.setattr(module,'desktop_dir',lambda: (_ for _ in ()).throw(AssertionError('Linux runtime used on Windows')))
    monkeypatch.setattr(module,'select_browser_tab',lambda *args:{'window_id':'win:42','pid':7})
    monkeypatch.setattr(module,'_request_current',lambda *_:True)
    monkeypatch.setattr(module,'raise_windows',lambda marker,target=None:{'backend':'win32','raised':True,'target':target})
    result=module.raise_dsh_window('[DSH-request]',request_context={'id':'request'})
    assert result['raised'] and result['target']=={'window_id':'win:42','pid':7}






def test_extension_health_uses_live_protocol(monkeypatch):
    import focus_demo.desktop_bridge as bridge
    monkeypatch.setattr(bridge,'call',lambda *a:{'running':True,'code_version':bridge.VERSION})
    assert module.extension_health()['version_matches']
    def disconnected(*a):raise RuntimeError('extension disconnected')
    monkeypatch.setattr(bridge,'call',disconnected)
    assert not module.extension_health()['running']


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


def test_focus_dbus_reply_does_not_replace_foreground_observation(tmp_path,monkeypatch):
    import focus_demo.desktop_bridge as bridge
    windows=[{'id':'gnome:9','pid':123,'title':'[DSH-test]','focused':False}]
    actions=[]
    def call(op,payload=None,**kw):
        if op=='snapshot':return {'windows':windows}
        if op=='status':return {'running':True}
        actions.append(payload)
        return {'acted':True,'request_id':payload['id']}
    monkeypatch.setattr(bridge,'call',call)
    monkeypatch.setattr(module,'select_browser_tab',lambda *a:True)
    monkeypatch.setattr(module,'raise_x11',lambda *a:{'raised':False})
    monkeypatch.setattr(module,'FOCUS_VERIFY_SECONDS',.01)
    assert not module.raise_tagged_tab(tmp_path,'[DSH-test]')['raised']
    assert len(actions)==1 and actions[0]['window_id']=='gnome:9'
    windows[0]['focused']=True
    assert module.raise_tagged_tab(tmp_path,'[DSH-test]')['raised']
    assert len(actions)==1  # No repeated activation after completion.


def test_same_pid_other_window_is_not_a_focus_target(tmp_path,monkeypatch):
    import focus_demo.desktop_bridge as bridge
    def call(op,*a,**kw):
        if op=='status':return {'running':True}
        if op=='snapshot':return {'windows':[{'id':'gnome:4','pid':123,'title':'unrelated','focused':True}]}
        raise AssertionError('must not activate unrelated window')
    monkeypatch.setattr(bridge,'call',call)
    monkeypatch.setattr(module,'select_browser_tab',lambda *a:False)
    monkeypatch.setattr(module,'raise_x11',lambda *a:{'raised':False})
    monkeypatch.setattr(module,'FOCUS_WINDOW_SECONDS',.01)
    assert not module.raise_tagged_tab(tmp_path,'[DSH-missing]',pids=[123])['raised']


def test_disconnected_bridge_reports_failure(tmp_path,monkeypatch):
    import focus_demo.desktop_bridge as bridge
    def broken(*a,**kw):raise RuntimeError('desktop disconnected')
    monkeypatch.setattr(bridge,'call',broken)
    result=module.request_gnome_focus(tmp_path,{'id':'gnome:7','title':'test'},pid=123)
    assert not result['raised'] and 'disconnected' in result['reason']
