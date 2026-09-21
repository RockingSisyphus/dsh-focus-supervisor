"""Guest-side shared group runner; knows nothing about VM lifecycle."""
import argparse,json,os,subprocess,sys,zipfile
from pathlib import Path
from .suite import group_args,resolve_groups

def run(root,out,spec):
    os.environ['DSH_TEST_GUEST']='1';os.environ['PYTHONIOENCODING']='utf-8'
    spec=resolve_groups(root,spec)
    rows=[];out.mkdir(parents=True,exist_ok=True)
    for group in spec['groups']:
        folder=out/group['id'];folder.mkdir(parents=True,exist_ok=True)
        with (folder/'console.txt').open('w',encoding='utf-8') as log:
            try:code=subprocess.run([sys.executable,*group_args(group,folder)],cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=log,timeout=None if group.get('human_review') else group.get('timeout',300),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).returncode
            except subprocess.TimeoutExpired:code=124
        rows.append({'id':group['id'],'exit_code':code,'status':'passed' if code==0 else 'failed'})
        (out/'groups.json').write_text(json.dumps(rows),encoding='utf-8')
        print(group['id'],rows[-1]['status'],flush=True)
    with zipfile.ZipFile(str(out)+'.zip','w',zipfile.ZIP_DEFLATED) as z:
        for directory,dirs,files in os.walk(out):
            dirs[:]=[d for d in dirs if d not in ('node_modules','__pycache__')]
            for name in files:
                path=Path(directory)/name
                if path.is_file():z.write(path,path.relative_to(out))
    Path(str(out)+'.done').write_text('done',encoding='utf-8')
    return rows

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--spec',type=Path,default=Path('dshmonitor-test-pack/cross-platform.json'));a=p.parse_args()
    run(Path.cwd(),a.output,json.loads(a.spec.read_text(encoding='utf-8')))
