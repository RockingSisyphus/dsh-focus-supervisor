"""Run a bounded helper and terminate its interpreter descendants on timeout."""
import os
import signal
import subprocess


def run_worker(argv, *, input=None, timeout, capture_output=True, text=True, check=False, cwd=None):
    process=subprocess.Popen(argv,stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE if capture_output else None,
                             stderr=subprocess.PIPE if capture_output else None,text=text,cwd=cwd,
                             start_new_session=os.name!='nt',
                             creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        stdout,stderr=process.communicate(input,timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if os.name=='nt':
            import psutil
            try:children=psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:children=[]
            process.kill()
            for child in children:
                try:child.kill()
                except psutil.NoSuchProcess:pass
            _,alive=psutil.wait_procs(children,timeout=1)
            if alive:raise RuntimeError('超时工作进程的子进程仍存活：'+str([p.pid for p in alive])) from error
        else:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        stdout,stderr=process.communicate(timeout=1)
        error.output=stdout;error.stderr=stderr
        raise
    result=subprocess.CompletedProcess(argv,process.returncode,stdout,stderr)
    if check:result.check_returncode()
    return result
