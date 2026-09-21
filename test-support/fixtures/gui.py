"""CLI for the shared native widget factory."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dsh_test_harness.gui import run
run(Path(sys.argv[1]))
