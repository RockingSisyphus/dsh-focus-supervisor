"""Compatibility import; implementation lives in the shared harness."""
from support import *
from dsh_test_harness.vm.linux_vm import *

if __name__=='__main__':
    import runpy
    runpy.run_module('dsh_test_harness.vm.linux_vm',run_name='__main__')
