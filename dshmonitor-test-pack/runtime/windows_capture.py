"""On-demand Windows desktop capture. No task scheduling or AI/model calls."""
import argparse
import ctypes
import getpass
import importlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--ready-only', action='store_true')
    parser.add_argument('--samples', type=int, default=10)
    parser.add_argument('--interval', type=float, default=2)
    parser.add_argument('--browser-skill', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Run in a signed-in Windows desktop session')
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    session = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        raise ctypes.WinError()
    ready = {'user': getpass.getuser(), 'session_id': session.value,
             'python': sys.version, 'executable': sys.executable,
             'mode': 'environment-only' if args.ready_only else 'capture',
             'real_model_called': False}
    try:
        if session.value == 0:
            raise RuntimeError('Session 0 cannot represent the signed-in user desktop')
        for name in ('requests', 'websocket', 'psutil', 'PIL.ImageGrab', 'pywinauto', 'win32gui', 'win32ui', 'focus_demo.collectors'):
            importlib.import_module(name)
        ready['imports_ok'] = True
        (output/'environment.json').write_text(json.dumps(ready, ensure_ascii=False, indent=2), encoding='utf-8')
        if args.ready_only:
            return
        from focus_demo.collectors import Collector
        collector = Collector('windows', 49998, 49999, SimpleNamespace(
            data_dir=str(output), screenshots=True, ui_text=True, detail_interval=args.interval,
            browser_text=False, browser_skill=args.browser_skill, log_root=[], system_logs=True))
        samples = []
        try:
            for _ in range(args.samples):
                samples.append(collector.capture())
                (output/'samples.json').write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding='utf-8')
                time.sleep(args.interval)
        finally:
            collector.suspend()
        (output/'completed.json').write_text(json.dumps({'samples': len(samples), 'completed_at': time.time(), 'capability_acceptance': 'requires_evidence_review'}), encoding='utf-8')
    except Exception as error:
        (output/'error.json').write_text(json.dumps({'error': repr(error), 'environment': ready}, ensure_ascii=False, indent=2), encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
