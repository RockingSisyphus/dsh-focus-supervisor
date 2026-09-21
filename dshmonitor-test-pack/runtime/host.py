"""Pack launch compatibility; execution is provided by dsh_test_harness."""
from support import *
import sys
from pathlib import Path
from dsh_test_harness.host import main
if __name__=='__main__':
    if '--modules' not in sys.argv:sys.argv += ['--modules',str(Path(__file__).resolve().parents[2]/'dsh-plugin/node_modules')]
    if '--case' not in sys.argv:sys.argv += ['--case',str(Path(__file__).with_name('json_case.py'))]
    main()
