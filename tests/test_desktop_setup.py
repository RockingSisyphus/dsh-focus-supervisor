"""Installation and capability reporting without modifying the user's settings."""
import json
from pathlib import Path
import subprocess
import sys
import time
from focus_demo import desktop_setup as setup


def environment(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_SESSION_TYPE', 'wayland')
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'GNOME')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path / 'cache'))
    monkeypatch.setattr('focus_demo.desktop_bridge.call', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('No desktop interface')))
    monkeypatch.setattr(setup.shutil, 'which', lambda _: '/usr/bin/gnome-extensions')


def test_new_install_preserves_extensions_and_is_idempotent(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    values = {'enabled-extensions': ['other@extension'], 'disabled-extensions': [setup.UUID, 'disabled@other']}
    def command(args):
        if args[0] == 'gsettings':
            if args[1] == 'get':
                return subprocess.CompletedProcess(args, 0, repr(values[args[3]]), '')
            values[args[3]] = True if args[4]=='true' else setup.ast.literal_eval(args[4])
            return subprocess.CompletedProcess(args, 0, '', '')
        return subprocess.CompletedProcess(args, 1, '', 'Extension does not exist')
    monkeypatch.setattr(setup, 'command', command)
    source = tmp_path / 'source'; source.mkdir()
    for name in ('extension.js', 'visibility.js', 'metadata.json'): (source / name).write_text('test')
    for _ in range(2):
        result = setup.install(source)
        assert result['code'] == 'login_required'
        assert not result['screenshot_verified']
    assert values == {'enabled-extensions': ['other@extension', setup.UUID], 'disabled-extensions': ['disabled@other'],'toolkit-accessibility':True}


def test_active_extension_is_not_a_verified_screenshot(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    target = tmp_path / 'data/gnome-shell/extensions' / setup.UUID
    target.mkdir(parents=True); (target / 'extension.js').touch()
    monkeypatch.setattr(setup, 'command', lambda args: subprocess.CompletedProcess(args, 0, 'State: ACTIVE\n', ''))
    monkeypatch.setattr('focus_demo.desktop_bridge.call', lambda operation: {'code_version':setup.EXPECTED_EXTENSION_CODE_VERSION})
    assert setup.status()['code'] == 'bridge_running'
    assert not setup.status()['screenshot_verified']


def test_other_wayland_desktop_is_explicitly_unsupported(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    monkeypatch.setenv('XDG_CURRENT_DESKTOP', 'KDE')
    assert setup.status()['code'] == 'unsupported_wayland'


def test_fresh_bridge_survives_empty_extension_cli(monkeypatch, tmp_path):
    environment(monkeypatch, tmp_path)
    target = tmp_path / 'data/gnome-shell/extensions' / setup.UUID
    target.mkdir(parents=True); (target / 'extension.js').touch()
    monkeypatch.setattr(setup, 'command', lambda args: subprocess.CompletedProcess(args, 0, '', ''))
    monkeypatch.setattr('focus_demo.desktop_bridge.call', lambda operation: {'code_version':setup.EXPECTED_EXTENSION_CODE_VERSION})
    assert setup.status()['code'] == 'bridge_running'
    def disconnected(*args, **kwargs):raise RuntimeError('Disconnected')
    monkeypatch.setattr('focus_demo.desktop_bridge.call', disconnected)
    assert setup.status()['code'] == 'status_unavailable'
    assert not setup.status()['screenshot_verified']


def test_module_is_runnable_as_a_cli(tmp_path, monkeypatch):
    """`python3 -m focus_demo.desktop_setup status` 必须真的输出 JSON。

    这段守卫原来缺失：模块有 argparse + main，却没有 `__main__` 分支，于是
    `-m … install` 静默什么都不做还返回 0——来宾里装扩展就是这么"成功"的。
    """
    environment(monkeypatch, tmp_path)
    monkeypatch.setattr(setup, 'command', lambda args: subprocess.CompletedProcess(args, 0, '[]', ''))
    result = subprocess.run([sys.executable, '-m', 'focus_demo.desktop_setup', 'status'],
        capture_output=True, text=True, timeout=60, cwd=str(Path(__file__).resolve().parents[1]))
    assert result.returncode == 0, result.stderr[-400:]
    assert json.loads(result.stdout)['session'] == 'wayland'
