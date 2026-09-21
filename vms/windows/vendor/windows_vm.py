"""Compatibility alias to the shared VM implementation."""
import sys
from pathlib import Path
sys.path.insert(0,str(next(p for p in Path(__file__).resolve().parents if (p/'test-support').is_dir())/'test-support'))
from dsh_test_harness.vm import windows_vm as implementation
sys.modules[__name__]=implementation
if __name__=='__main__' and hasattr(implementation,'main'):implementation.main()
