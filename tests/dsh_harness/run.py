"""Compatibility entry point; canonical runner and JSON scenarios live in the pack."""
import os
from pathlib import Path
import sys
if __name__ == '__main__':
    runner = Path(__file__).resolve().parents[2] / 'dshmonitor-test-pack/run.py'
    os.execv(sys.executable, [sys.executable, str(runner), 'test', *sys.argv[1:]])
