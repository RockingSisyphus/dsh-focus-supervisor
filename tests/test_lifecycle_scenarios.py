"""Shared JSON timing contracts; actual OS reboot/input is tested separately."""
import json,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from focus_demo.supervisor import Supervisor
SPEC=json.loads((Path(__file__).resolve().parents[1]/'dshmonitor-test-pack/lifecycle-contracts.json').read_text())

@pytest.mark.parametrize('case',SPEC['scenarios'],ids=lambda c:c['id'])
def test_lifecycle(case,tmp_path):
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None),interval=10,test_mode=True)
    now=time.time()
    task=core.plan(dict(task_id='t',task_prompt='检查实际进展',project_dir=str(tmp_path),agreement='阅读论文',start_at=now+60,end_at=now+180,allow_early_finish=True),'chat')
    task.update(start_at=now+case['start'],end_at=now+case['end'])
    core.store.save('task',task)
    try:
        if case.get('restore'):core.restored_tasks.add('t')
        if 'no_input_heartbeats' in case:core.presence={'available':True,'last_input_at':now-100,'idle_seconds':100}
        core.tick(now)
        if 'no_input_heartbeats' not in case:
            assert core.store.get('task','t')['status']==case['expected_status']
            notices=core.store.all('notice')
            assert (notices[-1]['kind'] if notices else None)==case['notice']
            if case['id']=='scheduled-quiet':
                assert not core.needs_dsh() and not core.due()
                calls=[];core.sensor=SimpleNamespace(call=lambda op:calls.append(op))
                core.poll_presence();core.capture()
                assert calls==[]
            return
        # The plugin, not the model, decides absence: each scheduled heartbeat
        # with no new input advances the counter until the threshold is reached.
        assert core.store.get('task','t').get('no_input_reports',0)==0,'首次心跳只建立输入基线'
        for index in range(case['no_input_heartbeats']):
            task=core.store.get('task','t')
            for report in core.due():core.delivered(report['id'])
            core.tick(task['next_check']+1)
            task=core.store.get('task','t')
            assert task.get('standby',False)==(index==case['no_input_heartbeats']-1),(index,task.get('no_input_reports'))
        assert core.store.get('task','t')['no_input_reports']==case['no_input_heartbeats']
        assert not core.needs_dsh(),'待机后不再唤醒 DSH'
        assert not core.due(),'进入待机的那次心跳不投递给 AI'
        assert any(e['event']=='standby_entered' and e['body'].get('reason')=='no_input_heartbeats' for e in core.store.logs(50))
        core.tick(now+500)
        assert core.store.get('task','t')['status']=='not_completed'
        assert not core.live(), '离席也不能超过约定结束时间持续监督'
    finally:core.store.close()


def scheduled_core(tmp_path,presence,interval=10):
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None),interval=interval,test_mode=True)
    now=time.time()
    task=core.plan(dict(task_id='t',task_prompt='检查实际进展',project_dir=str(tmp_path),agreement='阅读论文',
        start_at=now-5,end_at=now+3600,allow_early_finish=True),'chat')
    core.presence=presence
    return core,task,now


def test_agent_presence_is_recorded_but_never_triggers_standby(tmp_path):
    presence={'available':True,'last_input_at':time.time()-60,'idle_seconds':60}
    core,task,now=scheduled_core(tmp_path,presence)
    try:
        for _ in range(5):
            report=core.make_report(core.store.get('task','t'))
            core.observe(dict(report_id=report['id'],decision='uncertain',presence='away',reason='模型认为离席'),'chat')
        task=core.store.get('task','t')
        assert task.get('agent_presence')=='away' and not task.get('standby',False)
        assert task.get('no_input_reports',0)==0,'手动报告不计入无输入心跳'
    finally:core.store.close()


def test_capture_gap_never_counts_as_absence(tmp_path):
    core,task,now=scheduled_core(tmp_path,{'available':False,'error':'no idle api'})
    try:
        core.tick(now)
        for _ in range(5):
            task=core.store.get('task','t')
            for report in core.due():core.delivered(report['id'])
            core.tick(task['next_check']+1)
        task=core.store.get('task','t')
        assert not task.get('standby',False) and task.get('no_input_reports',0)==0
        assert task.get('no_input_in_report') is None
    finally:core.store.close()


def test_away_heartbeats_setting_controls_the_threshold(tmp_path):
    presence={'available':True,'last_input_at':time.time()-60,'idle_seconds':60}
    core,task,now=scheduled_core(tmp_path,presence)
    try:
        core.configure({'patch':{'away_heartbeats':2}},'ai','chat')
        core.tick(now)
        for index in range(2):
            task=core.store.get('task','t')
            for report in core.due():core.delivered(report['id'])
            core.tick(task['next_check']+1)
        task=core.store.get('task','t')
        assert task['standby'] and task['no_input_reports']==2
    finally:core.store.close()


def test_input_between_heartbeats_resets_the_counter(tmp_path):
    presence={'available':True,'last_input_at':time.time()-60,'idle_seconds':60}
    core,task,now=scheduled_core(tmp_path,presence)
    try:
        core.tick(now)
        for index in range(2):
            task=core.store.get('task','t')
            for report in core.due():core.delivered(report['id'])
            core.tick(task['next_check']+1)
        assert core.store.get('task','t')['no_input_reports']==2
        presence['last_input_at']=time.time();presence['idle_seconds']=0
        task=core.store.get('task','t')
        for report in core.due():core.delivered(report['id'])
        core.tick(task['next_check']+1)
        assert core.store.get('task','t')['no_input_reports']==0
    finally:core.store.close()


def test_report_carries_structured_input_activity(tmp_path):
    presence={'available':True,'last_input_at':time.time()-60,'idle_seconds':60}
    core,task,now=scheduled_core(tmp_path,presence)
    try:
        core.tick(now)
        for report in core.due():core.delivered(report['id'])
        task=core.store.get('task','t')
        core.tick(task['next_check']+1)
        report=[r for r in core.store.all('report') if r['phase']=='monitor'][-1]
        activity=report['input_activity']
        assert activity['no_input_in_report'] is True
        assert activity['consecutive_no_input_heartbeats']==1
        assert activity['heartbeats_until_standby']==2
        assert activity['available'] is True and activity['idle_seconds']==60
    finally:core.store.close()
