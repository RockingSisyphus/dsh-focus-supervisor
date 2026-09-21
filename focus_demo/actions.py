"""通用窗口动作：最小化已审核窗口，或在最后手段下结束已审核进程；不执行模型给出的任何命令。"""
import ctypes  # Windows 原生窗口接口。
import os  # 防止针对监督器自身。
import time  # 有界等待实际结果。
import uuid  # 绑定一次性 GNOME 请求。
from .common import write_json  # 固定目录中的有限请求。
from .platforms import process_info  # 核实进程生命周期。


def force_close_authorization(collector, expected):  # 功能：最后手段只核对进程生命周期。
    process = expected.get('process') or {}  # 身份来自已审证据，不重新取证窗口。
    pid, identity = process.get('pid') or expected.get('pid'), process.get('identity')  # PID 可被复用，身份才可信。
    if not pid or not identity: return {'authorized': False, 'reason': '缺少进程身份，拒绝强杀'}  # 无法核实就不动手。
    live_info = process_info(pid)
    if live_info.get('error') not in (None, 'NoSuchProcess', 'ZombieProcess'):return {'authorized':False,'reason':'无法读取进程身份：'+live_info['error']}
    live = live_info.get('identity')  # 目标可能已经被关掉了。
    if not live: return {'authorized': True, 'already_closed': True, 'pid': pid, 'identity': identity}  # 已经不在了等于无需强杀。
    if live != identity:  # PID 可能已被系统回收另作他用。
        fresh = collector._capture() if collector is not None else None  # 只在身份对不上时才重新看一次现场。
        gone = fresh is not None and fresh.get('desktop',{}).get('available',False) and not any(w.get('id') == (expected.get('native_window_id') or expected.get('id')) for w in (fresh.get('desktop') or {}).get('windows', []))
        if gone: return {'authorized': True, 'already_closed': True, 'pid': pid, 'identity': identity}  # 窗口已经没了，要关的东西不存在了。
        return {'authorized': False, 'reason': '进程生命周期已改变，拒绝强杀（期望 %s，实际 %s）' % (identity, live)}  # 窗口还在但不是那个进程：不误杀。
    return {'authorized': True, 'pid': pid, 'identity': identity}  # 授权精确到这一次进程生命周期。


def request_window_minimize(collector, expected):  # 功能：最小化一个已审核窗口；门禁与强杀一致，另加"尚未最小化"。
    if expected.get('kind')=='browser_tab':
        if not expected.get('native_window_id'):return {'minimized':False,'reason':'标签没有关联的原生窗口'}
        expected={**expected,'id':expected['native_window_id']}
    with collector.lock:  # 与采样连接串行使用，避免混乱。
        if collector.details: collector.details.last = 0  # 动作复核不能只沿用旧的缓存。
        fresh = collector._capture()  # 重新核实操作时的窗口身份。
        if not fresh.get('desktop',{}).get('available'):return {'minimized':False,'reason':'原生窗口状态不可用'}
        current = next((w for w in fresh['desktop']['windows'] if w['id'] == expected.get('id')), None)  # 精确到一个 GUI 窗口。
        if not current: return {'minimized': True, 'already_gone': True, 'window_id': expected.get('id'), 'reason': '目标窗口已不存在，无需最小化'}  # 要最小化的东西没了。
        if current.get('supervisor_owned') or current.get('pid') == os.getpid(): return {'minimized': False, 'reason': '目标属于监督器，拒绝操作'}  # 与强杀同一条自我保护。
        live = process_info(current.get('pid')).get('identity')  # 门禁与强杀同源：拿"已审证据里的进程身份"对"此刻的进程身份"。
        identity = (expected.get('process') or {}).get('identity')  # 不能拿实时值和实时值自己比，那等于没有门禁。
        if not identity or live != identity: return {'minimized': False, 'reason': '进程生命周期已改变，拒绝操作（期望 %s，实际 %s）' % (identity, live)}  # 与强杀同一条身份门禁。
        if current.get('minimized') is True or (fresh['desktop'].get('backend') == 'x11' and current.get('mapped') is False): return {'minimized': True, 'already_minimized': True, 'window_id': current['id'], 'pid': current.get('pid'), 'reason': '目标窗口已经是最小化状态'}  # 只要求目标尚未最小化。
        backend = fresh['desktop'].get('backend')  # 只按系统分支，不按软件名。
        try:  # 原生权限或接口失败必须返回明确失败。
            if backend == 'x11':  # 用 ICCCM 标准图标化请求，交给窗口管理器执行。
                from Xlib import X, Xatom  # 系统 X11 标准接口。
                from Xlib.protocol import event as x_event  # 显式取事件类，不依赖其它模块的副作用导入。
                connection = collector.desktop.display  # 复用当前采集器的显示连接。
                window = connection.create_resource_object('window', int(current['id'].split(':', 1)[1]))  # 精确窗口句柄。
                pid = window.get_full_property(connection.intern_atom('_NET_WM_PID'), Xatom.CARDINAL)  # 执行前再次核对 PID 属性。
                if pid is None or int(pid.value[0]) != current['pid']: return {'minimized': False, 'reason': '原生窗口 PID 已改变'}  # 拒绝窗口重用。
                message = x_event.ClientMessage(window=window, client_type=connection.intern_atom('WM_CHANGE_STATE'), data=(32, [3, 0, 0, 0, 0]))  # 3 = ICCCM IconicState（这版 Xlib 没有该常量）。
                connection.screen().root.send_event(message, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask); connection.sync()  # 由 WM 执行，不直接改窗口属性。
            elif backend == 'windows':  # 标准最小化接口，而非结束进程。
                user = ctypes.WinDLL('user32', use_last_error=True)  # 只加载系统接口。
                if not hasattr(user, 'ShowWindow'): raise OSError('user32 未导出 ShowWindow')  # 名字写错时给出明确原因，而不是让 ctypes 抛难懂的错。
                user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]  # 64 位句柄不能截断；user32 里没有 W/A 后缀。
                user.ShowWindow.restype = ctypes.c_int  # 检查调用结果。
                hwnd = int(current.get('native_id') or current['id'].split(':', 1)[1])  # 获取核实过的原生 HWND。
                user.ShowWindow(hwnd, 6)  # 6 = SW_MINIMIZE，系统拒绝时不冒充成功。
            elif backend == 'gnome':  # Wayland 由合成器内的扩展执行，采集器只写有期限的一次性请求。
                command = {'id': uuid.uuid4().hex, 'window_id': current['id'], 'pid': current['pid'], 'title': current.get('title', ''), 'expires_at': time.time()+2}  # 有期限的一次性目标。
                write_json(collector.desktop.path.parent/'minimize-request.json', command)  # 不暴露任意命令或任意路径。
            else:  # 尚未验证的系统动作不假装实现。
                return {'minimized': False, 'reason': '本系统尚无已实现的最小化后端'}  # macOS 可采集不等于能最小化。
            deadline = time.monotonic()+2.5  # 扩展每 500ms 处理一次请求，留出两轮以上余量。
            while time.monotonic() < deadline:  # 区分请求已发与实际最小化。
                now = collector.desktop.capture()  # 只读取窗口元数据，不重复截图。
                record = next((w for w in now.get('windows', []) if w['id'] == current['id']), None)  # 目标可能已经消失。
                if now.get('available') and (record is None or record.get('minimized') is True or (backend == 'x11' and record.get('mapped') is False)): return {'minimized': True, 'window_id': current['id'], 'pid': current.get('pid'), 'kind': 'native_window', 'reason': '已确认目标窗口最小化，未结束进程'}  # 实际观察结果。
                time.sleep(.05)  # 有界轮询。
            return {'minimized': False, 'requested': True, 'kind': 'native_window', 'reason': '最小化请求已发送，窗口仍处于显示状态'}  # 没最小化就不能记作成功。
        except Exception as error:  # 权限、窗口消失或接口异常都保留诊断。
            return {'minimized': False, 'reason': '最小化失败：'+str(error)[:180]}  # 不转为更强的结束进程命令。


