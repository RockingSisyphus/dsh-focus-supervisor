"""Historical diagnostic forwards to the controlled Wayland browser scenario."""
import subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
raise SystemExit(subprocess.call([sys.executable,str(root/'dshmonitor-test-pack/run.py'),'test','--platform','linux','--case','browser-visibility',*sys.argv[1:]]))
