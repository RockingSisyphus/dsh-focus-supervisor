"""Read-only observer of the installed service database, never initializes a Store."""
import json,sqlite3,sys
from pathlib import Path
request=json.load(sys.stdin)
p=Path(request['path']).resolve()
with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True,timeout=5) as db:
    if request['kind']=='samples':
        result=[{'sample_id':r[0],**json.loads(r[1])} for r in db.execute('SELECT id,body FROM samples WHERE task_id=? ORDER BY id',(request['id'],))]
    elif request.get('id') is not None:
        row=db.execute('SELECT body FROM documents WHERE kind=? AND id=?',(request['kind'],request['id'])).fetchone()
        result=json.loads(row[0]) if row else None
    else:result=[json.loads(r[0]) for r in db.execute('SELECT body FROM documents WHERE kind=? ORDER BY rowid',(request['kind'],))]
print(json.dumps(result,ensure_ascii=True))
