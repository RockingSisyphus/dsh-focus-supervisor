"""The test entry owns the independent, demand-driven compositor driver."""
import json,os,shutil,subprocess
from pathlib import Path
from contextlib import contextmanager
UUID='dsh-test-desktop@local'
@contextmanager
def driver_session():
    source=Path(__file__).resolve().parents[1]/'gnome-driver'
    target=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'gnome-shell/extensions'/UUID
    target.mkdir(parents=True,exist_ok=True)
    for name in ('metadata.json','extension.js'):
        data=(source/name).read_bytes()
        if not (target/name).exists() or (target/name).read_bytes()!=data:(target/name).write_bytes(data)
    enabled=subprocess.run(['gnome-extensions','enable',UUID],capture_output=True,text=True,timeout=10)
    if enabled.returncode:
        raise RuntimeError('无法启用独立桌面测试驱动：'+(enabled.stderr or enabled.stdout).strip()+'；首次安装后 GNOME 可能需要重新登录')
    try:
        yield
    finally:
        subprocess.run(['gnome-extensions','disable',UUID],capture_output=True,check=True,timeout=10)
        from focus_demo.native_dbus import NativeBus
        bus=NativeBus()
        try:
            if bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','NameHasOwner','s',['org.dsh.TestDesktop'],3000):
                raise RuntimeError('Test desktop driver still exported after disable')
        finally:bus.close()
