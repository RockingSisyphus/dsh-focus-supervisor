"""Legacy demo CLI forwards to the real JSON catalog."""
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'dshmonitor-test-pack'))
from run import main
if __name__=='__main__':
    args=sys.argv[1:]
    if '--scenario' in args:
        i=args.index('--scenario');selection=args[i+1];del args[i:i+2]
        if selection!='all':
            raise SystemExit('Old demo IDs are retired; select a real JSON case with --case. See docs/archive/test-harness/README.md')
    sys.argv=[sys.argv[0],'test','--guest','--platform','windows',*args]
    raise SystemExit(main())
