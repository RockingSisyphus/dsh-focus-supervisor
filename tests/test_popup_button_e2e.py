"""弹窗按钮协议契约测试：真实插件两端及 open_chat，DSH 与桌面使用桩。

2026-09-19 DSH 升到 0.1.6 后，会话列表里不再有 current 字段，页面侧的切换校验因此恒为假，
弹窗按钮把「其实切过去了」报成失败。各自的单测当时都是绿的，只有把两半真接起来才看得见，
所以这个文件跑的是发货代码本身：

    tests/popup_e2e/host.mjs  插件真实的 /focus/* 路由（chat-host.mjs），只把 DSH 宿主换成桩
    tests/popup_e2e/page.mjs  真实的 dsh-plugin/client.js，跑在三种会话服务形态下
    deploy/open_chat.py       真实的按钮逻辑；只有"桌面置前"这一层被替换，因为 CI 里没有桌面

判定依据全部来自进程外部可核对的事实：插件记录的交接状态、页面自己回报的会话与标题标记、
以及置前调用的参数——没有"看起来成功了"。
"""
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
import types
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests' / 'popup_e2e'


def _load_open_chat():
    spec = importlib.util.spec_from_file_location('monitor_open_chat_e2e', ROOT / 'deploy' / 'open_chat.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


open_chat_module = _load_open_chat()

# 夹具跑的是插件真实的 host 半，它按 DSH 的方式解析 @deepseek-ai/* 依赖。宿主机上那是
# dsh-plugin/node_modules 软链（指向本机 DSH 安装）；没有 DSH 的机器上跳过，而不是假装通过——
# 来宾（vms/linux|windows）里由宿主机脚本把这份依赖闭包推过去。
DSH_DEPENDENCY = ROOT / 'dsh-plugin' / 'node_modules' / '@deepseek-ai' / 'schemastery' / 'package.json'
if not DSH_DEPENDENCY.exists():
    pytest.skip('需要本机 DSH 提供的 @deepseek-ai/schemastery（插件 host 半的依赖）', allow_module_level=True)


class _Process:
    """一个不断打印 `PAGE {json}` 的子进程，按行留档供断言使用。"""

    def __init__(self, command, ready):
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines = []
        self.ready = ready
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        self.wait_for(ready, timeout=30)

    def _read(self):
        for line in self.process.stdout:
            self.lines.append(line.rstrip('\n'))
        for line in self.process.stderr:
            self.lines.append('ERR ' + line.rstrip('\n'))

    def wait_for(self, prefix, timeout=20.0, predicate=None):
        deadline = time.time() + timeout
        while time.time() < deadline:
            for line in list(self.lines):
                if line.startswith(prefix) and (predicate is None or predicate(line)):
                    return line
            if self.process.poll() is not None:
                raise AssertionError('子进程提前退出（%s）：\n%s' % (self.process.returncode, '\n'.join(self.lines[-20:])))
            time.sleep(0.05)
        raise AssertionError('等待 %r 超时：\n%s' % (prefix, '\n'.join(self.lines[-20:])))

    def events(self, name=None):
        found = []
        for line in list(self.lines):
            if not line.startswith('PAGE '):
                continue
            try:
                payload = json.loads(line[5:])
            except ValueError:
                continue
            if name is None or payload.get('event') == name:
                found.append(payload)
        return found

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()


class Harness:
    """真 host 半 + 真页面半的组合，跑在一台假后端上。"""

    def __init__(self, session='session-target', project='/tmp/project'):
        self.session = session
        self.project = project
        self.host = _Process(['node', str(FIXTURE / 'host.mjs'), '--session', session, '--project', project], 'HOST ')
        self.info = json.loads(self.host.wait_for('HOST ')[5:])
        self.origin = self.info['origin']
        self.token = self.info['token']
        self.page = None

    def start_page(self, shape='modern', page_id='node-page'):
        self.page_id = page_id
        self.page = _Process(['node', str(FIXTURE / 'page.mjs'), '--origin', self.origin,
            '--session', self.session, '--shape', shape, '--page-id', page_id], 'PAGE ')
        self.page.wait_for('PAGE ', predicate=lambda line: '"event":"booted"' in line)
        # 页面先向 /focus/status 轮询一次，插件才知道有人在看：等到插件记下这个页面。
        deadline = time.time() + 15
        while time.time() < deadline:
            pages = [item.get('page') for item in (self.status().get('pages') or [])]
            if page_id in pages:
                return
            time.sleep(0.2)
        raise AssertionError('页面已经启动，插件却没有记下它在轮询：%s' % self.status())

    def status(self):
        request = urllib.request.Request(self.origin + '/focus/status', method='GET',
            headers={'x-focus-token': self.token, 'x-focus-page': getattr(self, 'page_id', 'driver'), 'x-focus-visible': '1'})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            return json.loads(response.read().decode('utf-8') or '{}')

    def request_state(self, request_id):
        request = urllib.request.Request(self.origin + '/focus/open-request?id=' + str(request_id), method='GET',
            headers={'x-focus-token': self.token})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            return json.loads(response.read().decode('utf-8') or '{}')

    def page_state(self, predicate=None, timeout=15.0):
        """页面每 250ms 回报一次状态；等到满足条件的那一份，绝不拿旧的一份凑数。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for state in reversed(self.page.events('page')):
                if predicate is None or predicate(state):
                    return state
            time.sleep(0.1)
        raise AssertionError('页面没有回报满足条件的状况：\n%s' % '\n'.join(self.page.lines[-20:]))

    def click(self, registry):
        url = '%s/focus/open?session=%s' % (self.origin, self.session)
        return open_chat_module.open_chat(url, str(registry))

    def stop(self):
        if self.page:
            self.page.stop()
        self.host.stop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def test_the_fixture_never_touches_the_real_chat_registry(tmp_path, monkeypatch):
    """夹具跑的是真实 host 半，它会往 DSH_HOME 写 dafeiyu-chat-endpoint.json。

    真机实测过后果：夹具把注册文件写成自己的随机端口后，**真插件只在端口变化时才写一次**，
    不会自己改回来；用户点开工提醒时弹窗照着这个死地址回退，开了个连不上的页面还卡住。
    所以夹具必须把 DSH_HOME 指向临时目录——这条测试就是钉住这一点。
    """
    registry = Path(os.environ.get('DSH_HOME') or (Path.home() / '.dsh')) / 'dafeiyu-chat-endpoint.json'
    before = (registry.read_bytes(), registry.stat().st_mtime_ns) if registry.exists() else None
    with Harness() as harness:
        harness.start_page('modern')
        time.sleep(1.5)                     # 夹具 host 半此时已经在轮询并尝试注册自己
        assert 'DUMMY' not in harness.origin
        after = (registry.read_bytes(), registry.stat().st_mtime_ns) if registry.exists() else None
    assert after == before, '夹具不得改写真机的 %s' % registry
    assert not Path(harness.info['temporary_home']).exists()


def _stub_desktop(monkeypatch, raised=True, reason='合成器拒绝'):
    """只替换桌面置前这一层：CI 没有桌面，其余（连接、轮询、判定）全用真代码。"""
    calls = []
    module = types.ModuleType('focus_window')

    def raise_dsh_window(marker=None, **kwargs):
        calls.append({'marker': marker, **kwargs})
        return {'raised': raised, 'reason': None if raised else reason,
            'steps': [{'step': 'focus-request', 'ok': raised}]}

    module.raise_dsh_window = raise_dsh_window
    module.browser_process_ids = lambda: [4242]
    monkeypatch.setitem(sys.modules, 'focus_window', module)
    return calls


def _forbid_browser(monkeypatch):
    """把"回退开浏览器"这条路记下来：真开了就是失败（会多出一个标签页）。"""
    launched = []
    # 只换 open_chat 看到的那份 subprocess，别动测试自己用的（它还要起子进程）。
    fake = types.SimpleNamespace(Popen=lambda args, **kw: launched.append(args),
        run=lambda *args, **kw: None, CREATE_NO_WINDOW=0,
        SubprocessError=subprocess.SubprocessError)
    monkeypatch.setattr(open_chat_module, 'subprocess', fake)
    monkeypatch.setattr(open_chat_module.os, 'startfile', lambda url: launched.append(url), raising=False)
    return launched


def _registry(tmp_path):
    path = tmp_path / 'dafeiyu-chat-endpoint.json'
    path.write_text(json.dumps({'origin': 'http://127.0.0.1:1'}), encoding='utf-8')
    return path


@pytest.mark.parametrize('shape,verifiers', [
    ('modern', ['main-view-retention', 'list-main-view', 'list-current']),
    ('legacy', ['list-main-view', 'list-current']),
])
def test_popup_button_switches_the_open_page_and_raises_it(tmp_path, monkeypatch, shape, verifiers):
    """已有页面时：不新开标签页，切到指定会话，并把原窗口带到前台。"""
    raised = _stub_desktop(monkeypatch)
    launched = _forbid_browser(monkeypatch)
    with Harness() as harness:
        harness.start_page(shape)
        # 假装 registry 指向真 host：弹窗按钮要先问插件，而不是直接开浏览器。
        registry = tmp_path / 'endpoint.json'
        registry.write_text(json.dumps({'origin': harness.origin}), encoding='utf-8')
        marker = harness.click(registry)

        assert launched == [], '页面已接管切换，不得再开浏览器'
        assert isinstance(marker, str) and marker.startswith('[DSH-'), '按钮应拿到页面的交接标记'
        assert len(raised) == 1, '切换成功后必须尝试把原窗口带到前台'
        assert raised[0]['marker'] == marker, '置前用的标记就是页面打在标题上的那个'
        assert raised[0]['request_context'] == {'origin':harness.origin,'id':marker[len('[DSH-'):-1]}
        assert 'pids' not in raised[0], '同进程的任意窗口不能作为目标兜底'

        page = harness.page_state(lambda state: state['landed'])
        assert marker in page['title'], '页面标题里应有标记，原生助手才能选中它：%s' % page['title']
        assert page['landed'] is True and page['claimError'] is None, '页面应确认切换落地：%s' % page
        assert page['focusedSession'] == 'session-target'
        assert page['verifiers'] == verifiers, '切换判据应随 DSH 版本自适应'

        request_id = marker[len('[DSH-'):-1]
        state = harness.request_state(request_id)
        assert state.get('completed') is True and not state.get('error')


def test_a_switch_that_never_lands_is_reported_with_the_evidence(tmp_path, monkeypatch):
    """切换确实没落地时：如实报失败、写明判据与观测，且绝不新开标签页。"""
    raised = _stub_desktop(monkeypatch)
    launched = _forbid_browser(monkeypatch)
    with Harness() as harness:
        harness.start_page('stuck')
        registry = tmp_path / 'endpoint.json'
        registry.write_text(json.dumps({'origin': harness.origin}), encoding='utf-8')
        with pytest.raises(RuntimeError) as failure:
            harness.click(registry)

        message = str(failure.value)
        assert '已有 DSH 页面切换失败' in message
        assert '判据' in message and '观测' in message, '失败信息要能自证：%s' % message
        assert launched == [], '切换失败也不能偷偷再开一个页面'
        assert raised == [], '没有标记就不该调用置前'

        page = harness.page_state(lambda state: state['claimError'])
        assert page['landed'] is False and page['claimError'], '页面应把失败原因回报给插件：%s' % page
        assert '[DSH-' not in page['title'], '没切过去就不该打标记'


def test_a_failed_raise_keeps_the_marker_and_stays_a_raise_failure(tmp_path, monkeypatch):
    """会话切了但置前失败：必须报 RaiseFailed，并带上原生助手的证据。"""
    _stub_desktop(monkeypatch, raised=False, reason='合成器拒绝')
    launched = _forbid_browser(monkeypatch)
    with Harness() as harness:
        harness.start_page('modern')
        registry = tmp_path / 'endpoint.json'
        registry.write_text(json.dumps({'origin': harness.origin}), encoding='utf-8')
        with pytest.raises(open_chat_module.RaiseFailed) as failure:
            harness.click(registry)
        assert '桌面唤回未完成' in str(failure.value)
        assert failure.value.raise_result['reason'] == '合成器拒绝'
        assert launched == [], '置前失败不等于要再开一个页面'
