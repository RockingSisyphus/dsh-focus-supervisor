"""Dedicated Ubuntu GNOME guest. Host access uses a private SSH key, never sudo."""
import argparse,json,os,shlex,subprocess,time,tarfile,sys,urllib.parse
from pathlib import Path
from .windows_vm import wait_for
ROOT=Path(__file__).resolve().parents[3]
DEFAULT_CONFIG=Path.home()/'.config/dshmonitor-test-pack/linux.json'

class LinuxVM:
    def __init__(self,config):
        self.config=config;self.directory=Path(config['directory']);self.root=config.get('guest_root','/home/tester/dafeiyu-test/project')
    def running(self):
        try:
            command=Path('/proc/'+(self.directory/'vm.pid').read_text().strip()+'/cmdline').read_bytes()
            return b'qemu-system' in command and str(self.directory).encode() in command
        except OSError:return False
    def graphics(self):
        try:
            argv=Path('/proc/'+(self.directory/'vm.pid').read_text().strip()+'/cmdline').read_bytes().decode().split('\0')
            return {'display':[argv[i+1] for i,a in enumerate(argv[:-1]) if a=='-display'],
                    'devices':[argv[i+1] for i,a in enumerate(argv[:-1]) if a=='-device' and any(n in argv[i+1] for n in ('virtio-vga','virtio-gpu','qxl','VGA'))]}
        except OSError as error:return {'observation_error':str(error)}
    def hmp(self,command):
        import socket
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(8);connection.connect(str(self.directory/'monitor.sock'))
            data=b''
            while b'(qemu)' not in data:data+=connection.recv(8192)
            connection.sendall((command+'\n').encode())
            data=b''
            while b'(qemu)' not in data:data+=connection.recv(8192)
    def ssh(self,command,timeout=120,input=None):
        p=subprocess.run(['ssh','-i',self.config['key'],'-p',str(self.config['port']),'-o','BatchMode=yes','-o','StrictHostKeyChecking=accept-new','-o','UserKnownHostsFile='+str(self.directory/'known_hosts'),'-o','ConnectTimeout=4','tester@127.0.0.1',command],input=input,capture_output=True,timeout=timeout)
        if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace')[-2000:])
        return p.stdout.decode(errors='replace')
    def start_login(self):
        if not self.running():
            launcher=self.directory/'start.sh'
            if getattr(self,'human_review',False):
                source=launcher.read_text().replace('-audiodev none,id=audio0','-audiodev spice,id=audio0')
                launcher=self.directory/'start-review.sh';launcher.write_text(source);launcher.chmod(0o700)
            subprocess.run(['bash',str(launcher)],check=True,capture_output=True)
        wait_for(lambda:self.ssh('true',10) is not None,300)
        self.hmp('sendkey shift 80')  # Initial user input wakes a blanked VM display.
        if getattr(self,'human_review',False):
            from .vm_display import show_viewer
            show_viewer(self,'linux')
        return 'ssh_ready'
    def shutdown(self):
        if not self.running():return
        try:self.ssh('sudo poweroff',15)
        except (RuntimeError,subprocess.TimeoutExpired):pass
        wait_for(lambda:not self.running(),180)
        from .vm_display import close_viewer
        close_viewer(self)
    def reboot(self):
        previous=self.ssh('cat /proc/sys/kernel/random/boot_id').strip()
        try:self.ssh('sudo reboot',10)
        except (RuntimeError,subprocess.TimeoutExpired):pass
        wait_for(lambda:self.ssh('cat /proc/sys/kernel/random/boot_id',10).strip()!=previous,180)
        return self.ssh('cat /proc/sys/kernel/random/boot_id').strip()
    def deploy(self,out):
        archive=out/'linux-source.tar.gz';out.mkdir(parents=True,exist_ok=True)
        deleted=subprocess.check_output(['git','diff','HEAD','--no-renames','--diff-filter=D','--name-only','-z'],cwd=ROOT).decode().split('\0')
        paths=[self.root+'/'+name for name in deleted if name]
        if paths:self.ssh('rm -f -- '+' '.join(shlex.quote(path) for path in paths))
        names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
        with tarfile.open(archive,'w:gz') as tar:
            for name in dict.fromkeys(names):
                if name and (ROOT/name).is_file() and 'node_modules' not in Path(name).parts:tar.add(ROOT/name,arcname=name,recursive=False)
        self.ssh('mkdir -p '+shlex.quote(self.root)+' && tar xzf - -C '+shlex.quote(self.root),120,input=archive.read_bytes())
    def proxy_env(self):
        values=[]
        for name in ('HTTP_PROXY','HTTPS_PROXY'):
            value=os.environ.get(name) or os.environ.get(name.lower())
            if not value:continue
            url=urllib.parse.urlsplit(value)
            if url.hostname in ('127.0.0.1','localhost'):
                value=urllib.parse.urlunsplit(url._replace(netloc=url.netloc.replace(url.hostname,'10.0.2.2')))
            values.append(name+'='+shlex.quote(value));values.append(name.lower()+'='+shlex.quote(value))
        return ' '.join(values)
    def prepare(self):return self.ssh('cd '+shlex.quote(self.root)+' && env '+self.proxy_env()+' bash test-support/prepare_linux.sh',1800)



if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['start','shutdown','prepare']);a=p.parse_args()
    vm=LinuxVM(json.loads(DEFAULT_CONFIG.read_text()))
    if a.action=='start':print(vm.start_login())
    elif a.action=='shutdown':vm.shutdown()
    else:print(vm.prepare())
