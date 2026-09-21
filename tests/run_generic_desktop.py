"""Legacy CLI forwards to the JSON/VM runner; the former isolated desktop is retired."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'dshmonitor-test-pack'))
from run import main
if __name__=='__main__':
    sys.argv=[sys.argv[0],'test','--case','desktop-fixture-foundation',*sys.argv[1:]]
    raise SystemExit(main())
