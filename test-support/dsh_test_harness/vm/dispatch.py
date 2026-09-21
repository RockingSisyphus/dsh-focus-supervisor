"""Transport a selected catalog to existing VMs; preserve initial power state."""
import json,subprocess,sys,time,zipfile,shlex,io,uuid
from pathlib import Path
from .linux_vm import LinuxVM
from .windows_vm import WindowsVM,wait_for

def configuration(root,platform,args):
    override=getattr(args,platform+'_config',None)
    source=root/'dshmonitor-test-pack/cross-platform.json'
    catalog=json.loads(source.read_text()) if source.exists() else {}
    path=override or catalog.get('platforms',{}).get(platform,{}).get('config') or str(Path.home()/'.config/dshmonitor-test-pack'/f'{platform}.json')
    return json.loads(Path(path).expanduser().read_text())

def guest_source(root,out,ids,workers,human,delay,admin_password=None,session_directory=None,installed_host=False):
    return f'''import os,sys,subprocess,json,zipfile,traceback
from pathlib import Path
root=Path({str(root)!r});out=Path({str(out)!r});out.mkdir(parents=True,exist_ok=True)
os.chdir(root)
if {session_directory!r}:os.environ["DSH_TEST_SESSION_DIRECTORY"]={session_directory!r}
if {installed_host!r}:os.environ["DSH_TEST_INSTALLED_HOST"]="1"
if {admin_password!r}:os.environ["DSH_TEST_ADMIN_PASSWORD"]={admin_password!r}
try:
 executable=str(Path(sys.executable).with_name('python.exe')) if os.name=='nt' else sys.executable
 argv=[executable,'test-support/run_guest.py','dshmonitor-test-pack/run.py','test','--guest','--output',str(out),'--workers',{str(workers)!r}]
 for name in {ids!r}:argv+=['--case',name]
 if {human!r}:argv+=['--human-review','--human-step-delay',{str(delay)!r}]
 with (out/'guest-console.log').open('w',encoding='utf-8') as log:
  result=subprocess.run(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 (out/'runner-exit.json').write_text(json.dumps(dict(returncode=result.returncode)),encoding='utf-8')
except Exception:
 (out/'transport-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
finally:
 try:
  with zipfile.ZipFile(str(out)+'.zip','w',zipfile.ZIP_DEFLATED) as z:
   for d,dirs,files in os.walk(out):
    dirs[:]=[x for x in dirs if x not in ('node_modules','__pycache__','home','browser-profile','bsk')]
    for n in files:
     p=Path(d)/n
     if p.is_file():z.write(p,p.relative_to(out))
 except Exception:
  error=traceback.format_exc()
  (out/'transport-error.txt').write_text(error,encoding='utf-8')
  with zipfile.ZipFile(str(out)+'.zip','a') as z:z.writestr('transport-error.txt',error)
 finally:
  Path(str(out)+'.done').write_text('done')
'''

def unpack(data,out):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for member in z.infolist():
            if not (out/member.filename).resolve().is_relative_to(out.resolve()):raise ValueError('Invalid result path')
        z.extractall(out)

