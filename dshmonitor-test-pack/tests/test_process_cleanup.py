"""A browser-style profile writer must stop before its temporary files are removed."""
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil


def test_cleanup_waits_for_profile_writer_descendant(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'test-support'))
    from dsh_test_harness.desktop import Desktop
    profile = tmp_path / 'profile'
    profile.mkdir()
    child = (
        'import signal,time;from pathlib import Path;'
        'signal.signal(signal.SIGTERM,signal.SIG_IGN);'
        f'p=Path({str(profile / "preferences")!r});'
        '\nwhile True:p.write_text(str(time.time()));time.sleep(.02)'
    )
    marker = tmp_path / 'child.pid'
    parent = (
        'import subprocess,time;from pathlib import Path;'
        f'p=subprocess.Popen([{sys.executable!r},"-c",{child!r}]);'
        f'Path({str(marker)!r}).write_text(str(p.pid));time.sleep(60)'
    )
    process = subprocess.Popen([sys.executable, '-c', parent], start_new_session=os.name != 'nt',
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        deadline = time.monotonic() + 10
        while not (profile / 'preferences').exists():
            assert time.monotonic() < deadline
            time.sleep(.05)
        writer = psutil.Process(int(marker.read_text()))
        Desktop().stop_process(process)
        assert not writer.is_running() or writer.status() == psutil.STATUS_ZOMBIE
        import shutil
        shutil.rmtree(profile)
        time.sleep(.1)
        assert not profile.exists()
    finally:
        if process.poll() is None:Desktop().stop_process(process)
