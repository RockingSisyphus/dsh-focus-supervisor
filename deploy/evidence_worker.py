"""One-shot user filesystem delivery, independent of the desktop sampling pipe."""
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from focus_demo.evidence_export import user_export,user_verify,user_cleanup

request=json.load(sys.stdin)
operation={'export':user_export,'verify_export':user_verify,'cleanup_export':user_cleanup}[request['operation']]
print(json.dumps(operation(request['payload']),ensure_ascii=False))
