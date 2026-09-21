"""扩展代码、Python 助手与安装器必须对同一版扩展达成一致。

扩展是 JS、判据在 Python 里，两边一旦漂移就会出现"改了扩展但 Shell 里跑旧代码、
谁都没发现"——这在真机上真的发生过，所以用契约测试盯住。
"""
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

focus_window = _load('contract_focus_window', 'deploy/focus_window.py')
desktop_setup = _load('contract_desktop_setup', 'focus_demo/desktop_setup.py')
EXTENSION = (ROOT / 'gnome-extension/extension.js').read_text(encoding='utf-8')


def test_the_three_version_constants_agree():
    js_version = re.search(r"const CODE_VERSION = '([^']+)'", EXTENSION).group(1)
    assert js_version == focus_window.EXTENSION_CODE_VERSION, 'Python 助手读的版本要和扩展一致'
    assert js_version == desktop_setup.EXPECTED_EXTENSION_CODE_VERSION, '安装器核实的版本要和扩展一致'


def test_the_extension_reports_itself_and_its_actions():
    for name in ('extension-state.json', 'last-focus.json', 'extension-disabled.json'):
        assert name in EXTENSION, '扩展必须写出 ' + name + '，否则调用方只能猜'
    assert 'code_version:CODE_VERSION' in EXTENSION.replace(' ', ''), '自证文件要带版本'


def test_the_extension_authorises_by_marker_or_pid():
    assert 'marker_match' in EXTENSION and 'pid_match' in EXTENSION, '标题标记与进程号都要能授权'
    assert "request.pid" in EXTENSION, '置前请求要支持进程号（目标页不在最前或标题不跟随时靠它认窗口）'
    assert '!markerMatch&&!pidMatch' in EXTENSION.replace(' ', ''), '两者都不命中才拒绝'


def test_one_failure_cannot_stop_the_sampling_loop():
    assert 'processMinimize' in EXTENSION and 'processFocus' in EXTENSION
    capture = EXTENSION[EXTENSION.index('capture() {'):]
    assert 'try { this.processMinimize(); }' in capture and 'try { this.processFocus(); }' in capture, '单件事出错不能停掉整轮采样'


def test_the_installer_never_claims_a_reload_it_did_not_get():
    source = (ROOT / 'focus_demo/desktop_setup.py').read_text(encoding='utf-8')
    assert 'running_extension_version' in source and 'version_matches' in source, '安装后要核实 Shell 里真正跑的版本'
    assert '注销并重新登录一次' in source, '加载不上时要如实说要重登，不能假装成功'
