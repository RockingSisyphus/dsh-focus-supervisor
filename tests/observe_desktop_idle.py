"""Read-only idle observer; never activates or captures the desktop itself."""
import argparse,json,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=float,default=60);a=p.parse_args()
a.output.mkdir(parents=True,exist_ok=True)
paths=[Path.home()/'.cache'/name/file for name in ('focus-demo','tabfocus-demo') for file in ('gnome-snapshot.json','extension-state.json')]
rows=[];end=time.monotonic()+a.seconds
while True:
 rows.append({'at':time.time(),'files':{str(x):x.stat().st_mtime_ns if x.exists() else None for x in paths}})
 if time.monotonic()>=end:break
 time.sleep(min(1,max(0,end-time.monotonic())))
changes={str(x):sum(b['files'][str(x)]!=c['files'][str(x)] for b,c in zip(rows,rows[1:])) for x in paths}
(a.output/'idle-observation.json').write_text(json.dumps({'samples':rows,'changes':changes},indent=2))
assert not any(changes.values()),'Idle desktop files continue updating: '+str(changes)
