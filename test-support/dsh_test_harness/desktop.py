"""OS-specific process/display setup used by any test pack."""
import os,sys,subprocess,secrets,time,signal,tempfile,shutil
from pathlib import Path
from contextlib import ExitStack

class Desktop:
    windows=sys.platform=='win32'
    def __init__(self):self.bus_pid=None;self.runtime=None;self.original_settings=[];self.resources=ExitStack();self.display_configuration=None
    def setup(self,out,start,visible=False,settings=None,size=None):
        if self.windows:
            (out/'desktop-environment.json').write_text('{"backend":"windows","installation_environment":"existing-system"}')
            return
        result=subprocess.run(['systemctl','--user','show-environment'],capture_output=True,text=True,check=True)
        for row in result.stdout.splitlines():
            key,_,value=row.partition('=')
            if key in {'DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','XDG_RUNTIME_DIR','DBUS_SESSION_BUS_ADDRESS','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP'}:os.environ[key]=value
        import json
        for setting in settings or []:
            target=[setting['schema'],setting['key']]
            previous=subprocess.check_output(['gsettings','get',*target],text=True).strip()
            self.original_settings.append((target,previous))
            subprocess.run(['gsettings','set',*target,json.dumps(setting['value'])],check=True)
        if size:
            import json
            response=self.set_display({'size':size})
            self.display_configuration=response['previous']
            (out/'display-mode.json').write_text(json.dumps(response),encoding='utf-8')
        os.environ['GDK_BACKEND']='wayland';os.environ['QT_QPA_PLATFORM']='wayland'
        if os.environ.get('XDG_SESSION_TYPE')!='wayland':raise RuntimeError('Desktop session is not Wayland')
        from .desktop_driver_session import driver_session
        self.resources.enter_context(driver_session())
        from .gnome import call
        import json
        from .wait import until
        def ready():
            try:return call('snapshot')
            except RuntimeError as error:
                if 'ServiceUnknown' in str(error):return None
                raise
        actual=until(ready,30)
        actual['test_settings']=[{'schema':target[0],'key':target[1],'before':before,'actual':subprocess.check_output(['gsettings','get',*target],text=True).strip()} for target,before in self.original_settings]
        (out/'desktop-environment.json').write_text(json.dumps(actual,ensure_ascii=False),encoding='utf-8')
    def set_display(self,request):
        import json
        result=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('display_mode.py'))],input=json.dumps(request),text=True,capture_output=True,check=True,timeout=20)
        return json.loads(result.stdout)
    def close(self):
        try:
            for target,before in reversed(self.original_settings):subprocess.run(['gsettings','set',*target,before],check=True)
            self.original_settings.clear()
        finally:
            try:
                if self.display_configuration:self.set_display({'restore':self.display_configuration})
            finally:self.resources.close()
    def link_modules(self,source,target):
        if self.windows:subprocess.run(['cmd','/c','mklink','/J',str(target),str(source)],check=True,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        else:target.symlink_to(source,target_is_directory=True)
    def stop_process(self,p):
        if p.poll() is not None:return
        import psutil
        try:children=psutil.Process(p.pid).children(recursive=True)
        except psutil.NoSuchProcess:children=[]
        if self.windows:
            subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            p.wait(timeout=10)
        else:
            os.killpg(p.pid,signal.SIGTERM)
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        # Chrome's profile writers can outlive its launcher. Wait for the owned
        # descendants before deleting their profile, then end any remaining ones.
        _,alive=psutil.wait_procs(children,timeout=3)
        for child in alive:
            try:child.kill()
            except psutil.NoSuchProcess:pass
        _,alive=psutil.wait_procs(alive,timeout=3)
        remaining=[]
        for child in alive:
            try:
                if child.status()!=psutil.STATUS_ZOMBIE:remaining.append(child.pid)
            except psutil.NoSuchProcess:pass
        if remaining:raise RuntimeError('Test process descendants remain: '+str(remaining))
    def browser_options(self,visible,env):
        if self.windows:return {'channel':'msedge','headless':False,'env':env}
        executable=shutil.which('google-chrome') or shutil.which('google-chrome-stable')
        if not executable:raise FileNotFoundError('Google Chrome is not installed in the test guest')
        return {'headless':False,'executable_path':executable,'env':env}
    def browser_executable(self):
        if not self.windows:
            executable=shutil.which('google-chrome') or shutil.which('google-chrome-stable')
            if executable:return executable
            raise FileNotFoundError('Google Chrome is not installed in the test guest')
        import psutil
        for process in psutil.process_iter(['name']):
            if (process.info['name'] or '').lower()=='msedge.exe':
                try:return process.exe()
                except (psutil.AccessDenied,psutil.NoSuchProcess):continue
        raise FileNotFoundError('Microsoft Edge is not running in the test guest')
    def browser_arguments(self,executable,profile):
        args=[str(executable),'--user-data-dir='+str(profile),'--no-first-run',
              '--no-default-browser-check','--disable-sync','--password-store=basic','--lang=en-US','--accept-lang=en-US']
        if not self.windows:args.append('--ozone-platform=wayland')
        return args

    def python(self):return sys.executable if self.windows else '/usr/bin/python3'

    def activate(self,window):
        if not self.windows:
            from .gnome import action
            return bool(action('activate',window))
        import win32gui,win32con,pywintypes
        from .wait import until
        handle=int(window.get('native_id') or window['id'].split(':')[-1])
        def active():
            foreground=win32gui.GetForegroundWindow()
            try:return foreground==handle or bool(foreground and win32gui.GetAncestor(foreground,win32con.GA_ROOTOWNER)==handle)
            except pywintypes.error as error:
                if error.winerror!=1400:raise
                return False  # The foreground window disappeared between the two API reads.
        if active():return True
        from focus_demo.process_worker import run_worker
        source="""import sys
sys.coinit_flags=0
from comtypes.client import GetModule,CreateObject
api=GetModule('UIAutomationCore.dll')
client=CreateObject(api.CUIAutomation,interface=api.IUIAutomation)
import win32gui
handle=int(sys.argv[1]);element=client.ElementFromHandle(handle)
if win32gui.IsIconic(handle):
    element.GetCurrentPattern(10009).QueryInterface(api.IUIAutomationWindowPattern).SetWindowVisualState(0)
element.SetFocus()
"""
        run_worker([sys.executable,'-c',source,str(handle)],timeout=10,check=True)
        try:until(active,10)
        except TimeoutError as error:
            raise TimeoutError(f'Window activation failed for HWND {handle}; foreground={win32gui.GetForegroundWindow()}') from error
        return True
