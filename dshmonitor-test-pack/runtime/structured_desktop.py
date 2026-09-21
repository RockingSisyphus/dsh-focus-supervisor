"""Capture the real signed-in desktop and export structured application reports.

Run manually after arranging windows. Does not open/activate/close applications
or invoke models. On Windows launch in the interactive user session, not QGA's
SYSTEM session; see WINDOWS_VM.md.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from focus_demo.collectors import Collector
from focus_demo.prompts import timeline
from focus_demo.reports import overview, build_reports


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--backend', choices=['gnome', 'windows'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=3)
    args = parser.parse_args()
    if sys.platform == 'win32':
        import ctypes, os
        session = ctypes.c_ulong()
        ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
        if session.value == 0: parser.error('Run in the interactive desktop session, not Session 0')
    root = args.output.resolve(); root.mkdir(parents=True, exist_ok=True)
    def save(name, data):
        (root/name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    collector = Collector(args.backend, 49998, 49999, SimpleNamespace(
        data_dir=str(root), screenshots=True, ui_text=True, detail_interval=2,
        browser_text=False, browser_skill=False, log_root=[], system_logs=False))
    samples = []
    try:
        for i in range(max(2, args.samples)):
            sample = collector.capture(); sample['sample_id'] = i
            samples.append(sample); save('samples.json', samples)
            time.sleep(2)
    finally: collector.suspend()
    report = timeline(samples, 2)
    save('ai-report.json', {'overview': overview(report), 'programs': build_reports(report),
                            'evidence': report['evidence']})
    save('completed.json', {'samples':len(samples), 'real_model_called':False,
                            'note':'Sampling completed; inspect text and screenshots for coverage.'})


if __name__ == '__main__': main()
