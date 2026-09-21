#!/usr/bin/env python3
"""Single entry for the JSON catalog, contracts and real VM product flows."""
import argparse,json,os,subprocess,sys,time,tempfile,shutil
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
PACK=Path(__file__).resolve().parent;ROOT=PACK.parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'test-support'))
from dsh_test_harness.catalog import discover,select,capability_features
from dsh_test_harness.results import write_report

def load_cases(suite=None,extended=False,manual=False):
    return select(discover(PACK),extended=extended,manual=manual)

def report(out,results,suite,previous=None):
    catalog=discover(PACK) if (PACK/'cases').exists() else []
    return write_report(out,results,suite.get('features',[])+capability_features(PACK.parent),previous,[c for _,c in catalog])

def execute_case(path,case,out,args):
    target=out/case['id'];start=time.monotonic()
    record={k:case[k] for k in ('id','title','engine','verification','features')}
    record['verification_layer']=case.get('verification_layer',{'product':'dsh','desktop-contract':'desktop','contract':'protocol'}.get(case['verification'],'protocol'))
    record['evidence']=str(target)
    record.update(platform='windows' if sys.platform=='win32' else 'linux',status='not_run')
    if record['platform'] not in case['platforms']:
        return {**record,'status':'skipped','reason':'Not applicable to this platform'}
    if case.get('archived_reason'):
        return {**record,'status':'not_run','reason':case['archived_reason']}
    if case['engine']=='dsh':
        argv=[sys.executable,str(PACK/'runtime/host.py'),'--test-file',str(path),'--output',str(target),'--modules',str(args.modules.resolve()),'--browser-plugin',str(args.browser_plugin.resolve())]
        if args.human_review:argv+=['--human-review','--human-step-delay',str(args.human_step_delay)]
    else:
        target.mkdir(parents=True)
        argv=[a.replace('$python',sys.executable).replace('$output',str(target)).replace('$case',str(path)) for a in case['argv']]
    temporary=None
    env=os.environ.copy();env.update(PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
    env["PYTHONPATH"]=str(ROOT/"test-support")+os.pathsep+env.get("PYTHONPATH","")
    if case['engine']=='command':
        temporary=Path(tempfile.mkdtemp(prefix='dsh-test-'))
        env.update(TMPDIR=str(temporary),TMP=str(temporary),TEMP=str(temporary),PYTHONIOENCODING='utf-8',PYTHONUTF8='1')
        if '-m' in argv and 'pytest' in argv:argv+=['--junitxml',str(target/'junit.xml')]
    try:
        with (out/(case['id']+'.log')).open('w',encoding='utf-8') as log:
            process=subprocess.Popen(argv,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:code=process.wait(timeout=None if args.human_review else case.get('timeout',180))
            except subprocess.TimeoutExpired:
                from dsh_test_harness.desktop import Desktop
                Desktop().stop_process(process)
                if case['engine']=='dsh' and (target/'cleanup-state.json').exists():
                    sys.path.insert(0,str(PACK/'runtime'))
                    try:
                        from backend import cleanup_interrupted
                        cleanup=cleanup_interrupted(target)
                    except Exception as error:cleanup={'status':'failed','error':str(error)}
                    (target/'interrupted-cleanup.json').write_text(json.dumps(cleanup,ensure_ascii=False,indent=2),encoding='utf-8')
                raise TimeoutError('Scenario exceeded '+str(case.get('timeout',180))+' seconds')
        detail=json.loads((target/'result.json').read_text(encoding='utf-8')) if (target/'result.json').exists() else {}
        if case['engine']=='dsh' and not detail:
            record.update(status='failed',failure_stage='environment',error=f'Product host did not produce result.json (exit {code}); see {case["id"]}.log')
        elif code!=case.get('expect_exit',0) or (detail and detail.get('status')!='passed'):
            diagnostics=detail.get('page_errors',[])+detail.get('backend_errors',[])
            record.update(status='failed',failure_stage=detail.get('failure_stage','scenario'),error=detail.get('error') or '; '.join(map(str,diagnostics)) or f'exit {code}; see {case["id"]}.log')
        else:record.update(status='passed',model_requests=detail.get('requests',0))
        if (target/'steps.json').exists():
            failed=next((s for s in json.loads((target/'steps.json').read_text(encoding='utf-8')) if s['status']=='failed'),None)
            if failed:
                failures=[s for s in json.loads((target/'steps.json').read_text(encoding='utf-8')) if s['status']=='failed']
                record.update(status='failed',failure_stage=failed.get('failure_stage','scenario'),error=failed['id']+': '+failed['error'],failures=failures)
    except Exception as e:record.update(status='failed',failure_stage='environment' if isinstance(e,OSError) else 'scenario',error=f'{type(e).__name__}: {e}')
    finally:
        if temporary:
            try:shutil.rmtree(temporary)
            except OSError as error:
                record['cleanup_error']=str(error)
                if record['status']!='failed':record.update(status='failed',failure_stage='cleanup',error=str(error))
    record['seconds']=round(time.monotonic()-start,2)
    print(record['status'].upper(),case['id'],record.get('error',''),flush=True)
    return record

def run_guest(cases,out,args,suite):
    rows=[]
    def progress():
        completed={r['id'] for r in rows}
        pending=[{**{k:c[k] for k in ('id','title','verification','features')},'platform':'windows' if sys.platform=='win32' else 'linux','status':'not_run','reason':'Selected but not completed'} for _,c in cases if c['id'] not in completed]
        summary=report(out,rows+pending,suite)
        if args.guest and os.environ.get('DSH_TEST_VM_INPUT_URL'):
            from dsh_test_harness.vm.input import request
            try:request('progress',timeout=2,summary=summary)
            except Exception as error:print('Live progress unavailable:',error,flush=True)
    progress()
    contracts=[(p,c) for p,c in cases if c['verification']=='contract']
    desktop=[(p,c) for p,c in cases if c['verification']!='contract']
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for f in as_completed([pool.submit(execute_case,p,c,out,args) for p,c in contracts]):
            rows.append(f.result());progress()
    for p,c in desktop:
        rows.append(execute_case(p,c,out,args));progress()
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['test','list','report'],nargs='?',default='test')
    p.add_argument('--input',type=Path,action='append',help='Existing summary.json to combine; retains every supplied round')
    p.add_argument('--platform',choices=['linux','windows','both'],default='both')
    p.add_argument('--local',action='store_true',help='Run contracts on this host')
    p.add_argument('--guest',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--workers',type=int,default=8)
    p.add_argument('--case',action='append');p.add_argument('--extended',action='store_true')
    p.add_argument('--human-review',action='store_true');p.add_argument('--human-step-delay',type=float,default=2)
    p.add_argument('--output',type=Path);p.add_argument('--baseline',type=Path)
    p.add_argument('--prepare',action='store_true')
    p.add_argument('--windows-config','--vm-config',type=Path)
    p.add_argument('--linux-config',type=Path)
    p.add_argument('--cold-boot',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--skip-system',action='store_true',help=argparse.SUPPRESS)
    p.add_argument('--modules',type=Path,default=ROOT/'dsh-plugin/node_modules')
    p.add_argument('--browser-plugin',type=Path,default=Path.home()/'.dsh/profiles/web/node_modules/@wxg-prc-cpg/browser-skill-dsh-plugin')
    args=p.parse_args()
    if args.workers<1:p.error('--workers must be positive')
    try:cases=select(discover(PACK),args.case,args.extended)
    except ValueError as e:p.error(str(e))
    if args.command=='list':
        if not args.case:cases=discover(PACK)
        for _,c in cases:print(c['id'],c['group'],','.join(c['platforms']),c['verification'],c['title'],sep='\t')
        return 0
    if args.local:
        if args.case and any(c['verification']!='contract' for _,c in cases):p.error('--local is for contracts; product/desktop scenarios run in VMs')
        cases=[(path,c) for path,c in cases if c['verification']=='contract']
    out=(args.output or ROOT/'artifacts/dshmonitor-test-pack'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')).resolve()
    if out.exists() and any(x.name!='guest-console.log' for x in out.iterdir()):p.error('Output directory is not empty; choose a new run directory')
    out.mkdir(parents=True,exist_ok=True)
    suite=json.loads((PACK/'suite.json').read_text(encoding='utf-8'))
    if args.command=='report':
        if not args.input:p.error('report requires --input summary.json')
        rows=[]
        for filename in args.input:
            source=filename.resolve()
            for row in json.loads(source.read_text(encoding='utf-8'))['cases']:
                rows.append({**row,'run':str(source),'evidence':row.get('evidence') or str(source.parent)})
    elif args.local or args.guest:rows=run_guest(cases,out,args,suite)
    else:
        from dsh_test_harness.vm.dispatch import run
        rows=run(ROOT,cases,out,args)
    previous=json.loads(args.baseline.read_text(encoding='utf-8')) if args.baseline else None
    value=report(out,rows,suite,previous)
    print('Report:',out/'report.md',flush=True)
    return 1 if value['counts']['failed'] or value['counts']['not_run'] else 0

if __name__=='__main__':raise SystemExit(main())
