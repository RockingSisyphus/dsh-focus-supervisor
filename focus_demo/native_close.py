"""Disposable native close worker; killed by its caller before process fallback."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from focus_demo.collectors import GnomeDesktop,desktop_backend
from focus_demo.close_actions import _close_window,window_state,target_window

if __name__=='__main__':
    request=json.load(sys.stdin)
    desktop=GnomeDesktop() if request.get('backend')=='GnomeDesktop' else desktop_backend('auto')
    collector=SimpleNamespace(desktop=desktop)
    expected=request['expected']
    if request.get('operation')=='observe':
        identifier=target_window(expected)
        result={'closed':bool(identifier) and window_state(collector,expected)[1] is None,'window_id':identifier}
    else:result=_close_window(collector,expected)
    print(json.dumps(result))
