"""Identify and close ordinary Chromium tabs through the OS accessibility tree.

The report stores the provider's tab identity, not a title or a debugging target.
Both adapters only inspect browser chrome; they never turn on a debug endpoint.
"""
import sys
import time
from collections import deque


def _browser_windows(windows):
    tokens=('chrome', 'chromium', 'msedge', 'microsoft edge')
    return [w for w in windows if any(token in ' '.join(str(w.get('process',{}).get(key,'')) for key in ('name','exe')).lower()+' '+str(w.get('app','')).lower() for token in tokens)]


def _linux(windows):
    from .atspi_dbus import Bus, ACCESSIBLE, ROOT
    from .ui_probe import match_windows
    browser=_browser_windows(windows)
    result={'tabs':[], 'windows_scanned':[], 'errors':[]}
    if not browser:return result
    bus=Bus(2.6)
    try:
        names=bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames')
        wanted={w['pid'] for w in browser}
        owners={pid:[] for pid in wanted}
        for name in names:
            if not name.startswith(':'):continue
            try:
                pid=bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID','s',name)
            except RuntimeError:continue
            if pid in owners:owners[pid].append(name)
        for pid, belonging in owners.items():
            candidates=[]
            for owner in belonging:
                try:children=bus.call(owner,ROOT,ACCESSIBLE,'GetChildren')
                except RuntimeError:continue
                for name,path in children[:64]:
                    try:
                        rect=bus.call(name,path,'org.a11y.atspi.Component','GetExtents','u',0)
                        props=bus.call(name,path,'org.freedesktop.DBus.Properties','GetAll','s',ACCESSIBLE)
                        candidates.append({'node':(name,path),'rect':rect,'title':props.get('Name',{}).get('data','')})
                    except RuntimeError:continue
            associated=match_windows([w for w in browser if w['pid']==pid],candidates)
            for window in (w for w in browser if w['pid']==pid):
                match=associated.get(window['id'])
                if not match or 'node' not in match:
                    result['errors'].append({'window_id':window['id'],'reason':'AT-SPI 顶层窗口无法关联',
                        'native_rect':window.get('buffer_rect') or window.get('rect'),
                        'accessible_rects':[candidate['rect'] for candidate in candidates[:8]]})
                    continue
                queue=deque([match['node']]);visited=set();count=0;complete=True
                try:
                    while queue and count<650:
                        name,path=queue.popleft()
                        if (name,path) in visited:continue
                        visited.add((name,path));count+=1
                        try:role=bus.call(name,path,ACCESSIBLE,'GetRole')
                        except RuntimeError:continue
                        if role==37:  # ATSPI_ROLE_PAGE_TAB
                            try:
                                state=bus.call(name,path,ACCESSIBLE,'GetState')
                                selected=bool(state and state[0] & (1<<23))
                                props=bus.call(name,path,'org.freedesktop.DBus.Properties','GetAll','s',ACCESSIBLE)
                                result['tabs'].append({'tab_id':'atspi:'+name+':'+path,
                                    'native_tab':{'owner':name,'path':path},'window_id':window['id'],
                                    'pid':pid,'title':props.get('Name',{}).get('data',''),'selected':selected})
                            except RuntimeError:pass
                            continue
                        try:
                            role_name=bus.call(name,path,ACCESSIBLE,'GetRoleName')
                            if 'document' in role_name:continue
                            queue.extend(bus.call(name,path,ACCESSIBLE,'GetChildren')[:100])
                        except RuntimeError:continue
                    if queue:complete=False
                except TimeoutError:complete=False
                if complete:result['windows_scanned'].append(window['id'])
                else:result['errors'].append({'window_id':window['id'],'reason':'AT-SPI 标签遍历未完成','visited':count})
    finally:bus.close()
    return result


def _windows(windows):
    import ctypes
    from pywinauto import Desktop
    from ctypes import wintypes
    browser=_browser_windows(windows)
    result={'tabs':[], 'windows_scanned':[], 'errors':[]}
    user=ctypes.WinDLL('user32',use_last_error=True)
    for window in browser:
        hwnd=int(window.get('native_id') or window['id'].split(':')[-1])
        pid=wintypes.DWORD()
        user.GetWindowThreadProcessId(wintypes.HWND(hwnd),ctypes.byref(pid))
        if pid.value!=int(window['pid']):continue
        if user.IsIconic(wintypes.HWND(hwnd)):
            result['errors'].append({'window_id':window['id'],'reason':'窗口已最小化，标签列表不可观察'})
            continue
        try:
            root=Desktop(backend='uia').window(handle=hwnd)
            for tab in root.descendants(control_type='TabItem'):
                identity=tuple(int(v) for v in tab.element_info.runtime_id)
                try:selected=bool(tab.iface_selection_item.CurrentIsSelected)
                except Exception:selected=False
                result['tabs'].append({'tab_id':'uia:'+','.join(map(str,identity)),
                    'native_tab':{'runtime_id':list(identity)},'window_id':window['id'],
                    'pid':window['pid'],'title':tab.window_text(),'selected':selected})
            result['windows_scanned'].append(window['id'])
        except Exception as error:
            result['errors'].append({'window_id':window['id'],'reason':str(error)[:180]})
    return result


