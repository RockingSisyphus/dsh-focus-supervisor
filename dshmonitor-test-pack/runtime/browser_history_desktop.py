"""Logged-in Wayland desktop with real Chromium and the installed read-only observer extension."""
from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import tempfile
import time
from focus_demo.platforms import process_info


@contextmanager
def desktop(out):
    original = os.environ.copy()
    processes = []
    from dsh_test_harness.desktop import Desktop
    manager=Desktop()
    chrome_executable=manager.browser_options(True,os.environ.copy())['executable_path']
    with tempfile.TemporaryDirectory(prefix='dafeiyu-history-desktop-') as directory:
        try:
            log = open(Path(directory)/'process.log', 'w')
            def start(argv):
                p = subprocess.Popen(argv, stdout=log, stderr=log, start_new_session=True)
                processes.append(p)
                return p
            manager.setup(Path(directory),start)
            chrome = start([chrome_executable, '--user-data-dir='+directory+'/profile', '--remote-debugging-port=0','--no-first-run','--no-default-browser-check','--password-store=basic','--ozone-platform=wayland', 'about:blank'])
            # Opening the extension UI initializes its worker in a fresh profile.
            port_file = Path(directory)/'profile/DevToolsActivePort'
            end = time.monotonic()+10
            while not port_file.exists():
                if time.monotonic()>end: raise RuntimeError('测试 Chromium 调试端口未就绪')
                time.sleep(.1)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp('http://127.0.0.1:'+port_file.read_text(encoding='utf-8').splitlines()[0],no_defaults=True)
                yield {'instance_id':process_info(chrome.pid)['identity'],'context':browser.contexts[0]}
        except Exception as error:
            import json
            Path(out).mkdir(parents=True,exist_ok=True)
            result=Path(out)/'result.json'
            if not result.exists():result.write_text(json.dumps({'status':'failed','failure_stage':'environment','error':str(error)},ensure_ascii=False),encoding='utf-8')
            try:
                from dsh_test_harness.gnome import call
                from dsh_test_harness.wait import until
                (Path(out)/'setup-failure-desktop.json').write_text(json.dumps(call('snapshot'),ensure_ascii=False),encoding='utf-8')
                screenshot=Path(out)/'setup-failure-desktop.png'
                call('screenshot',{'path':str(screenshot)})
                until(screenshot.exists,3)
            except Exception as diagnostic_error:
                (Path(out)/'setup-diagnostic-error.txt').write_text(str(diagnostic_error),encoding='utf-8')
            raise
        finally:
            for p in reversed(processes):
                manager.stop_process(p)
            if 'log' in locals(): log.close()
            manager.close()
            os.environ.clear();os.environ.update(original)
