"""Bring the already open DSH browser window forward. Best effort by design.

Wayland-native windows (Chrome on a Wayland session is one) cannot be enumerated or
raised by X11 tools, so on Linux the compositor itself has to do it: our GNOME Shell
extension accepts a bounded D-Bus request. X11/XWayland windows are raised directly through Xlib, and Windows
through the top-level window that carries the DSH title.

Every path returns an observed result. The caller reports native failure separately
from a session switch that already happened.
"""
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

# Popup helpers run with Python isolation, outside the service's import path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MARKER = 'DeepSeek Harness'
EXTENSION_CODE_VERSION = 'dafeiyu-13'  # 与 gnome-extension/extension.js 的 CODE_VERSION 必须一致
REQUEST_TTL_SECONDS = 2
FOCUS_WINDOW_SECONDS = 1.5  # how long the tagged window may take to appear in the snapshot
FOCUS_VERIFY_SECONDS = 2.5  # how long the compositor may take to report it focused
FOCUS_POLL_SECONDS = .1


def desktop_dir():
    from focus_demo.desktop_bridge import runtime_directory
    return runtime_directory()


def snapshot_document(directory):
    """The extension's last snapshot document (carries ts/backend), or {}."""
    from focus_demo.desktop_bridge import call
    return call('snapshot')


def _snapshot(directory):
    """The extension's last window list, or an empty list when it is missing or broken."""
    return [window for window in (snapshot_document(directory).get('windows') or []) if isinstance(window, dict)]


def snapshot_window(directory, marker=MARKER):
    """First window in the extension snapshot whose title carries the marker."""
    for window in _snapshot(directory):
        title = str(window.get('title') or '')
        if marker in title and window.get('id'):
            return {'id': str(window['id']), 'title': title}
    return None


