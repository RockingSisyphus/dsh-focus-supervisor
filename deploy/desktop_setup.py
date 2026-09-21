"""CLI usable from the root-owned installation or a checkout."""
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
# A lingering DSH service can predate the graphical login. Read only display keys.
try:
    env = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True, text=True, timeout=3)
    if env.returncode == 0:
        allowed = {'DISPLAY', 'WAYLAND_DISPLAY', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'}
        for line in env.stdout.splitlines():
            key, sep, value = line.partition('=')
            if sep and key in allowed:
                os.environ[key] = value
except (OSError, subprocess.TimeoutExpired):
    pass
from focus_demo.desktop_setup import main
raise SystemExit(main())