def capture(windows, include_background=False):
    result=_windows(windows) if sys.platform=='win32' else _linux(windows)
    if not include_background:result['tabs']=[tab for tab in result['tabs'] if tab['selected']]
    return result


def _click_linux(tab):
    from .atspi_dbus import Bus,ACCESSIBLE
    node=tab['native_tab'];bus=Bus(1.2)
    try:
        if bus.call(node['owner'],node['path'],ACCESSIBLE,'GetRole')!=37:
            return {'requested':False,'reason':'目标标签对象已变化'}
        for child in bus.call(node['owner'],node['path'],ACCESSIBLE,'GetChildren'):
            try:
                role=bus.call(*child,ACCESSIBLE,'GetRoleName')
                if role not in ('push button','button'):continue
                props=bus.call(*child,'org.freedesktop.DBus.Properties','GetAll','s',ACCESSIBLE)
                label=props.get('Name',{}).get('data','').lower()
                if '关闭' not in label and 'close' not in label:continue
                return {'requested':bool(bus.call(*child,'org.a11y.atspi.Action','DoAction','i',0))}
            except RuntimeError:continue
        return {'requested':False,'reason':'目标标签没有可用的原生关闭按钮'}
    finally:bus.close()


def _click_windows(tab):
    from pywinauto import Desktop
    hwnd=int(tab['native_window_id'].split(':')[-1])
    root=Desktop(backend='uia').window(handle=hwnd)
    target=tuple(tab['native_tab']['runtime_id'])
    for item in root.descendants(control_type='TabItem'):
        if tuple(int(v) for v in item.element_info.runtime_id)!=target:continue
        for button in item.children(control_type='Button'):
            label=button.window_text().lower()
            if '关闭' in label or 'close' in label:
                button.invoke()
                return {'requested':True}
        return {'requested':False,'reason':'目标标签没有可用的原生关闭按钮'}
    return {'requested':False,'reason':'目标标签对象已变化'}


def observe(expected):
    window_id=expected.get('native_window_id')
    if not window_id or not expected.get('native_tab'):
        return {'closed':False,'reason':'报告没有原生标签身份'}
    node=expected['native_tab']
    if node.get('owner') and node.get('path'):
        from .atspi_dbus import Bus,ACCESSIBLE
        bus=Bus(1.2)
        try:
            try:
                role=bus.call(node['owner'],node['path'],ACCESSIBLE,'GetRole')
                if role!=37:return {'closed':True,'tab_id':expected.get('tab_id')}
                state=bus.call(node['owner'],node['path'],ACCESSIBLE,'GetState')
                if not state:return {'closed':False,'reason':'无法读取目标标签状态'}
                return {'closed':bool(state[0] & (1<<6)), 'tab_id':expected.get('tab_id')}
            except (RuntimeError,TimeoutError) as error:
                if 'org.freedesktop.DBus.Error.UnknownObject' in str(error):
                    return {'closed':True,'tab_id':expected.get('tab_id')}
                return {'closed':False,'reason':'无法读取目标标签对象：'+str(error)[:160]}
        finally:bus.close()
    window={'id':window_id,'pid':expected['process']['pid'],'process':expected['process'],
            'app':expected.get('app','browser'),'title':expected.get('window_title',''),
            'rect':expected.get('window_rect') or [0,0,0,0],
            'buffer_rect':expected.get('window_buffer_rect')}
    state=capture([window],include_background=True)
    if window_id not in state['windows_scanned']:
        return {'closed':False,'reason':'无法独立读取原生标签列表','errors':state['errors']}
    return {'closed':not any(tab['tab_id']==expected.get('tab_id') for tab in state['tabs']),
            'tab_id':expected.get('tab_id')}


def close(expected):
    activation=None
    if sys.platform.startswith('linux'):
        from .desktop_bridge import call
        try:
            activation=call('focus',{'window_id':expected['native_window_id'],
                                     'pid':expected['process']['pid'],'expires_at':time.time()+2})
        except Exception as error:
            activation={'acted':False,'reason':str(error)}
    elif sys.platform=='win32':
        import ctypes
        from ctypes import wintypes
        hwnd=int(expected['native_window_id'].split(':')[-1])
        user=ctypes.WinDLL('user32',use_last_error=True)
        pid=wintypes.DWORD()
        user.GetWindowThreadProcessId(wintypes.HWND(hwnd),ctypes.byref(pid))
        if pid.value==expected['process']['pid'] and user.IsIconic(wintypes.HWND(hwnd)):
            user.ShowWindow(wintypes.HWND(hwnd),9)  # SW_RESTORE; UIA cannot list minimized tabs.
            activation={'restored':not bool(user.IsIconic(wintypes.HWND(hwnd)))}
    before=observe(expected)
    if before.get('closed'):return {**before,'already_closed':True,'activation':activation}
    if before.get('reason'):return {**before,'activation':activation}
    attempted=(_click_windows if sys.platform=='win32' else _click_linux)(expected)
    if not attempted.get('requested'):return {'closed':False,**attempted,'activation':activation}
    deadline=time.monotonic()+2.1
    while time.monotonic()<deadline:
        fact=observe(expected)
        if fact.get('closed'):return {**fact,'requested':True,'activation':activation}
        if fact.get('reason'):return {**fact,'requested':True,'activation':activation}
        time.sleep(.08)
    return {'closed':False,'requested':True,'activation':activation,'reason':'原生关闭后标签仍存在'}
