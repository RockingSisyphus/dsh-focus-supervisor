"""Explicit Quickemu VM lifecycle; secrets stay in a private local config/env.

No hard power-off, login-registry edits or passwords in argv/artifacts. Existing
VMs are supported; run() always requests normal Windows shutdown after testing.
"""
import argparse,base64,getpass,json,os,socket,subprocess,sys,time,zipfile
from pathlib import Path
from functools import cached_property
from . import qemu_guest as guest

ROOT=Path(__file__).resolve().parents[3]
DEFAULT_CONFIG=Path.home()/'.config/dshmonitor-test-pack/windows.json'


def wait_for(fn, seconds=180):
    end=time.monotonic()+seconds if seconds is not None else None
    while end is None or time.monotonic()<end:
        try:
            value=fn()
            if value:return value
        except (OSError,RuntimeError):pass
        time.sleep(1)
    raise TimeoutError('VM operation did not complete before timeout')


class WindowsVM:
    def __init__(self,config):
        self.config=config
        self.directory=Path(config['directory']).expanduser()
        guest.SOCKET=str(self.directory/'windows-11-agent.sock')
        self.monitor=str(self.directory/'windows-11-monitor.socket')
        self.root=config.get('guest_root',r'C:\DafeiyuTest')
    @cached_property
    def mouse(self):
        from vncdotool import api
        return api.connect(str(self.directory/'dsh-test-vnc.sock'),timeout=10)
    def running(self):
        try:
            pid=int((self.directory/'windows-11.pid').read_text(encoding='utf-8'))
            args=Path(f'/proc/{pid}/cmdline').read_bytes()
            return b'qemu-system' in args and str(self.directory).encode() in args
        except (OSError,ValueError):return False
    def hmp(self,command):
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(8);s.connect(self.monitor)
            data=b''
            while b'(qemu)' not in data:data+=s.recv(8192)
            s.sendall((command+'\n').encode());data=b''
            while b'(qemu)' not in data:
                part=s.recv(8192)
                if not part:break
                data+=part
            # Never print/retain the HMP echo: it may include password keystrokes.
    def powershell(self,script,timeout=60):
        result=guest.ps("$ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); "+script,5)
        if 'running_pid' in result:
            pid=result['running_pid']
            raw=wait_for(lambda:(r if (r:=guest.call('guest-exec-status',{'pid':pid})).get('exited') else None),timeout)
            result={'exitcode':raw.get('exitcode'), 'stdout':base64.b64decode(raw.get('out-data','')).decode('utf-8','replace'), 'stderr':base64.b64decode(raw.get('err-data','')).decode('utf-8','replace')}
        if result.get('exitcode')!=0:raise RuntimeError('Guest command failed: '+result.get('stderr','')[-1000:])
        return result.get('stdout','')
    def desktop_ready(self):
        return self.powershell("$e=Get-Process explorer -ErrorAction SilentlyContinue; $l=Get-Process LogonUI -ErrorAction SilentlyContinue; if($e -and !$l){'ready'}",10).strip()=='ready'
    def start_login(self):
        launcher=None
        if not self.running():
            from .vm_display import start_windows
            launcher=start_windows(self)
        def connected():
            if launcher is not None and launcher.poll() is not None:
                log=self.directory/'test-launch.log'
                if getattr(self,'diagnostic_out',None) and log.exists():
                    saved=self.diagnostic_out/'test-launch.log'
                    saved.write_bytes(log.read_bytes());log=saved
                raise subprocess.CalledProcessError(launcher.returncode,'QEMU launcher; see '+str(log))
            return guest.call('guest-ping') is not None
        wait_for(connected,self.config.get('startup_timeout',600))
        print('Windows: guest agent connected',flush=True)
        if getattr(self,'human_review',False):
            from .vm_display import show_viewer
            show_viewer(self,'windows')
        if self.desktop_ready():return 'already_logged_in'
        secret=os.environ.get('DSHMONITOR_WINDOWS_PASSWORD') or self.config.get('password')
        if not secret:raise RuntimeError('Set DSHMONITOR_WINDOWS_PASSWORD or the private VM config password')
        # Configured VM account already selected on its normal Windows logon screen.
        if not secret.isascii() or not secret.isalnum():raise ValueError('HMP login currently supports ASCII letters/digits')
        from .windows_login import sign_in
        method=self.config.get('login_method','pin')
        print('Windows: waiting for a recognized '+method+' screen',flush=True)
        try:
            return sign_in(self,secret,timeout=self.config.get('login_timeout',180),method=method)
        except (TimeoutError,RuntimeError) as error:
            self.hmp('screendump '+str(self.directory/'login-timeout.ppm'))
            (self.directory/'login-timeout.ppm').chmod(0o600)
            failure_image=self.directory/'login-timeout.ppm'
            if getattr(self,'diagnostic_out',None):
                from PIL import Image
                failure_image=self.diagnostic_out/'login-timeout.png'
                Image.open(self.directory/'login-timeout.ppm').save(failure_image)
            raise RuntimeError('Windows login failed (not a monitor recovery failure): '+str(error)+
                               '; see '+str(failure_image)) from error
    def python(self,source,timeout=60):
        pid=guest.call('guest-exec',{'path':self.root+'\\venv\\Scripts\\python.exe','arg':['-c',source],'capture-output':True})['pid']
        result=wait_for(lambda:(r if (r:=guest.call('guest-exec-status',{'pid':pid})).get('exited') else None),timeout)
        output=base64.b64decode(result.get('out-data','')).decode('utf-8','replace')
        if result.get('exitcode')!=0:raise RuntimeError(base64.b64decode(result.get('err-data','')).decode('utf-8','replace'))
        return output
    def put(self,path,data):
        with guest.session() as connection:
            handle=connection.call('guest-file-open',{'path':path,'mode':'wb'})
            try:
                for offset in range(0,len(data),40000):connection.call('guest-file-write',{'handle':handle,'buf-b64':base64.b64encode(data[offset:offset+40000]).decode()})
            finally:connection.call('guest-file-close',{'handle':handle})
    def get(self,path):
        with guest.session() as connection:
            handle=connection.call('guest-file-open',{'path':path,'mode':'rb'});data=bytearray()
            try:
                while True:
                    result=connection.call('guest-file-read',{'handle':handle,'count':65536});data.extend(base64.b64decode(result.get('buf-b64','')))
                    if result.get('eof') or not result['count']:return bytes(data)
            finally:connection.call('guest-file-close',{'handle':handle})
    def deploy(self,out):
        out.mkdir(parents=True,exist_ok=True)
        archive=out/'test-source.zip'
        deleted=subprocess.check_output(['git','diff','HEAD','--no-renames','--diff-filter=D','--name-only','-z'],cwd=ROOT).decode().split('\0')
        paths=[self.root+'\\project\\'+name.replace('/','\\') for name in deleted if name]
        if paths:
            removals=self.root+'\\source-removals.json'
            self.put(removals,json.dumps(paths).encode('utf-8'))
            self.python("import json; from pathlib import Path; p=Path("+repr(removals)+"); [Path(name).unlink(missing_ok=True) for name in json.loads(p.read_text())]; p.unlink()")
        names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
            for name in dict.fromkeys(names):
                if name and (name.split('/')[0] in ('focus_demo','tests','deploy','dshmonitor-test-pack','dsh-plugin','test-support','scripts','gnome-extension') or name.startswith('requirements')):
                    p=ROOT/name
                    if p.is_file() and 'node_modules' not in p.parts:z.write(p,name)
        self.put(self.root+'\\test-source.zip',archive.read_bytes())
        self.powershell("Expand-Archive -Path '"+self.root+"\\test-source.zip' -DestinationPath '"+self.root+"\\project' -Force",120)
    def task(self,source,name=None,elevated=False):
        import uuid
        name=name or 'Dafeiyu-Test-'+uuid.uuid4().hex
        self._active_task=name;self._task_script=self.root+'\\'+name+'.py'
        self.put(self._task_script,source.encode('utf-8'))
        self.powershell("""$ErrorActionPreference='Stop'
$p=New-ScheduledTaskPrincipal -UserId (Get-CimInstance Win32_ComputerSystem).UserName -LogonType Interactive -RunLevel RUNLEVEL
$a=New-ScheduledTaskAction -Execute 'ROOT\\venv\\Scripts\\pythonw.exe' -Argument 'SCRIPT' -WorkingDirectory 'ROOT\\project'
$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName 'TASK' -Action $a -Principal $p -Settings $s -Force | Out-Null
Start-ScheduledTask -TaskName 'TASK'
""".replace('ROOT',self.root).replace('TASK',name).replace('RUNLEVEL','Highest' if elevated else 'Limited').replace('SCRIPT',self._task_script))
        return name
    def prepare(self):
        self.powershell("powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -File '"+self.root+"/project/test-support/prepare_windows.ps1' -Root '"+self.root+"'",1800)
    def cleanup_task(self):
        name=getattr(self,'_active_task',None)
        if not name:return
        self.powershell("Stop-ScheduledTask -TaskName '"+name+"' -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName '"+name+"' -Confirm:$false; Remove-Item -LiteralPath '"+self._task_script+"' -Force")
        self._active_task=None
    def shutdown(self):
        if not self.running():return
        try:self.powershell("shutdown.exe /s /t 0",10)
        except (OSError,RuntimeError,TimeoutError):pass  # QGA may disconnect as Windows exits.
        wait_for(lambda:not self.running(),self.config.get('shutdown_timeout',900))
        guest.reset()
        from .vm_display import close_viewer
        close_viewer(self)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['start','shutdown'])
    p.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    args=p.parse_args();vm=WindowsVM(json.loads(args.config.read_text(encoding='utf-8')))
    if args.action=='start':print(vm.start_login())
    else:vm.shutdown();print('powered_off')


if __name__=='__main__':main()
