"""Remove retired plugin files on upgrade; never edit browser profiles."""
import os
from pathlib import Path
import shutil
import sys

HOST = 'org.dafeiyu.browser_observer'


def retire(root, home=None):
    root = Path(root)
    if os.name == 'nt':
        import winreg
        for browser in ('Google\\Chrome', 'Microsoft\\Edge'):
            try:
                winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE,
                                 'Software\\'+browser+'\\NativeMessagingHosts\\'+HOST)
            except FileNotFoundError:
                pass
    else:
        for directory in ('/etc/opt/chrome/native-messaging-hosts', '/etc/chromium/native-messaging-hosts'):
            (Path(directory)/(HOST+'.json')).unlink(missing_ok=True)
    for name in ('browser-observer', 'browser-observer.cmd', 'browser_observer_host.py',
                 'browser_observer_setup.py', 'browser_setup.py', HOST+'.json'):
        (root/'deploy'/name).unlink(missing_ok=True)
    for name in ('browser_observer','__main__','doctor','dsh','engine','mcp_bridge','models','policy','popup','remote','retention','server','service_exit'):
        (root/'focus_demo'/(name+'.py')).unlink(missing_ok=True)
    for name in ('install_linux.py','maintenance_linux.py','recover_linux.py','run_service.py','run_session.py','retire_browser_observer.py'):
        (root/'deploy'/name).unlink(missing_ok=True)
    shutil.rmtree(root/'browser-observer', ignore_errors=True)
    if home:
        shutil.rmtree(Path(home)/'.cache/dafeiyu-browser', ignore_errors=True)
    print('已移除本插件旧采集 host；已安装的浏览器扩展请在浏览器扩展管理页移除。')


if __name__ == '__main__':
    retire(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else None)
