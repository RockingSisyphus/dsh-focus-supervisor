"""Return the user to the supervising chat: switch a page that is already open, and only
open a browser when no DSH page is there to take the request."""
import os
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse,parse_qsl,urlencode

COLD_WAIT_SECONDS = 45.0
CLAIM_WAIT_SECONDS = 12.0  # Includes page navigation and its explicit completion reply.
THAW_WAIT_SECONDS = 30.0   # An already existing frozen tab may reload after its window is restored.


class FocusSuperseded(RuntimeError):
    """A newer click owns focus; the previous popup should close quietly."""


class RaiseFailed(RuntimeError):
    """The Session did switch, but the browser window could not be brought forward.

    Kept apart from a failed switch so the popup can say what actually happened instead
    of claiming the chat could not be opened.
    """


class PluginUnreachable(RuntimeError):
    """The plugin address did not answer at all, so another address may still work.

    A popup reads its plugin address from a registry file written by whichever plugin
    process registered last. If that address is stale (a restarted DSH on a new port, or
    anything else that overwrote the file), the reminder's own address is still good and
    must be tried before opening a browser anywhere — otherwise the click lands on a dead
    page and looks like it did nothing.
    """


def _log(message):
    """Short diagnostics for the reminder log; never secrets and never fatal."""
    try:
        print('[open_chat] ' + str(message), file=sys.stderr, flush=True)
    except Exception:
        pass
CLAIM_POLL_SECONDS = 0.5
REQUEST_TIMEOUT = 1.5


def _plugin_call(origin, route, payload=None, method='POST', timeout=REQUEST_TIMEOUT):
    """One short loopback call to the plugin; failures stay with the caller."""
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(origin + route, data=data, method=method,
        headers={'content-type': 'application/json'} if data is not None else {})
    # A configured system proxy must never intercept a loopback call to the plugin.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8') or '{}')


def switch_open_page(origin, session, request_id=None, wait_seconds=None):
    """Ask an already open DSH page to switch to this session.

    Returns its native title marker only after the page confirms navigation and the
    native helper selects it. A claimed-but-failed request must never open a duplicate.
    """
    if not origin or not session:
        return False
    if request_id is None:
        try:
            created = _plugin_call(origin, '/focus/open-request', {'session': session})
        except urllib.error.HTTPError:
            return False
        except Exception as error:
            raise PluginUnreachable(str(error)[:120]) from error
        request_id = created.get('id')
    if not request_id:return False
    # A background tab's timers are throttled, so "no recent poll" does NOT mean no page:
    # always give a page the chance to take the request. A page that is present answers
    # immediately over its held request; only a genuinely absent page waits out the budget.
    state = {}
    assigned = False
    deadline = time.monotonic() + (CLAIM_WAIT_SECONDS if wait_seconds is None else wait_seconds)
    while time.monotonic() < deadline:
        try:
            state = _plugin_call(origin, '/focus/open-request?id=' + str(request_id), method='GET')
        except Exception:
            if assigned:raise RuntimeError('已有 DSH 页面正在切换，但确认连接中断；未新建标签页。')
            return False
        assigned = assigned or bool(state.get('claimed'))
        if state.get('replaced'):raise FocusSuperseded('本次唤回已被新的点击替代。')
        if state.get('error'):
            raise RuntimeError('已有 DSH 页面切换失败：'+state['error'])
        if state.get('session_ready',state.get('completed', state.get('claimed', False))):
            marker=state.get('marker')
            if marker:
                from focus_window import raise_dsh_window
                # A newer click supersedes this operation before any native activation.
                current=_plugin_call(origin,'/focus/open-request?id='+str(request_id),method='GET')
                if current.get('replaced'):raise FocusSuperseded('本次唤回已被新的点击替代。')
                if current.get('expired'):raise RuntimeError('本次唤回已超时结束。')
                native_started=time.monotonic()
                result=raise_dsh_window(marker,request_context={'origin':origin,'id':request_id})
                result['native_ms']=round((time.monotonic()-native_started)*1000)
                try:_plugin_call(origin,'/focus/open-result',{**result,'id':request_id})
                except urllib.error.HTTPError as error:
                    if error.code==409:raise FocusSuperseded('本次唤回已被新的点击替代。') from error
                    raise
                raised=bool(result.get('raised'))
                # 每一步都写进日志：失败时不必猜是"扩展没跑"还是"合成器拒绝"。
                for step in result.get('steps') or []:
                    _log('置前步骤 '+json.dumps(step, ensure_ascii=False)[:200])
                _log(('已把原窗口带到前台' if raised else '会话已切换，但没能把原窗口带到前台：'+str(result.get('reason','未知原因')))+' @'+origin)
                if not raised:
                    error=RaiseFailed('已切到监工会话；桌面唤回未完成：'+str(result.get('reason','未知原因')))
                    error.raise_result=result       # 证据随异常带走，弹窗与日志都能看到
                    raise error
            return marker or True
        if state.get('expired'):
            if assigned:raise RuntimeError('已有 DSH 页面的切换确认已超时；未新建标签页。')
            return False
        time.sleep(CLAIM_POLL_SECONDS)
    if assigned:
        _plugin_call(origin,'/focus/open-result',{'id':request_id,'raised':False,'reason':'页面切换超时'})
        raise RuntimeError('已有 DSH 页面仍在切换，请稍后重试；未新建标签页。')
    return False


