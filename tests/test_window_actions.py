"""窗口动作的判据：minimize_window 与 force_close 共用同一套门禁。

最小化：目标窗口存在 + 进程身份一致 + 尚未最小化 + 不属于监督器；
强杀：进程身份一致 + 不结束监督器自身及父进程。
真实事故的字段级复刻见 EVIDENCE 与 test_minimize_ignores_title_and_content_changes：
2026-09-18 对 gnome:328（B 站视频窗口）关闭被拒；2026-09-19 实测发现 Wayland 上
扩展还额外要求"目标必须是焦点窗口"，已一并去掉。
"""
import copy
import json
import os
import subprocess
import sys
import threading
import time
from types import SimpleNamespace as N

import pytest

from focus_demo.actions import force_close_authorization, kill_verified_process, request_window_minimize
from focus_demo.platforms import process_info

BILIBILI_TITLE = "强行给二哈做体检，那场面比杀猪现场还狠！_哔哩哔哩_bilibili - Google Chrome"
OTHER_TAB_TITLE = "哔哩哔哩 (゜-゜)つロ 干杯~-bilibili - Google Chrome"

# 与会话日志中 e_d01f4129d3a3a5 / window_inventory 的真实形状一致：
# ui_text 为空、画面为 native_window_surface 快照、进程身份来自 pid+创建时间摘要。
EVIDENCE = {
    "id": "gnome:328",
    "instance_key": "1f0c9a2b7d4e5f60718293",
    "process": {"pid": 892732, "created_at": 1789635832.39, "identity": "5496e10131d6beea8cf8"},
    "title": BILIBILI_TITLE,
    "ui_text": "",
    "screenshot": {"scope": "native_window_surface", "sha256": "9f" * 32, "captured_at": 1789717952.27},
}


class FakeDesktop:
    """契约替身：记录 D-Bus 请求与独立的窗口状态。"""

    instances = []

    def __init__(self, root, window, backend="gnome"):
        self.last_request = None
        FakeDesktop.instances.append(self)
        self.window = window
        self.backend = backend
        self.minimized = False

    def capture(self):
        window = {**self.window, "minimized": self.minimized or self.window.get("minimized",False), "mapped": False if self.minimized else self.window.get("mapped", True)}
        return {"available": True, "backend": self.backend, "windows": [window]}


@pytest.fixture(autouse=True)
def desktop_wire(monkeypatch):
    FakeDesktop.instances=[]
    def call(operation,request):
        assert operation=='minimize'
        desktop=next(d for d in reversed(FakeDesktop.instances) if d.window['id']==request['window_id'])
        desktop.last_request=request
        desktop.minimized=True
        return {'minimized':True}
    monkeypatch.setattr('focus_demo.desktop_bridge.call',call)


class FakeCollector:
    def __init__(self, windows, root, target=None):
        self.lock = threading.RLock()
        self.details = N(last=0)
        self.desktop = FakeDesktop(root, target if target is not None else (windows[0] if windows else {}))
        self._windows = windows

    def _capture(self):
        return {"desktop": {"backend": self.desktop.backend, "available": True, "windows": copy.deepcopy(self._windows)}}


@pytest.fixture
def sleeper():
    """真实子进程：提供可信的进程身份，结束后清理。"""
    children = []

    def spawn():
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        children.append(process)
        return process

    yield spawn
    for process in children:
        if process.poll() is None:
            process.kill()
        process.wait()


def live_window(process, **overrides):
    window = {"id": "gnome:328", "pid": process.pid, "instance_key": "1f0c9a2b7d4e5f60718293",
              "process": process_info(process.pid), "title": BILIBILI_TITLE, "ui_text": "",
              "focused": False, "visible": True, "mapped": True, "supervisor_owned": False,
              "screenshot": {"scope": "native_window_surface", "sha256": "9f" * 32}}
    window.update(overrides)
    return window


def test_minimize_ignores_title_and_content_changes(tmp_path, sleeper):
    """事故等价场景：标题、正文、画面都变了，只要进程身份与窗口还在就照样最小化。"""
    process = sleeper()
    expected = live_window(process)
    current = live_window(process, title=OTHER_TAB_TITLE, ui_text="完全不同的正文" * 5,
                          screenshot={"scope": "native_window_surface", "sha256": "3c" * 32})
    collector = FakeCollector([current], tmp_path, target=current)
    outcome = request_window_minimize(collector, expected)
    assert outcome["minimized"] is True
    assert collector.desktop.last_request['window_id']==current['id']


