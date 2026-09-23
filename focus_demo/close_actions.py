"""One force-close strategy: exact tab/window first, verified process fallback."""
import ctypes
import json
import os
from pathlib import Path
from .process_worker import run_worker
import subprocess
import sys
import time
import uuid
from .common import write_json
from .platforms import process_info


def target_window(expected):
    return expected.get('native_window_id') or (expected.get('id') if expected.get('kind') != 'browser_tab' else None)


def window_state(collector, expected):
    snapshot = collector.desktop.capture()
    if not snapshot.get('available'):raise RuntimeError('原生窗口状态不可用')
    return snapshot, next((w for w in snapshot.get('windows', []) if w['id'] == target_window(expected)), None)


def _close_window(collector, expected):
    identifier=target_window(expected)
    if not identifier:return {'closed':False,'reason':'没有关联的原生窗口'}
    snapshot,window=window_state(collector,expected)
    if not window:return {'closed':True,'already_closed':True,'window_id':identifier}
    if window.get('pid') != expected['process']['pid']:
        return {'closed':False,'reason':'原生窗口所属进程已改变'}
    backend=snapshot.get('backend')
    if backend=='gnome':
        request={'id':uuid.uuid4().hex,'window_id':identifier,'pid':window['pid'],'expires_at':time.time()+2}
        from .desktop_bridge import call
        call('close',request)
    elif backend=='windows':
        from ctypes import wintypes as w
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
        user.PostMessageW.restype=w.BOOL
        if not user.PostMessageW(int(window.get('native_id') or identifier.split(':')[1]),0x10,0,0):
            raise ctypes.WinError(ctypes.get_last_error())
    else:return {'closed':False,'reason':'没有精细窗口关闭通道'}
    deadline=time.monotonic()+2.5
    while time.monotonic()<deadline:
        _,live=window_state(collector,expected)
        if live is None:return {'closed':True,'window_id':identifier}
        time.sleep(.05)
    return {'closed':False,'window_id':identifier,'requested':True,'reason':'关闭请求后窗口仍存在'}


def close_window(collector, expected, operation='close'):
    try:
        payload={'operation':operation,'expected':expected,'backend':getattr(collector.desktop,'__class__',type(None)).__name__}
        result=run_worker([sys.executable,'-I',str(Path(__file__).with_name('native_close.py'))],input=json.dumps(payload),capture_output=True,text=True,timeout=3)
        if result.returncode:raise RuntimeError(result.stderr[-400:])
        return json.loads(result.stdout)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        return {'closed':False,'reason':str(error)}


def close_tab(expected, operation='close'):
    """The subprocess owns every blocking browser call and dies before fallback."""
    try:
        result=run_worker([sys.executable,'-I',str(Path(__file__).with_name('browser_targets.py')),operation],input=json.dumps(expected),capture_output=True,text=True,timeout=3)
        if result.returncode:raise RuntimeError(result.stderr[-400:])
        return json.loads(result.stdout)
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
        return {'closed':False,'reason':str(error)}


def force_close(collector, expected, target_kind='process', defer_kill=False):
    from .actions import force_close_authorization,kill_verified_process
    if target_kind not in ('process','window','browser_tab'):raise ValueError('target_kind 须为 process、window 或 browser_tab')
    process=expected.get('process') or {}
    result={'closed':False,'target_kind':target_kind,'requested_target':{'id':expected.get('id'),'window_id':target_window(expected),'tab_id':expected.get('tab_id'),'pid':process.get('pid')},'attempts':[]}
    authorization=force_close_authorization(collector,expected)
    if not authorization.get('authorized'):return {**result,**authorization}
    if authorization.get('already_closed'):return {**result,**authorization,'closed':True,'actual_scope':'none'}
    import psutil
    protected={os.getpid(),*(p.pid for p in psutil.Process().parents())}
    if expected.get('supervisor_owned') or authorization['pid'] in protected:
        return {**result,'reason':'拒绝操作监督器或其父进程'}
    def attempt(kind,fn):
        start=time.monotonic()
        try:observed=fn()
        except Exception as error:observed={'closed':False,'reason':str(error)}
        result['attempts'].append({'scope':kind,'elapsed_seconds':round(time.monotonic()-start,3),**observed})
        if observed.get('closed'):
            result.update(observed,actual_scope=kind)
            return True
        return False
    if target_kind=='browser_tab' and attempt('browser_tab',lambda:close_tab(expected)):return result
    if target_kind in ('window','browser_tab'):
        def window_attempt():
            outcome=close_window(collector,expected)
            if target_kind=='browser_tab' and outcome.get('closed'):
                return {**outcome,'tab_observation':{'closed':True,'basis':'owning_window_destroyed'}}
            return outcome
        if attempt('window',window_attempt):return result
    if defer_kill:return {**result,'process_fallback':authorization}
    attempt('process',lambda:kill_verified_process(authorization['pid'],authorization['identity']))
    last=result['attempts'][-1]
    result={**result,'actual_scope':'process','process_result':last,'alive_pids':last.get('alive_pids',[]),'reason':last.get('reason','')}
    return reconcile_target(result,lambda:observe_target(collector,expected,target_kind))


def observe_target(collector,expected,target_kind):
    if target_kind=='browser_tab':
        process=expected.get('process',{})
        current=process_info(process.get('pid'))
        if process.get('identity') and current.get('identity')!=process['identity']:
            if current.get('identity') or current.get('error') in ('NoSuchProcess','ZombieProcess'):
                return {'closed':True,'basis':'owning_process_lifecycle_ended'}
        if target_window(expected):
            window=close_window(collector,expected,'observe')
            if window.get('closed'):return {**window,'basis':'owning_window_destroyed'}
        return close_tab(expected,'observe')
    return close_window(collector,expected,'observe')


def reconcile_target(result,observe=None):
    if not result.get('closed') and result.get('target_kind')!='process' and observe:
        try:fact=observe()
        except Exception as error:fact={'closed':False,'reason':str(error)}
        result['target_observation']=fact
        if fact.get('closed'):
            result.update(closed=True,reason='原目标已消失；进程后备存在残留或失败，详见 process_result')
    return result


def finish_process_fallback(result, observe=None):
    from .actions import kill_verified_process
    auth=result.pop('process_fallback',None)
    if not auth:return result
    start=time.monotonic();observed=kill_verified_process(auth['pid'],auth['identity'])
    result['attempts'].append({'scope':'process','elapsed_seconds':round(time.monotonic()-start,3),**observed})
    return reconcile_target({**result,**observed,'actual_scope':'process','process_result':observed},observe)
