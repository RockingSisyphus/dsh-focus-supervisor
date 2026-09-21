"""Legacy CLI delegates to the sole catalog entry; historical implementation is archived."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'dshmonitor-test-pack'))
from run import main
if __name__=='__main__':
    args=[a for a in sys.argv[1:] if a!='--desktop']
    sys.argv=[sys.argv[0],*['test','--case','heartbeat-evidence-actions'],*args]
    raise SystemExit(main())