def test_minimize_reports_already_minimized(tmp_path, sleeper):
    process = sleeper()
    current = live_window(process, mapped=False, minimized=True)
    collector = FakeCollector([current], tmp_path, target=current)
    outcome = request_window_minimize(collector, live_window(process))
    assert outcome["minimized"] is True and outcome["already_minimized"] is True
    assert collector.desktop.last_request is None  # 已经最小化就不发请求。


def test_minimize_reports_already_gone(tmp_path, sleeper):
    process = sleeper()
    collector = FakeCollector([], tmp_path)
    outcome = request_window_minimize(collector, live_window(process))
    assert outcome["minimized"] is True and outcome["already_gone"] is True


def test_minimize_refuses_changed_process_identity(tmp_path, sleeper):
    process = sleeper()
    current = live_window(process)
    collector = FakeCollector([current], tmp_path, target=current)
    expected = {**live_window(process), "process": {**process_info(process.pid), "identity": "stale"}}
    outcome = request_window_minimize(collector, expected)
    assert outcome["minimized"] is False
    assert collector.desktop.last_request is None  # 与强杀同一条身份门禁。


def test_minimize_refuses_supervisor_owned_window(tmp_path, sleeper):
    process = sleeper()
    current = live_window(process, supervisor_owned=True)
    collector = FakeCollector([current], tmp_path, target=current)
    outcome = request_window_minimize(collector, live_window(process))
    assert outcome["minimized"] is False


def test_minimize_request_is_bounded_and_expiring(tmp_path, sleeper):
    """写给扩展的请求必须是一条有时限、只有窗口身份的小记录，不含任何命令。"""
    process = sleeper()
    current = live_window(process)
    collector = FakeCollector([current], tmp_path, target=current)
    request_window_minimize(collector, live_window(process))
    request = collector.desktop.last_request
    assert set(request) == {"id", "window_id", "pid", "title", "expires_at"}
    assert request["window_id"] == "gnome:328" and request["pid"] == process.pid
    assert time.time() < request["expires_at"] <= time.time() + 3


def test_force_authorizes_without_any_live_window(sleeper):
    """窗口列表里找不到目标，也应按证据里的进程身份授权强杀（不再重新取证窗口）。"""
    process = sleeper()
    expected = {"id": "gnome:328", "title": BILIBILI_TITLE, "process": process_info(process.pid)}

    def forbidden():
        raise AssertionError("强杀不应重新采集窗口")

    collector = N(lock=threading.RLock(), _capture=forbidden)
    outcome = force_close_authorization(collector, expected)
    assert outcome["authorized"] is True and outcome["pid"] == process.pid


def test_force_rejects_missing_identity():
    expected = {"id": "gnome:328", "title": BILIBILI_TITLE, "process": {"pid": 892732}}
    outcome = force_close_authorization(N(lock=threading.RLock()), expected)
    assert outcome["authorized"] is False and "身份" in outcome["reason"]


def test_force_rejects_reused_identity(sleeper):
    process = sleeper()
    expected = {"id": "gnome:328", "title": BILIBILI_TITLE,
                "process": {**process_info(process.pid), "identity": "stale-identity"}}
    collector = N(lock=threading.RLock(), _capture=lambda: {"desktop": {"windows": [expected]}})  # 窗口还在，只是身份对不上。
    outcome = force_close_authorization(collector, expected)
    assert outcome["authorized"] is False
    assert process.poll() is None  # 身份不符绝不杀。


def test_force_treats_reused_identity_as_closed_when_window_is_gone(sleeper):
    """PID 被回收且原窗口已经不在了：要关的东西已经没了，不该用"身份已变"卡住强杀。"""
    process = sleeper()
    expected = {"id": "gnome:328", "title": BILIBILI_TITLE,
                "process": {**process_info(process.pid), "identity": "stale-identity"}}
    collector = N(lock=threading.RLock(), _capture=lambda: {"desktop": {"available": True, "windows": []}})  # 目标窗口已不存在。
    outcome = force_close_authorization(collector, expected)
    assert outcome["authorized"] is True and outcome["already_closed"] is True
    assert process.poll() is None  # 仍不去杀那个被复用了 PID 的无辜进程。


