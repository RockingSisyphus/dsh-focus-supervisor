"""Legacy GNOME install CLI; delegates to the actual VM installation case."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dshmonitor-test-pack'))
from run import main
if __name__=='__main__':
    sys.argv=[sys.argv[0],'test','--platform','linux','--case','ui-setup-click',*sys.argv[1:]]
    raise SystemExit(main())
