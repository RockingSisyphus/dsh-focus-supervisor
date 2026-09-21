"""Each process receives its own HTTP result; input errors are not swallowed."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'test-support'))
from dsh_test_harness.vm.input import desktop_input,request


def test_concurrent_process_requests_keep_their_own_response(tmp_path):
    commands=[]
    vm=SimpleNamespace(hmp=commands.append)
    support=Path(__file__).resolve().parents[2]/'test-support'
    with desktop_input(vm) as url:
        env={**os.environ,'DSH_TEST_VM_INPUT_URL':url.replace('10.0.2.2','127.0.0.1'),'PYTHONPATH':str(support)}
        source="from dsh_test_harness.vm.input import request;import json,sys;print(json.dumps(request('keys',timeout=8,keys=sys.argv[1])))"
        workers=[subprocess.Popen([sys.executable,'-c',source,str(i)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for i in range(3)]
        try:
            for worker in workers:
                output,error=worker.communicate(timeout=10)
                assert worker.returncode==0,error
                assert json.loads(output)['sent']
            assert sorted(commands)==['sendkey 0','sendkey 1','sendkey 2']
        finally:
            for worker in workers:
                if worker.poll() is None:worker.kill()
                worker.wait()


def test_input_failure_reaches_the_guest(monkeypatch):
    def rejected(command):raise RuntimeError('Input device disconnected')
    with desktop_input(SimpleNamespace(hmp=rejected)) as url:
        monkeypatch.setenv('DSH_TEST_VM_INPUT_URL',url.replace('10.0.2.2','127.0.0.1'))
        with pytest.raises(RuntimeError,match='Input device disconnected'):request('keys',keys='f15')


def test_progress_is_pushed_without_opening_guest_files(tmp_path,monkeypatch):
    # No file-transfer API exists on this VM: the running guest owns its report.
    with desktop_input(SimpleNamespace(),tmp_path) as url:
        monkeypatch.setenv('DSH_TEST_VM_INPUT_URL',url.replace('10.0.2.2','127.0.0.1'))
        for passed in (0,1):
            summary={'counts':{'passed':passed,'not_run':1-passed},'cases':[]}
            request('progress',summary=summary)
            assert json.loads((tmp_path/'progress.json').read_text())==summary