def browser_process_ids():
    """Browser UI processes restrict tab search; PID alone never identifies a target."""
    names = ('chrome', 'chromium', 'msedge', 'epiphany', 'firefox')
    pids = []
    if os.name == 'nt':
        try:
            import psutil
        except ImportError:
            return []
        wanted = {name + '.exe' for name in names}
        for process in psutil.process_iter(['pid', 'name']):
            if (process.info.get('name') or '').lower() in wanted:
                pids.append(int(process.info['pid']))
        return pids
    for name in names:
        try:
            listing = subprocess.run(['pgrep', '-x', name], capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        for line in (listing.stdout or '').split():
            try:
                pid = int(line)
            except ValueError:
                continue
            try:
                cmdline = Path('/proc/%d/cmdline' % pid).read_bytes()
            except OSError:
                continue
            if b'--type=' in cmdline or b'--renderer' in cmdline:   # 只保留 UI 进程
                continue
            pids.append(pid)
    return sorted(set(pids))


def extension_health(directory=None):
    """Whether the Shell is really running this version, and why it is not, when it is not."""
    from focus_demo.desktop_bridge import call
    try:
        state=call('status')
        return {**state,'expected':EXTENSION_CODE_VERSION,'version_matches':True}
    except Exception as error:
        return {'running':False,'version_matches':False,'expected':EXTENSION_CODE_VERSION,'last_error':str(error)}


def focused_window(directory, window_id):
    """Whether the compositor currently reports that exact window as the focused one."""
    for window in _snapshot(directory):
        if str(window.get('id') or '') == window_id:
            return bool(window.get('focused'))
    return False


def wait_for_focus(directory, window_id, seconds=FOCUS_VERIFY_SECONDS, request_id=None):
    """Wait, bounded, until the compositor reports the window focused."""
    deadline = time.monotonic() + seconds
    while True:
        if focused_window(directory, window_id):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(FOCUS_POLL_SECONDS)


def request_gnome_focus(directory, window, marker=MARKER, now=None, pid=None):
    """Write the one-shot request the GNOME extension polls (same shape as close-request).

    `pid` is the fallback anchor: when the window title does not carry the marker (a
    background tab, or a browser that does not follow page titles) the extension authorises
    the activation by matching the window's client pid instead.
    """
    now = time.time() if now is None else now
    payload = {'id': uuid.uuid4().hex, 'window_id': window['id'], 'marker': marker,
        'title': window['title'][:120], 'expires_at': now + REQUEST_TTL_SECONDS}
    if pid:
        payload['pid'] = int(pid)
    from focus_demo.desktop_bridge import call
    try:
        result=call('focus',payload)
        return {'backend':'gnome','raised':bool(result.get('acted')),'reason':result.get('reason'),'id':payload['id'],'window_id':window['id'],'result':result}
    except Exception as error:
        return {'backend':'gnome','raised':False,'reason':str(error)}


def raise_x11(marker=MARKER):
    """Raise and focus an X11/XWayland window by title, without guessing identity."""
    try:
        from Xlib import X, display, protocol
    except ImportError:
        return {'backend': 'x11', 'raised': False, 'reason': '缺少 python-xlib'}
    try:
        connection = display.Display()
    except Exception as error:
        return {'backend': 'x11', 'raised': False, 'reason': '无法连接 X 显示：' + str(error)}
    try:
        root = connection.screen().root
        clients = root.get_full_property(connection.intern_atom('_NET_CLIENT_LIST'), X.AnyPropertyType)
        for identifier in clients.value if clients else []:
            window = connection.create_resource_object('window', int(identifier))
            title = ''
            for atom in ('_NET_WM_NAME', 'WM_NAME'):
                value = window.get_full_property(connection.intern_atom(atom), X.AnyPropertyType)
                if value and value.value:
                    raw = value.value
                    title = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
                    if title:
                        break
            if marker not in title:
                continue
            window.configure(stack_mode=X.Above)
            # Window managers ignore a bare XSetInputFocus from a client and enforce their
            # own focus policy, so ask through EWMH; keep the direct call as a fallback for
            # bare X servers without a window manager.
            request = protocol.event.ClientMessage(window=window, client_type=connection.intern_atom('_NET_ACTIVE_WINDOW'),
                data=(32, [2, X.CurrentTime, 0, 0, 0]))
            root.send_event(request, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
            window.set_input_focus(X.RevertToParent, X.CurrentTime)
            connection.sync()
            return {'backend': 'x11', 'raised': True, 'reason': '已请求把 X11 窗口置前'}
        return {'backend': 'x11', 'raised': False, 'reason': 'X11 窗口中未找到 DSH 页面'}
    except Exception as error:
        return {'backend': 'x11', 'raised': False, 'reason': str(error)}
    finally:
        try:
            connection.close()
        except Exception:
            pass


def windows_foreground(hwnd, seconds=FOCUS_VERIFY_SECONDS):
    """Wait, bounded, until Windows really reports that window as the foreground one."""
    try:
        import win32gui
    except ImportError:
        return False
    deadline = time.monotonic() + seconds
    while True:
        try:
            if int(win32gui.GetForegroundWindow()) == int(hwnd):
                return True
        except Exception:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(FOCUS_POLL_SECONDS)


def _win32_nudge(hwnd, win32con, win32gui):
    """Windows 拒绝程序化前台请求时的标准两步：先提到最上层，再用一次极小键输入解除前台锁定。

    This is a normal, documented desktop technique (SetWindowPos + a key tap), not a bypass
    of a permission: it only removes the "foreground lock" Windows keeps for background
    processes. Whether it worked is still decided by GetForegroundWindow, below.
    """
    try:
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
    except Exception:
        pass
    try:
        import win32api
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    except Exception:
        pass


def raise_windows(marker=MARKER, target=None):
    """Restore and foreground the DSH browser window."""
    try:
        import win32con
        import win32gui
    except ImportError:
        return {'backend': 'win32', 'raised': False, 'reason': '缺少 pywin32'}
    try:
        if target and target.get('window_id'):
            import win32process
            hwnd=int(target['window_id'].split(':')[-1])
            if not win32gui.IsWindow(hwnd) or win32process.GetWindowThreadProcessId(hwnd)[1]!=target['pid']:
                return {'backend':'win32','raised':False,'stage':'locate','reason':'已选标签对应的原生窗口已消失或改变'}
        else:
            matched = []

            def visit(hwnd, _):
                if win32gui.IsWindowVisible(hwnd) and marker in win32gui.GetWindowText(hwnd):
                    matched.append(hwnd)
                return True

            deadline=time.monotonic()+FOCUS_WINDOW_SECONDS
            while True:
                win32gui.EnumWindows(visit,None)
                if matched or time.monotonic()>=deadline:break
                time.sleep(FOCUS_POLL_SECONDS)
            if not matched:
                return {'backend': 'win32', 'raised': False, 'stage':'locate', 'reason': '无法确定目标 DSH 窗口身份'}
            hwnd = matched[0]
        if not win32gui.IsIconic(hwnd) and windows_foreground(hwnd, seconds=0):
            return {'backend':'win32','raised':True,'reason':'目标窗口已经在前台','attempts':0,'window_id':'win:'+str(hwnd)}
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        for attempt in range(2):
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                # Windows refuses a programmatic foreground request from a background process;
                # this still lifts the window to the top of the stacking order.
                win32gui.BringWindowToTop(hwnd)
            if windows_foreground(hwnd, seconds=1.5):
                return {'backend': 'win32', 'raised': True, 'reason': '已激活 Windows 窗口', 'attempts': attempt + 1,'window_id':'win:'+str(hwnd)}
            if attempt == 0:
                _win32_nudge(hwnd, win32con, win32gui)   # 第一次被拒：解除前台锁定后再试一次
        return {'backend': 'win32', 'raised': False, 'reason': 'Windows 没有把该窗口切到前台'}
    except Exception as error:
        return {'backend': 'win32', 'raised': False, 'reason': str(error)}


def _request_current(context):
    if not context:return True
    import urllib.request
    try:
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(context['origin']+'/focus/open-request?id='+context['id'],timeout=1) as response:value=json.load(response)
        return not value.get('expired') and value.get('status') not in ('completed','failed')
    except (OSError,ValueError):return False


def select_browser_tab(marker,request_context=None):
    """Bound blocking native UIA/AT-SPI tab selection to one disposable worker."""
    import sys
    try:
        from focus_demo.process_worker import run_worker
        result=run_worker([sys.executable,'-I',str(Path(__file__).resolve()),'--select-tab',marker,json.dumps(request_context)],capture_output=True,text=True,timeout=5)
        return json.loads(result.stdout).get('selected',False) if result.returncode==0 else False
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired):return False


def _select_browser_tab(marker,request_context=None):
    if marker!=MARKER and (not marker.startswith('[DSH-') or not marker.endswith(']')):return False
    from collections import deque
    if os.name == 'nt':
        import win32gui,win32process
        from pywinauto import Desktop
        pids=set(browser_process_ids());handles=[]
        win32gui.EnumWindows(lambda h,_:handles.append(h) if win32gui.IsWindowVisible(h) and win32process.GetWindowThreadProcessId(h)[1] in pids else None,None)
        for hwnd in handles:
            # UIA omits a minimized Chromium tab strip. Reveal this candidate without
            # activating it, inspect only browser chrome, then restore its prior state
            # when the exact marked tab is not there.
            import win32con
            minimized=bool(win32gui.IsIconic(hwnd));selected=False
            if minimized:win32gui.ShowWindow(hwnd,win32con.SW_SHOWNOACTIVATE)
            try:
                deadline=time.monotonic()+1
                while time.monotonic()<deadline:
                    queue=deque([Desktop(backend='uia').window(handle=hwnd).wrapper_object()])
                    while queue and time.monotonic()<deadline:
                        control=queue.popleft();kind=control.element_info.control_type
                        if kind=='Document':continue
                        if kind=='TabItem' and marker in control.window_text():
                            if not _request_current(request_context):return False
                            control.select();selected=True
                            return {'selected':True,'window_id':'win:'+str(hwnd),'pid':win32process.GetWindowThreadProcessId(hwnd)[1],'source':'uia'}
                        queue.extend(control.children())
                    if not minimized:break
                    time.sleep(.05)
            finally:
                if minimized and not selected:win32gui.ShowWindow(hwnd,win32con.SW_SHOWMINNOACTIVE)
        return False
    from focus_demo.atspi_dbus import Bus,ACCESSIBLE,ROOT
    bus=Bus(4)
    try:
        names=bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames')
        wanted=set(browser_process_ids());owners=[]
        for name in names:
            if not name.startswith(':'):continue
            try:pid=bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID','s',name)
            except RuntimeError:continue
            if pid in wanted:owners.append(name)
        # Chrome exposes frame shells until an assistive client requests extended
        # properties. This standard query enables its native tab tree on demand;
        # it does not require a screen reader or a browser startup flag.
        for name in owners:
            try:bus.call(name,ROOT,ACCESSIBLE,'GetAttributes')
            except RuntimeError:pass
        queue=deque((name,ROOT,0) for name in owners)
        seen=set()
        while queue and time.monotonic()<bus.deadline:
            name,path,depth=queue.popleft()
            if (name,path) in seen:continue
            seen.add((name,path))
            try:
                role=bus.call(name,path,ACCESSIBLE,'GetRoleName')
                if role=='page tab':
                    props=bus.call(name,path,'org.freedesktop.DBus.Properties','GetAll','s',ACCESSIBLE)
                    title=props.get('Name',{});title=title.get('data','') if isinstance(title,dict) else title
                    if marker in str(title):
                        if not _request_current(request_context):return False
                        return bool(bus.call(name,path,'org.a11y.atspi.Action','DoAction','i',0))
                if depth<10 and role not in ('document web','document frame'):
                    queue.extend((n,p,depth+1) for n,p in bus.call(name,path,ACCESSIBLE,'GetChildren'))
            except (RuntimeError,TimeoutError):continue
        return False
    finally:bus.close()


def _locate_window(directory, marker, pids, wait=False):
    """Locate the selected target by its unique request marker."""
    deadline=time.monotonic()+(FOCUS_WINDOW_SECONDS if wait else 0)
    while True:
        found=snapshot_window(directory,marker)
        if found:return found,'title-marker'
        if time.monotonic()>=deadline:return None,None
        time.sleep(FOCUS_POLL_SECONDS)


def _extension_hint(health):
    """A precise reason for "the extension did not act", so it is not guessed at."""
    if not health.get('running'):
        return '（扩展没在运行：Shell 里可能还是旧代码，或它刚被停掉——例如锁屏；快照年龄 ' + str(health.get('age')) + ' 秒）'
    if not health.get('version_matches'):
        return '（Shell 里跑的是旧版扩展 ' + str(health.get('code_version')) + '，需要 ' + str(health.get('expected')) + '，注销重登一次即可）'
    return ''


def raise_tagged_tab(directory, marker, pids=None,request_context=None):
    """Select the page tab tagged with this marker and prove its window came forward.

    Selecting the tab is not evidence: a compositor may refuse the activation, and the GNOME
    extension only acts while the running Shell has code that handles the request. The
    fresh compositor snapshot is the arbiter, and every step is kept
    so a failure can be read instead of guessed at.
    """
    steps = []
    health = extension_health(directory)
    pids = list(pids or [])
    already, how = _locate_window(directory, marker, pids)
    if already and focused_window(directory, already['id']):
        steps.append({'step': 'already-focused', 'ok': True, 'window_id': already['id'], 'located_by': how})
        return {'backend': 'gnome', 'raised': True, 'reason': '目标窗口已经在前台', 'steps': steps}
    selected = False
    try:
        selected = select_browser_tab(marker,request_context) if request_context else select_browser_tab(marker)
    except Exception:
        selected = False
    steps.append({'step': 'browser-tab-select', 'ok': bool(selected)})
    if not _request_current(request_context):return {'raised':False,'reason':'唤回已被替代或结束','steps':steps}
    direct = raise_x11(marker)
    if direct.get('raised'):
        direct['steps'] = steps + list(direct.get('steps') or [])
        return direct
    window, how = _locate_window(directory, marker, pids, wait=True)
    if not window:
        reason = ('已请求选中该标签页，' if selected else '未能选中该标签页，') + '扩展快照里也没有对应窗口' + _extension_hint(health)
        return {'backend': 'gnome', 'raised': False, 'reason': reason, 'steps': steps, 'extension_health': health}
    if focused_window(directory,window['id']):
        steps.append({'step':'selected-and-focused','ok':True,'window_id':window['id']})
        return {'backend':'gnome','raised':True,'reason':'选中标签后目标窗口已在前台','steps':steps}
    pid = window.get('pid')
    request = request_gnome_focus(directory, window, marker, pid=pid)
    steps.append({'step': 'focus-request', 'ok': bool(request.get('raised')), 'window_id': window['id'],
                  'pid': pid, 'located_by': how, 'request_id': request.get('id')})
    if not request.get('raised'):
        request['steps'] = steps
        return request
    if wait_for_focus(directory, window['id'],request_id=request.get('id')):
        steps.append({'step': 'verify', 'ok': True})
        return {'backend': 'gnome', 'raised': True, 'reason': '已把目标窗口置前', 'steps': steps}
    last = request.get('result',{})
    acted = bool(last) and last.get('request_id') == request.get('id')
    steps.append({'step': 'verify', 'ok': False, 'extension_acted': acted})
    if not health.get('running'):
        reason = '扩展没在运行，无法激活窗口' + _extension_hint(health)
    elif not acted:
        reason = '扩展没有处理这次置前请求'
    else:
        reason = '扩展执行了激活，但合成器没有把焦点给这个窗口'
    return {'backend': 'gnome', 'raised': False, 'reason': reason, 'steps': steps,
            'extension_health': health, 'last_focus': last}



def wake_existing_dsh_window():
    """Wake an existing DSH tab before its frozen page is asked to claim.

    A discarded/frozen browser page cannot answer the handoff until its native
    window is restored. The compositor window ID (or HWND) is selected from a
    fresh snapshot and independently verified after activation.
    """
    if os.name == 'nt':
        try:
            import win32gui,win32process
            pids=set(browser_process_ids());matches=[]
            def visit(hwnd,_):
                if win32gui.IsIconic(hwnd) and MARKER in win32gui.GetWindowText(hwnd):
                    pid=win32process.GetWindowThreadProcessId(hwnd)[1]
                    if pid in pids:matches.append((hwnd,pid))
            win32gui.EnumWindows(visit,None)
            if matches:
                hwnd,pid=matches[0]
                target={'window_id':'win:'+str(hwnd),'pid':pid}
            else:
                selected=select_browser_tab(MARKER)
                if not selected:return {'found':False}
                if not isinstance(selected,dict) or not selected.get('window_id'):
                    return {'found':True,'raised':False,'reason':'已选中 DSH 标签，但无法关联原生窗口'}
                target=selected
            return {'found':True,**raise_windows(MARKER,target=target)}
        except Exception as error:
            return {'found':False,'reason':str(error)}
    try:
        directory=desktop_dir()
        windows=[w for w in _snapshot(directory) if w.get('id') and w.get('minimized')
                 and MARKER in str(w.get('title') or '')]
        if not windows:
            if not select_browser_tab(MARKER):return {'found':False}
            window,_=_locate_window(directory,MARKER,[],wait=True)
            if not window:
                return {'found':True,'raised':False,'reason':'已选中 DSH 标签，但无法关联原生窗口'}
            windows=[window]
        window=windows[0]
        target={'id':str(window['id']),'title':str(window['title'])}
        if focused_window(directory,target['id']):
            return {'found':True,'raised':True,'window_id':target['id'],'reason':'旧 DSH 窗口已在前台'}
        result=request_gnome_focus(directory,target,MARKER,pid=window.get('pid'))
        if not result.get('raised'):
            return {'found':True,'raised':False,'window_id':target['id'],
                    'reason':result.get('reason') or '桌面接口未恢复窗口'}
        raised=wait_for_focus(directory,target['id'])
        return {'found':True,'raised':raised,'window_id':target['id'],
                'reason':'旧 DSH 窗口已恢复' if raised else '窗口恢复请求已执行，但没有获得焦点'}
    except Exception as error:
        return {'found':False,'reason':str(error)}


def raise_dsh_window(marker=MARKER, directory=None, pids=None,request_context=None):
    """Select and verify the exact request target; return observed failure details."""
    try:
        if os.name == 'nt':
            selected=select_browser_tab(marker,request_context) if marker.startswith('[DSH-') else False
            if not _request_current(request_context):return {'raised':False,'reason':'唤回已被替代或结束'}
            result=raise_windows(marker,target=selected if isinstance(selected,dict) else None)
            result['selection']=selected
            return result
        target = Path(directory) if directory else desktop_dir()
        if marker.startswith('[DSH-'):
            return raise_tagged_tab(target, marker, pids=pids,request_context=request_context)
        # An X11/XWayland window can be raised directly and the result is observable; a
        # Wayland-native window is invisible there, so fall back to the compositor.
        direct = raise_x11(marker)
        if direct.get('raised'):
            return direct
        window = snapshot_window(target, marker)
        if window:
            return request_gnome_focus(target, window, marker)
        return direct
    except Exception as error:
        return {'backend': 'none', 'raised': False, 'reason': str(error)}


if __name__ == '__main__':
    import sys
    result={'selected':_select_browser_tab(sys.argv[2],json.loads(sys.argv[3]) if len(sys.argv)>3 else None)} if len(sys.argv)>2 and sys.argv[1]=='--select-tab' else raise_dsh_window()
    print(json.dumps(result, ensure_ascii=False))
