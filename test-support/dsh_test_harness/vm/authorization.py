"""Accept the real system authorization dialog using physical VM input."""
def accept_windows(vm,out,accept=True):
    import subprocess
    from PIL import Image
    from .windows_vm import wait_for
    screenshot=vm.directory/'authorization-current.ppm'
    def visible():
        vm.hmp('screendump '+str(screenshot))
        result=subprocess.run(['tesseract',str(screenshot),'stdout','-l','eng+chi_sim','--psm','11'],capture_output=True,text=True,timeout=15)
        if result.returncode:raise RuntimeError('Cannot read real authorization dialog')
        Image.open(screenshot).save(out/'authorization-last.png')
        (out/'authorization-observation.txt').write_text(result.stdout,encoding='utf-8')
        text=result.stdout.lower().replace(' ','').replace('\n','')
        return ('用户账户控制' in text or '用户帐户控制' in text or 'useraccountcontrol' in text) and ('powershell' in text)
    wait_for(visible,90)
    Image.open(screenshot).save(out/('authorization.png' if accept else 'authorization-denied.png'))
    vm.hmp('sendkey '+('alt-y' if accept else 'alt-n'))
    return {'dialog':'Windows UAC','application':'PowerShell','physical_input':'Alt+Y' if accept else 'Alt+N','accepted':accept}