def test_force_treats_dead_process_as_closed():
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pid, identity = process.pid, process_info(process.pid)["identity"]
    process.kill()
    process.wait()
    outcome = kill_verified_process(pid, identity)
    assert outcome["closed"] is True and outcome.get("already_closed") is True


def test_force_kills_children_but_not_siblings(sleeper):
    """连子进程一起结束，但不牵连无关进程；返回值要如实反映"当时看到几个子进程"。"""
    import psutil

    parent = subprocess.Popen([sys.executable, "-c",
        "import subprocess,sys,time;subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);time.sleep(30)"])
    sibling = sleeper()
    child_pids = []
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not child_pids:
            try:
                child_pids = [child.pid for child in psutil.Process(parent.pid).children(recursive=True)]
            except psutil.Error:
                child_pids = []
            if not child_pids:
                time.sleep(0.1)
        assert child_pids, "测试夹具未能派生子进程"
        outcome = kill_verified_process(parent.pid, process_info(parent.pid)["identity"])
        assert outcome["closed"] is True and outcome["forced"] is True
        assert outcome["pid"] == parent.pid  # 服务端测试依赖该字段。
        assert outcome["children_seen"] >= 1 and outcome["killed_children"] >= 1
        assert not psutil.pid_exists(parent.pid)
        assert all(not psutil.pid_exists(pid) for pid in child_pids)
        assert sibling.poll() is None
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait()


def test_force_close_never_kills_supervisor_parents(monkeypatch):
    """保护集合里的父进程同样不允许终止（红线上不只有自身 PID）。"""
    import psutil

    victim = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        monkeypatch.setattr(psutil.Process, "parents", lambda self: [N(pid=victim.pid)])  # 把它伪装成当前进程的父进程。
        outcome = kill_verified_process(victim.pid, process_info(victim.pid)["identity"])
        assert outcome["closed"] is False
        assert victim.poll() is None
    finally:
        if victim.poll() is None:
            victim.kill()
        victim.wait()


def test_hidden_window_records_keep_process_identity():
    """被最小化/完全遮挡的窗口也要带进程身份，否则"尚未最小化"这类判据没法用在它们身上。"""
    from focus_demo.collectors import Collector

    collector = object.__new__(Collector)
    collector.lock = threading.RLock()
    collector.desktop = N(capture=lambda: {"backend": "x11", "available": True, "windows": [
        {"id": "x11:1", "app": "t", "title": "hidden", "pid": os.getpid(),
         "mapped": False, "visible": False, "focused": False, "rect": [0, 0, 10, 10]}]})
    collector.details = None
    collector.browser_text = False
    collector.browser_skill = None
    collector.chrome = N(capture=lambda desktop: {"available": False, "pages": [], "limitations": []})
    window = collector._capture()["desktop"]["windows"][0]
    assert window["process"]["identity"]
    assert window["instance_key"]


def test_minimize_x11_sends_iconic_state_request(tmp_path, sleeper):
    """X11 分支只向窗口管理器发一条标准"请最小化"消息；这条用例会抓住常量/导入这类错误。"""
    process = sleeper()
    window = live_window(process)
    desktop = FakeDesktop(tmp_path, window, backend="x11")
    sent = {}

    class FakeWindow(int):  # 真的 Xlib 要求 window/atom 是整数，这里用 int 子类才不会被类型检查挡住。
        def get_full_property(self, atom, kind):
            return N(value=[process.pid])

    class FakeRoot:
        def send_event(self, message, event_mask=0):
            sent["data"] = message.data; sent["mask"] = event_mask; desktop.minimized = True

    class FakeDisplay:
        def create_resource_object(self, kind, ident): return FakeWindow(ident)
        def intern_atom(self, name): return abs(hash(name)) % 100000
        def screen(self): return N(root=FakeRoot())
        def sync(self): pass

    desktop.display = FakeDisplay()
    collector = FakeCollector([window], tmp_path, target=window)
    collector.desktop = desktop
    outcome = request_window_minimize(collector, window)
    assert outcome["minimized"] is True
    assert sent["data"][0] == 32 and sent["data"][1][0] == 3  # 32 位格式里的 ICCCM IconicState
    assert sent["mask"] & (1 << 20)  # SubstructureRedirectMask：请求交给 WM，而不是自己改窗口属性
