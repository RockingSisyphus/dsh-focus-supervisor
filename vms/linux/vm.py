"""Compatibility alias; VM operations live in test-support."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'test-support'))
from dsh_test_harness.vm.linux_vm import *
if __name__=='__main__':
    import runpy
    runpy.run_module('dsh_test_harness.vm.linux_vm',run_name='__main__')
