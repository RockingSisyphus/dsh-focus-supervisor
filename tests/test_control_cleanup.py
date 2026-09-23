"""Slow evidence cleanup must not own task control or delete a newer task's files."""
import threading,time
from types import SimpleNamespace
from focus_demo.supervisor import Supervisor
from focus_demo.control_lock import ControlLock


def plan(core,identifier):
    return core.plan(dict(task_id=identifier,task_prompt='test',project_dir=str(core.directory),agreement='test',start_at=time.time()-1,end_at=time.time()+90,allow_early_finish=True,deadline_policy='stop'),'chat')


def test_slow_cleanup_allows_new_task_status_and_action(tmp_path):
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def sensor(operation,payload=None):
        calls.append(operation)
        if operation=='cleanup_export' and not entered.is_set():
            entered.set();assert release.wait(3)
        return {'popup':True}
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None),SimpleNamespace(call=sensor))
    first=plan(core,'old')
    errors=[]
    def finish():
        try:core.finish(dict(task_id='old',verdict='cancelled',reason='test'),'chat')
        except Exception as e:errors.append(e)
    worker=threading.Thread(target=finish);worker.start()
    try:
        assert entered.wait(1)
        assert core.state()['live']==[]
        second=plan(core,'new')
        result=core.act(dict(task_id=second['id'],action='remind',message='test'),'chat')
        assert result['delivery']['popup']
        images=tmp_path/'screenshots';images.mkdir(exist_ok=True)
        (images/'new.png').write_bytes(b'new-task-evidence')
        release.set();worker.join(3)
        assert not errors and not worker.is_alive()
        assert (images/'new.png').exists()
        assert 'cleanup_capture' not in calls
        assert not core.store.get('task',first['id']).get('cleanup_pending')
    finally:
        release.set();worker.join(3);core.store.close()


def test_nested_control_cleanup_runs_after_outer_release():
    lock=ControlLock();done=[]
    with lock:
        with lock:lock.after_release(lambda:done.append('cleanup'))
        assert done==[]
    assert done==['cleanup']


def test_cleanup_failure_stays_pending_until_retry(tmp_path):
    failed=[True]
    def sensor(operation,payload=None):
        if operation=='cleanup_export' and failed[0]:raise OSError('storage unavailable')
        return {}
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None),SimpleNamespace(call=sensor))
    try:
        plan(core,'old')
        core.finish(dict(task_id='old',verdict='cancelled',reason='test'),'chat')
        task=core.store.get('task','old')
        assert task['cleanup_pending'] and not core.cleaning
        failed[0]=False
        with core.lock:core.cleanup_task(task)
        assert not core.store.get('task','old').get('cleanup_pending')
    finally:core.store.close()


def test_one_failed_cleanup_does_not_abandon_other_tasks():
    import pytest
    lock=ControlLock();done=[]
    def failure():raise OSError('storage unavailable')
    with pytest.raises(OSError):
        with lock:
            lock.after_release(failure)
            lock.after_release(lambda:done.append('second task cleaned'))
    assert done==['second task cleaned']


def test_slow_export_does_not_block_stop_state_or_actions(tmp_path):
    entered,release=threading.Event(),threading.Event()
    def sensor(operation,payload=None):
        if operation=='export':entered.set();assert release.wait(4)
        return {'popup':True}
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None),SimpleNamespace(call=sensor))
    core.presence={'available':True}
    task=plan(core,'old');report=core.make_report(task)
    exporting=threading.Thread(target=lambda:core.report_tool(dict(report_id=report['id'],operation='get_overview')))
    finishing=threading.Thread(target=lambda:core.finish(dict(task_id='old',verdict='cancelled',reason='test'),'chat'))
    exporting.start()
    try:
        assert entered.wait(1)
        assert core.act(dict(task_id='old',action='remind',message='test'),'chat')['delivery']['popup']
        finishing.start()
        deadline=time.monotonic()+1
        while core.state()['live'] and time.monotonic()<deadline:time.sleep(.01)
        assert not core.state()['live']
        assert core.capture_state()=='idle'
        assert finishing.is_alive() # Durable stop is visible before file cleanup finishes.
    finally:
        release.set();exporting.join(3);finishing.join(3)
        assert not exporting.is_alive() and not finishing.is_alive()
        assert not core.store.all('export')
        core.store.close()
