"""Exact reviewed process identity is required even with elevated execution."""
import subprocess,sys
from focus_demo.actions import kill_verified_process
from focus_demo.platforms import process_info

def test_force_close_rejects_reused_identity_then_kills_only_target():
    target=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
    other=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
    try:
        assert not kill_verified_process(target.pid,'stale')['closed']
        assert target.poll() is None
        result=kill_verified_process(target.pid,process_info(target.pid)['identity'])
        assert result['closed'] and result['forced']
        assert other.poll() is None
    finally:
        for p in (target,other):
            if p.poll() is None:p.kill()
            p.wait()

def test_force_close_cannot_kill_supervisor():
    import os
    result=kill_verified_process(os.getpid(),process_info(os.getpid())['identity'])
    assert not result['closed']


def test_identity_survives_unreadable_elevated_executable(monkeypatch):
    import os,psutil
    expected=process_info(os.getpid())['identity']
    def denied(self):raise psutil.AccessDenied(self.pid)
    monkeypatch.setattr(psutil.Process,'exe',denied)
    info=process_info(os.getpid())
    assert info['identity']==expected and info['exe_unavailable']=='AccessDenied'


def test_linux_identity_uses_kernel_start_ticks_not_adjustable_wall_time(monkeypatch):
    import os,pytest,psutil
    if sys.platform!='linux':pytest.skip('Linux procfs lifecycle identity')
    pid=os.getpid();before=process_info(pid)
    real_create=psutil.Process.create_time
    # Reproduce the observed +1 second epoch conversion shift without changing
    # the VM clock; this process and its kernel start time are unchanged.
    monkeypatch.setattr(psutil.Process,'create_time',lambda self:real_create(self)+1)
    after=process_info(pid)
    assert after['created_at']==before['created_at']+1
    assert after['identity']==before['identity']
