"""VM transport failures and power ownership are separate from product results."""
import json
from types import SimpleNamespace
from pathlib import Path
from dsh_test_harness.vm import dispatch
import pytest

@pytest.mark.parametrize('already_running',[False,True])
def test_vm_shutdown_on_login_failure_preserves_original_power(tmp_path,monkeypatch,already_running):
    calls=[]
    class VM:
        def __init__(self,config):self.directory=tmp_path
        def running(self):return already_running
        def start_login(self):calls.append('login');raise RuntimeError('login unavailable')
        def shutdown(self):calls.append('shutdown')
    monkeypatch.setattr(dispatch,'WindowsVM',VM)
    monkeypatch.setattr(Path,'home',lambda:tmp_path)
    config=tmp_path/'.config/dshmonitor-test-pack';config.mkdir(parents=True)
    (config/'windows.json').write_text(json.dumps({'password':'PRIVATE_TEST_ONLY'}))
    args=SimpleNamespace(platform='windows',human_review=False)
    rows=dispatch.run(tmp_path,[(None,{'id':'actual','platforms':['windows'],'verification':'product'})],tmp_path/'out',args)
    assert calls==(['login'] if already_running else ['login','shutdown'])
    assert rows[0]['status']=='failed' and rows[0]['failure_stage']=='environment'
    assert 'PRIVATE_TEST_ONLY' not in json.dumps(rows)

@pytest.mark.parametrize('runner_crashed',[False,True])
def test_repeated_nested_runs_never_reuse_guest_completion(tmp_path,monkeypatch,runner_crashed):
    import ast,io,re,zipfile
    paths=[]
    case={'id':'chat','title':'Real chat','platforms':['windows'],'verification':'product','features':[]}
    class VM:
        root='C:\\Test'
        config={}
        def __init__(self,config):self.directory=tmp_path
        def running(self):return True
        def start_login(self):pass
        def deploy(self,out):pass
        def task(self,source,elevated=False):
            assert not elevated
            path=ast.literal_eval(re.search(r'out=Path\((.*?)\);',source).group(1))
            paths.append(path)
            assert "['chat']" in source
        def get(self,path):
            if path.endswith('.done'):return b'done'
            if path.endswith('.zip'):
                data=io.BytesIO()
                with zipfile.ZipFile(data,'w') as archive:
                    archive.writestr('summary.json',json.dumps({'cases':[{**case,'status':'not_run' if runner_crashed else 'passed'}]}))
                    archive.writestr('runner-exit.json',json.dumps({'returncode':1 if runner_crashed else 0}))
                return data.getvalue()
            raise RuntimeError('No input request')
        def python(self,source):return '[]'
        def powershell(self,source):return '{"tasks":[],"startup_error":null,"timeline":[]}'
        def cleanup_task(self):pass
    monkeypatch.setattr(dispatch,'WindowsVM',VM)
    monkeypatch.setattr(dispatch,'configuration',lambda *args:{})
    monkeypatch.setattr(dispatch,'wait_for',lambda fn,*args:fn())
    args=SimpleNamespace(platform='windows',human_review=False,prepare=False,workers=8,human_step_delay=0)
    for parent in ('run-one','run-two'):
        rows=dispatch.run(tmp_path,[(None,case)],tmp_path/parent/'after-reboot',args)
        assert rows[0]['status']==('not_run' if runner_crashed else 'passed')
        if runner_crashed:assert rows[1]['id']=='guest-runner' and rows[1]['failure_stage']=='environment'
    assert len(set(paths))==2


def test_dead_launcher_reports_failure_without_waiting_for_guest(tmp_path,monkeypatch):
    import subprocess
    from dsh_test_harness.vm import vm_display,windows_vm
    vm=windows_vm.WindowsVM({'directory':str(tmp_path)})
    monkeypatch.setattr(vm,'running',lambda:False)
    monkeypatch.setattr(vm_display,'start_windows',lambda _:SimpleNamespace(poll=lambda:1,returncode=1))
    def forbidden(*args):raise AssertionError('A dead launcher cannot connect to the guest')
    monkeypatch.setattr(windows_vm.guest,'call',forbidden)
    with pytest.raises(subprocess.CalledProcessError,match='test-launch.log'):vm.start_login()


def test_large_source_migration_does_not_expand_windows_command_line(tmp_path,monkeypatch):
    """Transport contract: many retired paths are data, never one huge command."""
    from dsh_test_harness.vm import windows_vm
    vm=windows_vm.WindowsVM({'directory':str(tmp_path),'guest_root':str(tmp_path/'guest')})
    names=[f'focus_demo/retired_{i:04d}.py' for i in range(1000)]
    retired=[Path(vm.root+'\\project\\'+name.replace('/','\\')) for name in names]
    Path(vm.root).mkdir()
    for path in retired:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('old source')
    retained=Path(vm.root+'\\project\\focus_demo\\supervisor.py');retained.write_text('current source')
    def git(argv,**kwargs):
        if argv[1]=='diff':
            assert '--no-renames' in argv
            return ('\0'.join(names)+'\0').encode()
        return b''
    monkeypatch.setattr(windows_vm.subprocess,'check_output',git)
    monkeypatch.setattr(vm,'put',lambda path,data:Path(path).write_bytes(data))
    commands=[]
    def execute(source):
        commands.append(source)
        exec(source,{})
    monkeypatch.setattr(vm,'python',execute)
    monkeypatch.setattr(vm,'powershell',lambda source,*args:commands.append(source))
    vm.deploy(tmp_path/'out')
    assert all(not path.exists() for path in retired)
    assert retained.read_text()=='current source'
    assert max(len(source.encode('utf-16le')) for source in commands)<32767
