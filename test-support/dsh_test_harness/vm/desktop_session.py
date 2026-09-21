"""Real guest lock/unlock operations; credentials remain in private VM config."""
import time
from .windows_vm import wait_for


def linux_session(vm):
    import shlex,json
    # After logout Display may point to this SSH session. Inspect it within the
    # same connection: a second SSH call sees an already-ended temporary ID.
    source="""import subprocess,json
identifier=subprocess.check_output(['loginctl','show-user','tester','-p','Display','--value'],text=True).strip()
rows=subprocess.check_output(['loginctl','show-session',identifier,'-p','State','-p','Type','-p','Class','-p','Active'],text=True).splitlines() if identifier else []
properties=dict(row.split('=',1) for row in rows if '=' in row)
print(json.dumps({'id':identifier if properties.get('Type')=='wayland' else None,'observed_session':identifier,**properties}))
"""
    return json.loads(vm.ssh('python3 -c '+shlex.quote(source)))


def locked(vm,platform):
    if platform=='windows':
        return vm.powershell("if(Get-Process LogonUI -ErrorAction SilentlyContinue){'locked'}else{'unlocked'}").strip()=='locked'
    return vm.ssh("loginctl show-session $(loginctl show-user tester -p Display --value) -p LockedHint --value").strip()=='yes'


def lock(vm,platform):
    if platform=='windows':
        vm.task("import ctypes\nif not ctypes.windll.user32.LockWorkStation():raise ctypes.WinError()\n",elevated=False)
    else:vm.ssh('loginctl lock-session $(loginctl show-user tester -p Display --value)')
    wait_for(lambda:locked(vm,platform),30)
    if platform=='windows':vm.cleanup_task()
    return {'locked':True,'at':time.time()}


def unlock(vm,platform):
    if not locked(vm,platform):return {'locked':False,'at':time.time(),'already_unlocked':True}
    if platform=='windows':vm.start_login()
    else:
        secret=vm.config['admin_password']
        # Disposable installer guests use an ASCII hex password. Send it through
        # the same physical keyboard channel as the other VM UI interactions.
        vm.hmp('sendkey ret 80');time.sleep(1)
        for character in secret:
            vm.hmp('sendkey '+character+' 80');time.sleep(.04)
        vm.hmp('sendkey ret 80')
    wait_for(lambda:not locked(vm,platform),45)
    return {'locked':False,'at':time.time()}


def logout(vm,platform):
    if platform=='windows':
        vm.task("import subprocess\nsubprocess.run(['shutdown.exe','/l'],check=True)\n",elevated=False)
        wait_for(lambda:vm.powershell("if(!(Get-Process explorer -ErrorAction SilentlyContinue)){'logged_out'}").strip()=='logged_out',45)
        vm.cleanup_task()
    else:
        before=linux_session(vm)
        vm.ssh('loginctl terminate-session '+before['id'])
        observations=[]
        def changed():
            try:state=linux_session(vm)
            except RuntimeError as error:state={'id':before['id'],'error':str(error)}
            observations.append({'at':time.time(),**state})
            if getattr(vm,'diagnostic_out',None):
                import json
                (vm.diagnostic_out/'logout-observations.json').write_text(json.dumps({'before':before,'observations':observations},indent=2),encoding='utf-8')
            return state if state['id']!=before['id'] else None
        after=wait_for(changed,45)
        return {'logged_out':True,'at':time.time(),'before':before,'after':after}
    return {'logged_out':True,'at':time.time()}


def login(vm,platform):
    if platform=='windows':
        vm.start_login()
        return {'logged_in':True,'at':time.time()}
    import subprocess
    submitted=False;selected=False
    def attempt():
        nonlocal submitted,selected
        session=linux_session(vm)
        if session.get('Type')=='wayland' and session.get('State')=='active':return session
        path=vm.directory/'login-current.ppm'
        vm.hmp('screendump '+str(path));path.chmod(0o600)
        text=subprocess.run(['tesseract',str(path),'stdout','-l','eng','--psm','11'],capture_output=True,text=True,timeout=15,check=True).stdout.lower()
        if 'sorry' in text or 'incorrect' in text:raise RuntimeError('GNOME rejected the login credential')
        if 'password' in text and not submitted:
            vm.hmp('sendkey ctrl-a 80')
            for character in vm.config['admin_password']:
                vm.hmp('sendkey '+character+' 80');time.sleep(.04)
            vm.hmp('sendkey ret 80');submitted=True
        elif 'tester' in text and not selected:
            vm.hmp('sendkey ret 80');selected=True
        return False
    session=wait_for(attempt,90)
    return {'logged_in':True,'at':time.time(),'method':'GDM physical keyboard','session':session}
