"""Desktop transport boundaries and deployed version agreement."""
import re
from pathlib import Path
from focus_demo.desktop_bridge import VERSION
from focus_demo.desktop_setup import EXPECTED_EXTENSION_CODE_VERSION
ROOT=Path(__file__).resolve().parents[1]

def test_versions_agree():
    source=(ROOT/'gnome-extension/extension.js').read_text()
    assert re.search(r"const CODE_VERSION = '([^']+)'",source).group(1)==VERSION==EXPECTED_EXTENSION_CODE_VERSION
    assert f"EXTENSION_CODE_VERSION = '{VERSION}'" in (ROOT/'deploy/focus_window.py').read_text()

def test_no_periodic_or_synchronous_filesystem_work():
    for path in ('gnome-extension/extension.js','test-support/gnome-driver/extension.js'):
        source=(ROOT/path).read_text()
        for banned in ('timeout_add','load_contents(','.replace(','.replace_contents(','.close(null)','.delete(null)','query_exists('):
            assert banned not in source,(path,banned)

def test_actions_keep_request_identity():
    source=(ROOT/'gnome-extension/extension.js').read_text()
    assert 'request_id:request.id' in source
    assert "w.get_pid()===request.pid" in source