def kill_verified_process(pid,identity):
    """Terminate one freshly reviewed process and its children; callers own OS elevation."""
    import psutil
    try:
        process=psutil.Process(pid)
        protected={os.getpid(),*(p.pid for p in psutil.Process().parents())}
        if pid in protected:return {'closed':False,'reason':'拒绝终止监督器或其父进程'}
        if not process.is_running():return {'closed':True,'already_closed':True,'pid':pid,'kind':'native_process','reason':'目标进程已不存在，视为已关闭'}
        live_info=process_info(pid)
        if live_info.get('error') in ('NoSuchProcess','ZombieProcess'):return {'closed':True,'already_closed':True,'pid':pid,'reason':'身份检查前目标进程已退出'}
        if live_info.get('error'):return {'closed':False,'reason':'无法读取进程身份：'+live_info['error']}
        if live_info.get('identity')!=identity:return {'closed':False,'reason':'进程生命周期已改变'}
        children=[child for child in process.children(recursive=True) if child.pid not in protected]  # 子进程可能才是真正持有窗口的那个。
        errors=[]
        for target in [process,*children]:
            try:target.kill()
            except psutil.NoSuchProcess:pass
            except psutil.Error as error:errors.append({'pid':target.pid,'error':str(error)})
        gone,alive=psutil.wait_procs([process,*children],timeout=5)
        remaining=[]
        for target in alive:
            try:
                if target.is_running() and target.status()!=psutil.STATUS_ZOMBIE:remaining.append(target)
            except psutil.NoSuchProcess:pass
            except psutil.AccessDenied:remaining.append(target)
        alive=remaining
        return {'closed':not alive,'forced':True,'pid':pid,'children_seen':len(children),
                'killed_children':sum(c.pid not in {p.pid for p in alive} for c in children),
                'alive_pids':[p.pid for p in alive],'errors':errors,'kind':'native_process',
                'reason':'目标进程树已退出' if not alive else '强杀后仍有进程存活'}
    except psutil.NoSuchProcess:return {'closed':True,'already_closed':True,'pid':pid,'kind':'native_process','reason':'目标进程已不存在，视为已关闭'}  # 已被关掉不算失败。
    except Exception as error:
        return {'closed':False,'forced':True,'reason':'强制退出失败：'+str(error)[:180]}
