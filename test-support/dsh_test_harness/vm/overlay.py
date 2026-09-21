"""Disposable Linux installation guest backed by a powered-off clean baseline."""
import json,re,shutil,subprocess,tempfile,secrets
from pathlib import Path
from .linux_vm import LinuxVM

class LinuxOverlay:
    def __init__(self,baseline,diagnostic_out=None):
        self.baseline=Path(baseline).expanduser().resolve();self.vm=None;self.directory=None
    def __enter__(self):
        base=self.baseline
        config={'directory':str(base),'key':str(base/'id_ed25519'),'port':22244}
        if LinuxVM(config).running():raise RuntimeError('Installation baseline is running; its disk cannot be used as a stable backing image')
        self.directory=Path(tempfile.mkdtemp(prefix='dsh-install-',dir=base.parent))
        try:
            subprocess.run(['qemu-img','create','-f','qcow2','-F','qcow2','-b',str(base/'ubuntu.qcow2'),str(self.directory/'ubuntu.qcow2')],check=True,capture_output=True)
            (self.directory/'seed.iso').symlink_to(base/'seed.iso')
            source=(base/'start.sh').read_text().replace(str(base),str(self.directory))
            source=re.sub(r'hostfwd=tcp:127\.0\.0\.1:\d+-:22','hostfwd=tcp:127.0.0.1:22244-:22',source)
            source=re.sub(r'-vnc 127\.0\.0\.1:\d+','-vnc 127.0.0.1:44',source)
            (self.directory/'start.sh').write_text(source)
            config.update(directory=str(self.directory),installation_environment='clean-overlay',baseline=str(base))
            self.vm=LinuxVM(config);self.vm.start_login()
            # Observe the actual baseline before any product installation.
            self.vm.ssh("test ! -e /opt/dafeiyu && test ! -e /etc/dafeiyu/config.json && test ! -e /etc/systemd/system/dafeiyu-supervisor.service",20)
            # An installed profile is a baseline defect, not something to erase.
            self.vm.ssh("test ! -d ~/.dsh/profiles && test ! -d ~/.local/share/gnome-shell/extensions/focus-demo@local.demo && test ! -d ~/.local/share/gnome-shell/extensions/tabfocus-demo@local.demo",20)
            password=secrets.token_hex(12)
            self.vm.ssh('sudo chpasswd',input=('tester:'+password+'\n').encode())
            config['admin_password']=password
            return config
        except Exception:
            self.__exit__(None,None,None);raise
    def __exit__(self,*args):
        if self.vm:self.vm.shutdown()
        if self.directory:shutil.rmtree(self.directory)


class WindowsOverlay:
    """Discardable layer of the newly provisioned Windows baseline, never the daily VM."""
    def __init__(self,baseline,diagnostic_out=None):
        self.diagnostic_out=diagnostic_out
        self.config=json.loads(Path(baseline).expanduser().read_text())
        self.base=Path(self.config['directory']);self.vm=None;self.directory=None
    def __enter__(self):
        from .windows_vm import WindowsVM
        if WindowsVM(self.config).running():raise RuntimeError('Installation baseline is running; shut down its guest before making a disk layer')
        self.directory=Path(tempfile.mkdtemp(prefix='dsh-install-windows-',dir=self.base.parent))
        try:
            subprocess.run(['qemu-img','create','-f','qcow2','-F','qcow2','-b',str(self.base/'disk.qcow2'),str(self.directory/'disk.qcow2')],check=True,capture_output=True)
            for path in [self.base/'OVMF_VARS.fd',*self.base.glob('tpm2-*')]:
                if path.is_file():shutil.copyfile(path,self.directory/path.name)
            source=(self.base/'windows-11.sh').read_text().replace(str(self.base),str(self.directory))
            source=re.sub(r'hostfwd=tcp:127\.0\.0\.1:\d+-:22','hostfwd=tcp:127.0.0.1:22250-:22',source)
            (self.directory/'windows-11.sh').write_text(source)
            config={**self.config,'directory':str(self.directory),'installation_environment':'clean-overlay','baseline':str(self.base)}
            self.vm=WindowsVM(config);self.vm.diagnostic_out=self.diagnostic_out;self.vm.start_login()
            state=self.vm.powershell(r"$paths=@(Join-Path $env:ProgramData 'Dafeiyu'); $paths+=@(Get-ChildItem 'C:\Users' -Directory | ForEach-Object {Join-Path $_.FullName '.dsh\profiles'}); $found=@($paths | Where-Object {Test-Path $_}); $tasks=@(Get-ScheduledTask -TaskName 'Dafeiyu-*' -ErrorAction SilentlyContinue); if($found.Count -or $tasks.Count){throw 'Baseline contains the product'}; 'absent'")
            return config
        except Exception:
            self.__exit__(None,None,None);raise
    def __exit__(self,*args):
        if self.vm:self.vm.shutdown()
        if self.directory:shutil.rmtree(self.directory)