def run(root,cases,out,args):
    rows=[]
    platforms=['linux','windows'] if args.platform=='both' else [args.platform]
    if not getattr(args,'_clean_overlay',False):
        fresh=[(p,c) for p,c in cases if c.get('installation')=='fresh']
        for path,case in fresh:
            for platform in platforms:
                if platform not in case['platforms']:continue
                try:
                    from .overlay import LinuxOverlay,WindowsOverlay
                    from copy import copy
                    config=configuration(root,platform,args)
                    factory=LinuxOverlay if platform=='linux' else WindowsOverlay
                    diagnostics=out/('installation-'+case['id'])/platform/'environment'
                    diagnostics.mkdir(parents=True,exist_ok=True)
                    with factory(config['clean_baseline'],diagnostic_out=diagnostics) as isolated:
                        child=copy(args);child.platform=platform;child._clean_overlay=True;child._config=isolated;child.prepare=True
                        rows.extend(run(root,[(path,case)],out/('installation-'+case['id'])/platform,child))
                except Exception as error:
                    rows.append({**case,'platform':platform,'status':'failed','failure_stage':'environment','error':str(error)})
        cases=[(p,c) for p,c in cases if c.get('installation')!='fresh']
    for _,case in cases:
        if case.get('execution')=='vm-orchestration':
            from .scenario import execute
            for platform in (['linux','windows'] if args.platform=='both' else [args.platform]):
                if platform in case['platforms']:rows.append(execute(root,case,out/platform/case['id'],args,platform))
    cases=[(p,c) for p,c in cases if c.get('execution')!='vm-orchestration']
    platforms=['linux','windows'] if args.platform=='both' else [args.platform]
    for platform in platforms:
        selected=[c for _,c in cases if platform in c['platforms']]
        for _,c in cases:
            if platform not in c['platforms']:rows.append({**c,'platform':platform,'status':'skipped','reason':'Not applicable to this platform'})
        if not selected:continue
        target=out/platform;target.mkdir(parents=True,exist_ok=True)
        vm=None;was_running=None;guestout=None
        try:
            config=getattr(args,'_config',None) or configuration(root,platform,args)
            vm=(LinuxVM if platform=='linux' else WindowsVM)(config)
            was_running=vm.running();vm.human_review=args.human_review;vm.diagnostic_out=target
            (target/'environment.json').write_text(json.dumps({'platform':platform,'initially_running':was_running,'installation_environment':config.get('installation_environment','existing-system'),'vm':str(vm.directory)},indent=2))
            if getattr(args,'cold_boot',False) and was_running:vm.shutdown()
            vm.start_login()
            if platform=='linux':
                environment=json.loads((target/'environment.json').read_text())
                environment['graphics']=vm.graphics()
                (target/'environment.json').write_text(json.dumps(environment,indent=2))
            vm.deploy(target)
            guest_run=out.name+'-'+uuid.uuid4().hex[:12]
            if platform=='linux':
                if args.prepare:vm.prepare()
                guestout='/home/tester/dafeiyu-test/results/'+guest_run
                source=guest_source(vm.root,guestout,[c['id'] for c in selected],args.workers,args.human_review,args.human_step_delay,config.get('admin_password'),getattr(args,'_session_directory',None),installed_host=getattr(args,'_installed_host',False))
                command='systemd-run --user --quiet --wait --pipe --collect --setenv=PATH="$HOME/.local/node/bin:$PATH" --working-directory='+shlex.quote(vm.root)+' '+shlex.quote(vm.root+'/.venv/bin/python')+' -'
                print('Linux: running selected scenarios in logged-in Wayland session',flush=True)
                from .input import desktop_input
                with desktop_input(vm,target) as input_url:
                    source='import os\nos.environ["DSH_TEST_VM_INPUT_URL"]='+repr(input_url)+'\n'+source
                    vm.ssh(command,None if args.human_review else sum(c.get('timeout',180) for c in selected)+600,input=source.encode())
                data=subprocess.check_output(['ssh','-i',config['key'],'-p',str(config['port']),'-o','BatchMode=yes','-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+str(vm.directory/'known_hosts'),'tester@127.0.0.1','cat '+shlex.quote(guestout+'.zip')])
            else:
                if args.prepare:vm.prepare()
                guestout=vm.root+'\\results\\'+guest_run
                node=vm.config.get('node_directory',vm.root+'\\node-v24.18.0-win-x64')
                source='import os\nos.environ["PATH"]='+repr(node)+'+";"+os.environ["PATH"]\n'+guest_source(vm.root+'\\project',guestout,[c['id'] for c in selected],args.workers,args.human_review,args.human_step_delay,session_directory=getattr(args,'_session_directory',None),installed_host=getattr(args,'_installed_host',False))
                from .input import desktop_input
                with desktop_input(vm,target) as input_url:
                    source='import os\nos.environ["DSH_TEST_VM_INPUT_URL"]='+repr(input_url)+'\n'+source
                    vm.task(source,elevated=False)
                    print('Windows: running selected scenarios in interactive user session',flush=True)
                    def progress():
                        try:return vm.get(guestout+'.done')==b'done'
                        except RuntimeError:return False
                    wait_for(progress,None if args.human_review else sum(c.get('timeout',180) for c in selected)+600)
                cleanup_source="""import json,pathlib,psutil
root=pathlib.Path(ROOT)
results=[]
for path in root.rglob('cleanup-processes.json'):
 for item in json.loads(path.read_text()):
  try:
   process=psutil.Process(item['pid'])
   if abs(process.create_time()-item['created_at'])<.01:
    process.terminate();process.wait(10)
   results.append({'pid':item['pid'],'status':'cleaned'})
  except psutil.NoSuchProcess:results.append({'pid':item['pid'],'status':'already_exited'})
print(json.dumps(results))
""".replace('ROOT',repr(guestout))
                cleanup=vm.python(cleanup_source)
                (target/'vm-cleanup.json').write_text(cleanup,encoding='utf-8')
                data=vm.get(guestout+'.zip')

            unpack(data,target)
            if (target/'transport-error.txt').exists():raise RuntimeError((target/'transport-error.txt').read_text(encoding='utf-8'))
            summary=json.loads((target/'summary.json').read_text(encoding='utf-8'))
            rows.extend({**r,'evidence':str(target/r['id'])} for r in summary['cases'])
            exit_file=target/'runner-exit.json'
            if exit_file.exists() and json.loads(exit_file.read_text())['returncode'] and not any(r['status']=='failed' for r in summary['cases']):
                rows.append({'id':'guest-runner','platform':platform,'verification':'environment','status':'failed',
                             'failure_stage':'environment','error':'Guest runner stopped before completing selected cases; see guest-console.log',
                             'evidence':str(target)})
        except Exception as e:
            for c in selected:rows.append({**c,'platform':platform,'status':'failed','failure_stage':'environment','error':f'{type(e).__name__}: {e}'})
            (target/'transport-error.txt').write_text(str(e),encoding='utf-8')
            if vm and platform=='windows' and guestout:
                # Preserve partial real execution when the guest wrapper cannot
                # complete its archive. Never substitute these for a passed run.
                names=['guest-console.log','summary.json']
                for case in selected:
                    names += [case['id']+'/'+name for name in ('steps.json','result.json','error-traceback.txt','process-1.log')]
                    names.append(case['id']+'.log')
                for name in names:
                    try:
                        content=vm.get(guestout+'\\'+name.replace('/','\\'))
                        path=target/'partial'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
                    except (OSError,RuntimeError,TimeoutError):pass
        finally:
            if vm and platform=='windows':
                try:
                    diagnostic=vm.powershell(r"""
$base=Join-Path $env:ProgramData 'Dafeiyu'
$tasks=@(Get-ScheduledTask -TaskName 'Dafeiyu-*' -ErrorAction SilentlyContinue | ForEach-Object {
 $info=$_ | Get-ScheduledTaskInfo
 @{name=$_.TaskName;state=[string]$_.State;result=$info.LastTaskResult;last_run=[string]$info.LastRunTime}
})
$log=Join-Path $base 'service-error.log'
$config=Join-Path $base 'config.json'
$notification=$null
if(Test-Path $config){
 $data=(Get-Content $config -Raw | ConvertFrom-Json).data_dir
 $notification=[string]::Join("`n",[string[]]@(Get-Content (Join-Path $data 'notification-error.log') -Tail 80 -ErrorAction SilentlyContinue))
}
@{tasks=$tasks;startup_error=$(if(Test-Path $log){Get-Content $log -Raw}else{$null});notification_error=$notification;
 timeline=@(Get-Content (Join-Path $base 'service-startup.jsonl') -ErrorAction SilentlyContinue | Select-Object -Last 80 | ForEach-Object {ConvertFrom-Json -InputObject ([string]$_)})} | ConvertTo-Json -Depth 5
""")
                    (target/'service-startup.json').write_text(diagnostic,encoding='utf-8')
                except Exception as error:(target/'service-diagnostic-error.txt').write_text(str(error),encoding='utf-8')
            if vm and platform=='windows' and hasattr(vm,'cleanup_task'):
                try:vm.cleanup_task()
                except Exception as error:rows.append({'id':'vm-task-cleanup','platform':platform,'verification':'environment','status':'failed','failure_stage':'cleanup','error':str(error)})
            if vm:
                from .vm_display import close_viewer
                close_viewer(vm)
            if vm and was_running is False:
                try:vm.shutdown()
                except Exception as e:rows.append({'id':'vm-shutdown','platform':platform,'verification':'environment','status':'failed','failure_stage':'cleanup','error':str(e)})
    return rows
