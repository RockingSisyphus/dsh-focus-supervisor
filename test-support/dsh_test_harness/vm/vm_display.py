"""Explicit test-only VM viewers. Normal test boots have no viewer or audio sink."""
import shutil
import subprocess
from pathlib import Path


def start_windows(vm):
    # Use Quickemu's already generated, known VM command without its desktop
    # launcher. Keep disks/TPM/network unchanged; audio goes to a null backend.
    script=vm.directory/'windows-11.sh'
    source=script.read_text().replace('2>/dev/null','')
    # The legacy EHCI tablet can stay suspended after a VNC wakeup on Windows.
    # Use QEMU's recommended controller instead of retrying lost mouse actions.
    source=source.replace('-device usb-ehci,id=input', '-device qemu-xhci,id=input')
    source=source.replace('-display none', '-display none -vnc unix:'+str(vm.directory/'dsh-test-vnc.sock'))
    if not getattr(vm,'human_review',False):source=source.replace('-audiodev spice,id=audio0','-audiodev none,id=audio0')
    generated=vm.directory/'start-test-headless.sh'
    generated.write_text(source);generated.chmod(0o700)
    log=(vm.directory/'test-launch.log').open('ab')
    launcher=subprocess.Popen(['bash',str(generated)],cwd=vm.directory,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    log.close()
    return launcher


def show_viewer(vm,platform):
    if getattr(vm,'viewer',None) and vm.viewer.poll() is None:return
    title='大肥鱼监工测试 · '+platform
    if shutil.which('remote-viewer'):
        uri=('spice+unix://'+str(vm.directory/'windows-11.sock')) if platform=='windows' else 'spice+unix://'+str(vm.directory/'spice.sock')
        argv=['remote-viewer','--title',title,uri]
    else:
        uri='spice+unix://'+str(vm.directory/('windows-11.sock' if platform=='windows' else 'spice.sock'))
        argv=['spicy','--uri='+uri,'--title',title]
    vm.viewer=subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def close_viewer(vm):
    viewer=getattr(vm,'viewer',None)
    if viewer and viewer.poll() is None:viewer.terminate();viewer.wait(timeout=10)
