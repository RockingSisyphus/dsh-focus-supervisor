"""Thin pack entry; all window contents come from JSON."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'test-support'))
from dsh_test_harness.gui import run
run(Path(sys.argv[1]))
