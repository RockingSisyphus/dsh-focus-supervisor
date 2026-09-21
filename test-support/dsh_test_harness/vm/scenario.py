"""Generic JSON VM orchestration; product steps remain ordinary catalog cases."""
import json,time,uuid
from copy import copy
from pathlib import Path
from ..scenario import ScenarioEngine
from ..catalog import discover,select
from ..results import write_report
from .linux_vm import LinuxVM
from .windows_vm import WindowsVM

def execute(root,case,out,args,platform):
    from .dispatch import configuration,run
    out.mkdir(parents=True,exist_ok=True)
    vm=(LinuxVM if platform=='linux' else WindowsVM)(getattr(args,'_config',None) or configuration(root,platform,args))
    original=vm.running();vm.human_review=args.human_review
    vm.diagnostic_out=out
    session_name='.test-session-'+uuid.uuid4().hex[:12]
    session_directory=str(Path(vm.root)/session_name) if platform=='linux' else vm.root+'\\'+session_name
    record={**{k:case[k] for k in ('id','title','verification','features')},'platform':platform,'status':'not_run','evidence':str(out)}
    def cleanup_failure(error):
        record.setdefault('cleanup_errors',[]).append(str(error))
        if record['status']!='failed':record.update(status='failed',failure_stage='cleanup',error=str(error))
    def boot_id():
        if platform=='linux':return vm.ssh('cat /proc/sys/kernel/random/boot_id').strip()
        return vm.powershell('(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString("o")').strip()
    def reboot(step):
        before=boot_id()
        if platform=='linux':vm.reboot();vm.start_login()
        else:vm.shutdown();vm.start_login()
        now=float(vm.ssh('date +%s') if platform=='linux' else vm.powershell('[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()'))
        return {'before':before,'after':boot_id(),'completed_at':now}
    def read_service():
        source="import json,os;from pathlib import Path;p=Path('/etc/dafeiyu/config.json') if os.name!='nt' else Path(os.environ['PROGRAMDATA'])/'Dafeiyu/config.json';c=json.loads(p.read_text(encoding='utf-8-sig'));print((Path(c['data_dir'])/'status.json').read_text(encoding='utf-8'))"
        if platform=='linux':
            import shlex
            text=vm.ssh('python3 -c '+shlex.quote(source))
        else:text=vm.python(source)
        return json.loads(text)
    def observe_service(step):
        # Read the installed service's public status before starting test DSH.
        from ..wait import until
        observations=[]
        def read():
            state=read_service()
            task=next((t for t in state.get('live',[]) if t['id']==step['task_id']),None)
            observations.append({k:state.get(k) for k in ('server_time','last_sample_at','capture_error')})
            (out/(step['id']+'-observations.json')).write_text(json.dumps(observations,ensure_ascii=False,indent=2))
            if (task and (state.get('last_sample_at') or 0)>step['sampled_after']
                    and ('capture_error' not in step or state.get('capture_error')==step['capture_error'])):
                return {'task':task,'state':state,'observations':observations}
        return until(read,step.get('timeout',90))
    def checkpoint(step):
        filename=session_directory+('/checkpoint.json' if platform=='linux' else '\\checkpoint.json')
        if platform=='linux':
            import shlex
            return json.loads(vm.ssh('cat '+shlex.quote(filename)))
        return json.loads(vm.get(filename))
    session_locked=False
    def desktop_session(step):
        nonlocal session_locked
        from . import desktop_session as session
        if step['action']=='lock':
            session_locked=True
            return session.lock(vm,platform)
        if step['action']=='unlock':
            value=session.unlock(vm,platform);session_locked=False
            return value
        if step['action']=='logout':
            session_locked=True
            return session.logout(vm,platform)
        if step['action']=='login':
            value=session.login(vm,platform);session_locked=False
            return value
        if step['action']=='observe':
            observations=[];end=time.monotonic()+step.get('seconds',0)
            while True:
                observations.append({'at':time.time(),'locked':session.locked(vm,platform),'service':read_service()})
                if time.monotonic()>=end:break
                time.sleep(1)
            return {'observations':observations,**observations[-1]}
        raise ValueError('Unknown desktop session action '+step['action'])
    network_blocked=False
    network_rule='DafeiyuTest-'+uuid.uuid4().hex[:10]
    def network(step):
        nonlocal network_blocked
        enabled=step['enabled']
        ports=[80,443]
        if platform=='linux':
            import os,urllib.parse
            for key in ('HTTP_PROXY','HTTPS_PROXY'):
                address=urllib.parse.urlsplit(os.environ.get(key) or os.environ.get(key.lower()) or '')
                if address.port and address.port not in ports:ports.append(address.port)
        if not enabled:
            network_blocked=True
            if platform=='linux':
                vm.ssh(f"sudo iptables -N {network_rule} && sudo iptables -A {network_rule} -p tcp -m multiport --dports {','.join(map(str,ports))} -j REJECT && sudo iptables -I OUTPUT -j {network_rule}")
            else:vm.powershell(f"New-NetFirewallRule -Name '{network_rule}' -DisplayName '{network_rule}' -Direction Outbound -Action Block -Protocol TCP -RemotePort 80,443 | Out-Null")
        elif network_blocked:
            if platform=='linux':
                observation=vm.ssh(f"sudo iptables -L {network_rule} -v -n -x")
                vm.ssh(f"sudo iptables -D OUTPUT -j {network_rule}; sudo iptables -F {network_rule}; sudo iptables -X {network_rule}")
            else:
                observation=vm.powershell(f"Get-NetFirewallRule -Name '{network_rule}' | Select-Object Name,Enabled,Action | ConvertTo-Json; Remove-NetFirewallRule -Name '{network_rule}'")
            (out/'network-fault-observation.txt').write_text(observation,encoding='utf-8')
            network_blocked=False
        return {'downloads_enabled':enabled,'rule':network_rule,'ports':ports}
    guest_prepared=False
    def guest_case(step):
        nonlocal guest_prepared
        selected=select(discover(root/'dshmonitor-test-pack'),step['cases'])
        if any(c.get('execution')=='vm-orchestration' for _,c in selected):raise ValueError('Nested VM orchestration is not supported')
        child=copy(args);child.platform=platform;child.cold_boot=False
        child.prepare=args.prepare and not guest_prepared
        child._installed_host=case.get("installed_host",False)
        if case.get('persistent_session'):
            child._session_directory=session_directory
        target=out/step['id']
        rows=run(root,selected,target,child)
        if any(r.get('failure_stage')!='environment' for r in rows):guest_prepared=True
        return write_report(target,rows)
    commands={}
    def command_run(step):
        if platform!='linux':raise ValueError('Use interactive command.start on Windows')
        import shlex
        if step.get('prepare'):
            vm.deploy(out/'source');vm.prepare()
        source="import subprocess,json,os;env={**os.environ,**"+repr(step.get('env',{}))+"};r=subprocess.run("+repr(step['argv'])+",cwd="+repr(vm.root)+",env=env,capture_output=True);print(json.dumps({'code':r.returncode,'output':(r.stdout+r.stderr).decode('utf-8','replace')}))"
        result=json.loads(vm.ssh('python3 -c '+shlex.quote(source),step.get('timeout',1200)))
        return result
    def command_start(step):
        if platform!='windows':raise ValueError('Interactive command transport currently requires Windows')
        vm.deploy(out/'source')
        result_path=vm.root+'\\'+step['id']+'-'+out.parent.parent.name+'.json'
        source="import subprocess,json,pathlib\nresult=subprocess.run("+repr(step['argv'])+",cwd="+repr(vm.root+'\\project')+",capture_output=True)\npathlib.Path("+repr(result_path)+").write_text(json.dumps({'code':result.returncode,'output':(result.stdout+result.stderr).decode('utf-8','replace')}),encoding='utf-8')"
        task=vm.task(source,elevated=False)
        commands[step['id']]=result_path
        return {'id':step['id'],'task':task,'run_level':'Limited'}
    def command_wait(step):
        from .windows_vm import wait_for
        value=wait_for(lambda:json.loads(vm.get(commands[step['command']])),step.get('timeout',1200))
        (out/'command-result.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        vm.cleanup_task()
        return value
    def authorize(step):
        from .authorization import accept_windows
        return accept_windows(vm,out)
    engine=ScenarioEngine(case,out,values={'session_directory':session_directory,'guest_root':vm.root},actions={'case.run':guest_case,'vm.reboot':reboot,'vm.desktop_session':desktop_session,'vm.observe_service':observe_service,'vm.checkpoint':checkpoint,'vm.network':network,'vm.command.run':command_run,'vm.command.start':command_start,'vm.command.wait':command_wait,'vm.authorize':authorize})
    try:
        vm.start_login()
        record['initially_running']=original
        engine.run();record['status']='passed'
    except Exception as error:
        failed=next((s for s in engine.steps if s['status']=='failed'),{})
        record.update(status='failed',failure_stage=failed.get('failure_stage','environment'),error=str(error))
    finally:
        if session_locked:
            try:desktop_session({'action':'unlock'})
            except Exception as error:cleanup_failure(error)
        if network_blocked:
            try:network({'enabled':True})
            except Exception as error:cleanup_failure(error)
        if case.get('persistent_session'):
            try:
                directory=session_directory
                if platform=='linux':
                    import shlex
                    result=vm.ssh('python3 '+shlex.quote(vm.root+'/test-support/dsh_test_harness/vm/session_cleanup.py')+' '+shlex.quote(directory))
                else:
                    result=vm.python("import sys;sys.path.insert(0,"+repr(vm.root+'\\project\\test-support')+");from dsh_test_harness.vm.session_cleanup import clean;import json;print(json.dumps(clean("+repr(directory)+")))")
                (out/'session-cleanup.json').write_text(result,encoding='utf-8')
            except Exception as error:cleanup_failure(error)
        if platform=='windows':
            try:vm.cleanup_task()
            except Exception as error:cleanup_failure(error)
        if not original:
            try:vm.shutdown()
            except Exception as error:cleanup_failure(error)
        from .vm_display import close_viewer
        close_viewer(vm)
    (out/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    return record