def _session_of(parsed):
    for pair in parsed.query.split('&'):
        key, _, value = pair.partition('=')
        if key == 'session' and value:
            return value
    return ''


def open_chat(url, registry=None):
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1':
        raise ValueError('Only the local DSH page may be opened')
    # 提醒自带的地址永远是可达兜底：registry 里的地址可能已经过时（DSH 换了端口，或者别的
    # 进程把注册文件写成了自己的地址）。
    url_origin = f'{parsed.scheme}://{parsed.netloc}'
    registry_origin = ''
    if registry:
        try:
            candidate = urlparse(json.loads(Path(registry).read_text(encoding='utf-8'))['origin'])
            if candidate.scheme == 'http' and candidate.hostname == '127.0.0.1' and candidate.port:
                registry_origin = f'{candidate.scheme}://{candidate.netloc}'
        except (OSError, ValueError, KeyError):
            registry_origin = ''
    session = _session_of(parsed)
    switched = False
    request_id=None
    if not session:
        _log('链接里没有会话编号，直接打开浏览器')
    else:
        ordered, seen = [], set()
        for candidate in (registry_origin, url_origin):
            if candidate and candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        for candidate in ordered:
            try:
                try:created=_plugin_call(candidate,'/focus/open-request',{'session':session})
                except Exception as error:raise PluginUnreachable(str(error)) from error
                request_id=created.get('id')
                switched = switch_open_page(candidate,session,request_id=request_id,
                    wait_seconds=2.0 if created.get('open_page') is False else CLAIM_WAIT_SECONDS)
                if not switched:
                    from focus_window import wake_existing_dsh_window
                    wake=wake_existing_dsh_window()
                    if wake.get('found'):
                        _log('旧 DSH 窗口唤醒：'+json.dumps(wake,ensure_ascii=False)[:240])
                        if not wake.get('raised'):
                            raise RaiseFailed('找到旧 DSH 窗口，但无法恢复：'+str(wake.get('reason') or '未知原因'))
                        switched=switch_open_page(candidate,session,request_id=request_id,
                            wait_seconds=THAW_WAIT_SECONDS)
                        if not switched:
                            raise RuntimeError('旧 DSH 窗口已恢复，但页面没有接管会话；未新建重复标签页。')
            except PluginUnreachable as error:
                _log('插件地址不通（%s），换下一个地址：%s' % (candidate, str(error)[:80]))
                continue
            except Exception as error:
                _log('请求已开页面失败：' + type(error).__name__ + ' ' + str(error)[:160])
                raise
            # 插件在（有人接管或没人接管都算），回退开浏览器就用这个可达地址，别用过时地址。
            if candidate != url_origin:
                _log('用 registry 地址接管：' + candidate)
            merged = urlparse(candidate)._replace(path=parsed.path, query=parsed.query)
            url, parsed = merged.geturl(), merged
            break
        else:
            _log('注册地址与提醒地址都不通，按提醒自带地址回退')
        if switched:
            _log('已有页面接管切换 @' + url)
        elif ordered:
            _log('没有页面接管，回退打开浏览器 @' + url)
        else:
            _log('没有可用的插件地址，直接打开浏览器')
    if not switched:
        # B checks DSH every 15 seconds. Avoid opening a dead browser tab during
        # that short recovery window; report failure to the popup if it stays down.
        deadline = time.monotonic() + 30
        launch_attempted = False
        while True:
            try:
                with socket.create_connection(('127.0.0.1', parsed.port or 80), timeout=1):
                    break
            except OSError:
                if not launch_attempted:
                    launch_attempted = True
                    command = ['schtasks', '/Run', '/TN', 'Dafeiyu-DSH'] if os.name == 'nt' else ['systemctl', '--user', 'start', 'dsh-web.service']
                    try:
                        subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    except (OSError, subprocess.SubprocessError):
                        pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('DSH 尚未恢复，请稍后重试')
                time.sleep(.25)
        # Reuse this click's request when the official browser entry boots a page.
        # The redirect must not create a second request or leave native activation unowned.
        if request_id:
            query=dict(parse_qsl(parsed.query));query['request']=request_id
            url=parsed._replace(query=urlencode(query)).geturl()
        if os.name == 'nt':os.startfile(url)
        else:subprocess.Popen(['xdg-open',url],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        if not request_id:
            raise RuntimeError('已打开 DSH，但插件唤回接口不可用，无法确认目标会话与窗口。')
        switched=switch_open_page(f'{parsed.scheme}://{parsed.netloc}',session,request_id=request_id,wait_seconds=COLD_WAIT_SECONDS)
        if not switched:raise RuntimeError('浏览器已打开，但目标页面未完成唤回。')
    return switched
