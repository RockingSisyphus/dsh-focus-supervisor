"""VM-only syscall-delay injection and independent compositor latency sampling."""
import os,signal,subprocess,time,json
from pathlib import Path

def delay(scenario,step):
    if not os.environ.get('DSH_TEST_GUEST') or os.name=='nt':raise RuntimeError('I/O delay is limited to the disposable Linux test guest')
    target=step.get('target','desktop')
    if target=='desktop':pid=int(subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip())
    else:
        import psutil
        matches=[p.pid for p in psutil.process_iter(['cmdline']) if any(Path(arg).name=='chat_service.py' for arg in p.info['cmdline'] or [])]
        if len(matches)!=1:raise RuntimeError(f'Expected one installed service; found {matches}')
        pid=matches[0]
    path=scenario.out/(step['id']+'-fsync.log')
    error=(scenario.out/(step['id']+'-tracer.log')).open('w')
    argv=['sudo','timeout','--signal=TERM',str(step.get('duration_seconds',180)),'strace','-tt','-T','-p',str(pid),'-e','trace=fsync,fdatasync','-e','inject=fsync:delay_exit='+str(step['delay_ms'])+'ms','-o',str(path)]
    if target=='service':
        argv.insert(argv.index('-tt'),'-f')
        argv.extend(['-e','inject=fdatasync:delay_exit='+str(step['delay_ms'])+'ms'])
    process=subprocess.Popen(argv,stdout=error,stderr=error,start_new_session=True)
    def close():
        if process.poll() is None:
            subprocess.run(['sudo','kill','-TERM','--','-'+str(process.pid)],capture_output=True)
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        error.close()
    scenario.backend.cleanup_callbacks.append(close)
    scenario.io_delay=(close,path)
    time.sleep(.5)
    if process.poll() is not None:raise RuntimeError('Unable to attach syscall delay; see tracer log')
    return {'pid':pid,'delay_ms':step['delay_ms'],'scope':target+' fsync syscall delay (not a disk hardware fault)','trace':str(path)}

def latency(scenario,step):
    from focus_demo.desktop_bridge import call
    deadline=time.monotonic()+step['seconds'];rows=[]
    while True:
        start=time.monotonic()
        try:result=scenario.backend.request('/state',{}) if step.get('target')=='service' else call('status');error=None
        except Exception as problem:result=None;error=str(problem)
        rows.append({'at':time.time(),'seconds':time.monotonic()-start,'error':error,'status':result})
        (scenario.out/(step['id']+'-latency.json')).write_text(json.dumps(rows,indent=2))
        if time.monotonic()>=deadline:break
        scenario.page.wait_for_timeout(min(.2,max(0,deadline-time.monotonic()))*1000)
    values=sorted(r['seconds'] for r in rows)
    return {'samples':len(rows),'errors':sum(bool(r['error']) for r in rows),'max_seconds':max(values),'p95_seconds':values[int((len(values)-1)*.95)]}


def runtime_storage(scenario,step):
    """Fill a private, owned tmpfs in the test VM; never fill the desktop runtime."""
    if not os.environ.get('DSH_TEST_GUEST') or os.name=='nt':raise RuntimeError('Storage injection requires a Linux test VM')
    from focus_demo.desktop_bridge import runtime_directory
    if step['action']=='restore':
        scenario.runtime_storage_cleanup()
        return {'restored':True}
    directory=runtime_directory();directory.mkdir(exist_ok=True)
    subprocess.run(['sudo','mount','-t','tmpfs','-o',f'size=128k,mode=700,uid={os.getuid()},gid={os.getgid()}','dafeiyu-test-full',str(directory)],check=True,capture_output=True)
    mounted=True
    def cleanup():
        nonlocal mounted
        if mounted:
            subprocess.run(['sudo','umount',str(directory)],check=True,capture_output=True)
            mounted=False
    scenario.runtime_storage_cleanup=cleanup
    scenario.backend.cleanup_callbacks.append(cleanup)
    try:
        with (directory/'test-owned-fill').open('wb',buffering=0) as output:
            while True:output.write(bytes(4096))
    except OSError as error:
        import errno
        if error.errno!=errno.ENOSPC:raise
    return {'directory':str(directory),'available_bytes':os.statvfs(directory).f_bavail*os.statvfs(directory).f_frsize,'scope':'private screenshot tmpfs only'}


def bridge_rpc(scenario,step):
    """Protocol observation only; product acceptance uses DSH and report evidence."""
    from focus_demo.desktop_bridge import call,runtime_directory
    start=time.monotonic()
    try:result=call(step['operation']);error=None
    except Exception as problem:result=None;error=str(problem)
    finally:
        if step['operation']=='capture':call('release')
    return {'result':result,'error':error,'seconds':time.monotonic()-start,'temporary_images':len(list(runtime_directory().glob('*.png')))}


def extension_state(scenario,step):
    if not os.environ.get('DSH_TEST_GUEST') or os.name=='nt':raise RuntimeError('Extension fault injection requires Linux VM')
    uuid='focus-demo@local.demo'
    def enable():subprocess.run(['gnome-extensions','enable',uuid],check=True,capture_output=True)
    if step['action']=='disable':
        scenario.backend.cleanup_callbacks.append(enable)
    subprocess.run(['gnome-extensions',step['action'],uuid],check=True,capture_output=True)
    from focus_demo.desktop_bridge import call
    deadline=time.monotonic()+5
    while True:
        try:state=call('status');connected=True
        except Exception as error:state={'error':str(error)};connected=False
        if connected==(step['action']=='enable') or time.monotonic()>=deadline:break
        time.sleep(.1)
    return {'connected':connected,'state':state,'at':time.time()}


def stop_delay(scenario,step):
    close,path=scenario.io_delay;close()
    trace=path.read_text(errors='replace')
    return {'trace':str(path),'delayed_calls':trace.count('DELAYED')}


def disconnect_capture(scenario,step):
    if not os.environ.get('DSH_TEST_GUEST') or os.name=='nt':raise RuntimeError('Capture disconnect test requires Linux VM')
    import sys,select
    from focus_demo.desktop_bridge import runtime_directory,call
    root=Path(__file__).resolve().parents[2]
    child=subprocess.Popen([sys.executable,'-c',"from focus_demo.desktop_bridge import call; import json,time; print(json.dumps(call('capture')),flush=True); time.sleep(30)"],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        if not select.select([child.stdout],[],[],8)[0]:raise TimeoutError('Capture client did not return')
        line=child.stdout.readline()
        if not line:raise RuntimeError(child.stderr.read())
        captured=json.loads(line)
        before=len(list(runtime_directory().glob('*.png')))
    finally:
        child.kill();child.wait(timeout=5)
    deadline=time.monotonic()+5
    while list(runtime_directory().glob('*.png')) and time.monotonic()<deadline:time.sleep(.05)
    return {'capture':captured,'files_before_disconnect':before,'files_after_disconnect':len(list(runtime_directory().glob('*.png'))),'status':call('status')}
