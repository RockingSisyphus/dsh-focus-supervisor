"""Civil-time rules and the existing task lifecycle working together."""
from datetime import datetime
from types import SimpleNamespace
import time

import pytest

from focus_demo import recurrence
from focus_demo.supervisor import Supervisor


def at(value):
    return datetime.fromisoformat(value).timestamp()


def request(root, start, end, **extra):
    return {'task_id': extra.pop('task_id', 'task_one'), 'agreement': '写作',
            'task_prompt': '核对草稿', 'project_dir': str(root),
            'start_at': start, 'end_at': end, 'allow_early_finish': True,
             **extra}


def test_civil_days_weekdays_and_dst():
    shanghai='Asia/Shanghai'
    daily=recurrence.schedule({'start_at':at('2026-09-23T23:00:00+08:00'),
                               'end_at':at('2026-09-24T01:00:00+08:00')},
                              {'frequency':'daily','count':5},shanghai)
    assert recurrence.occurrence(daily,4)['date']=='2026-09-27'
    assert recurrence.occurrence(daily,4)['end_at']-recurrence.occurrence(daily,4)['start_at']==7200
    assert recurrence.occurrence(daily,5) is None
    weekly=recurrence.schedule({'start_at':at('2026-09-23T09:00:00+08:00'),
                                'end_at':at('2026-09-23T10:00:00+08:00')},
                               {'frequency':'weekly','weekdays':[3,7],'until':'2026-09-27'},shanghai)
    assert [recurrence.occurrence(weekly,n)['date'] for n in range(2)]==['2026-09-23','2026-09-27']
    assert recurrence.occurrence(weekly,2) is None
    ny='America/New_York'
    spring=recurrence.schedule({'start_at':at('2026-03-07T02:30:00-05:00'),
                                'end_at':at('2026-03-07T03:30:00-05:00')},{'frequency':'daily','count':3},ny)
    assert datetime.fromtimestamp(recurrence.occurrence(spring,1)['start_at'],recurrence.ZoneInfo(ny)).strftime('%H:%M')=='03:00'
    fall=recurrence.schedule({'start_at':at('2026-10-31T01:30:00-04:00'),
                              'end_at':at('2026-10-31T02:30:00-04:00')},{'frequency':'daily','count':3},ny)
    assert datetime.fromtimestamp(recurrence.occurrence(fall,1)['start_at'],recurrence.ZoneInfo(ny)).fold==0


def test_full_range_conflicts_and_touching_edges():
    one=recurrence.schedule({'start_at':at('2026-09-23T09:00:00+08:00'),
                             'end_at':at('2026-09-23T10:00:00+08:00')},{'frequency':'weekly','weekdays':[3],'count':10},'Asia/Shanghai')
    late={'start_at':at('2026-10-07T09:30:00+08:00'),'end_at':at('2026-10-07T10:00:00+08:00')}
    adjacent={'start_at':at('2026-10-07T10:00:00+08:00'),'end_at':at('2026-10-07T11:00:00+08:00')}
    assert recurrence.conflict(one,late)
    assert recurrence.conflict(one,adjacent) is None
    two=recurrence.schedule({'start_at':at('2026-09-25T09:30:00+08:00'),
                             'end_at':at('2026-09-25T10:30:00+08:00')},{'frequency':'weekly','weekdays':[3,5]},'Asia/Shanghai')
    assert recurrence.conflict(one,two)
    with pytest.raises(ValueError,match='相邻循环'):
        recurrence.schedule({'start_at':at('2026-09-23T23:00:00+08:00'),
                             'end_at':at('2026-09-25T01:00:00+08:00')},{'frequency':'daily'},'Asia/Shanghai')
    # Wednesday-to-Sunday is wide enough; Sunday-to-Wednesday is not.
    long_weekend={'start_at':at('2026-09-23T09:00:00+08:00'),
                  'end_at':at('2026-09-26T21:00:00+08:00')}
    recurrence.schedule(long_weekend,{'frequency':'weekly','weekdays':[3,7],'count':2},'Asia/Shanghai')
    with pytest.raises(ValueError,match='相邻循环'):
        recurrence.schedule(long_weekend,{'frequency':'weekly','weekdays':[3,7],'count':3},'Asia/Shanghai')


def test_occurrence_advance_restart_and_scope(tmp_path, monkeypatch):
    clock=[at('2026-09-23T08:00:00+08:00')]
    monkeypatch.setattr(time,'time',lambda:clock[0])
    lifecycle=SimpleNamespace(enable=lambda:None)
    core=Supervisor(tmp_path,lifecycle)
    try:
        first=core.plan(request(tmp_path,at('2026-09-23T09:00:00+08:00'),at('2026-09-23T10:00:00+08:00'),
                                repeat={'frequency':'daily','count':3}), 'chat')
        series_id=first['series_id']
        assert len(core.live())==1 and len(core.live_series())==1
        clock[0]=at('2026-09-23T09:30:00+08:00');core.tick()
        assert core.store.get('task',first['id'])['status']=='active'
        clock[0]=at('2026-09-23T10:01:00+08:00');core.tick()
        assert core.store.get('task',first['id'])['status']=='not_completed'
        second=core.live()[0]
        assert second['occurrence_index']==1 and second['id']!=first['id']
        assert core.store.get('series',series_id)['consumed']==1
        legacy_series=core.store.get('series',series_id)
        legacy_series['template']['deadline_policy']='continue'
        core.store.save('series',legacy_series)
        second['deadline_policy']='discuss'
        core.store.save('task',second)
        core.store.close()
        core=Supervisor(tmp_path,lifecycle)
        assert core.live()[0]['id']==second['id'] and len(core.live())==1
        assert 'deadline_policy' not in core.live()[0]
        assert 'deadline_policy' not in core.store.get('series',series_id)['template']
        core.finish({'series_id':series_id,'scope':'current_only','verdict':'cancelled','reason':'本轮取消'},'chat')
        assert core.live()[0]['occurrence_index']==2
        assert 'deadline_policy' not in core.live()[0]
        core.finish({'series_id':series_id,'scope':'entire_series','verdict':'cancelled','reason':'取消以后'},'chat')
        assert not core.live() and not core.live_series()
    finally: core.store.close()


def test_strict_tasks_and_legacy_migration(tmp_path):
    now=time.time()
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None))
    normal=core.plan(request(tmp_path,now+100,now+150),'chat')
    strict=core.plan(request(tmp_path,now+200,now+250,task_id='strict',strictness='strict'),'chat')
    assert core.settings()['ui_locked']
    with pytest.raises(ValueError,match='严苛'):core.finish_ui({'task_id':strict['id']})
    assert core.finish_ui({'task_id':normal['id']})['status']=='cancelled'
    core.configure({'patch':{'strict_heartbeat_prompt':'严格检查，但接受正当理由'}},'ai','chat')
    assert core.settings()['strict_heartbeat_prompt'].startswith('严格检查')
    core.store.close()

    legacy=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None))
    old=legacy.store.get('task',strict['id']);old.pop('strictness');legacy.store.save('task',old)
    legacy.store.save('settings',{'id':'global','protect_task_changes':True,'heartbeat_prompt':'我的自定义心跳'})
    legacy.store.close()
    migrated=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None))
    try:
        assert migrated.store.get('task',strict['id'])['strictness']=='strict'
        assert migrated.settings()['ui_locked']
        assert migrated.settings()['heartbeat_prompt']=='我的自定义心跳'
        assert 'protect_task_changes' not in migrated.settings()
    finally:migrated.store.close()


def test_missed_count_is_bounded_and_revision_checks_next_round(tmp_path, monkeypatch):
    clock=[at('2026-09-23T08:00:00+08:00')]
    monkeypatch.setattr(time,'time',lambda:clock[0])
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None))
    try:
        first=core.plan(request(tmp_path,at('2026-09-23T09:00:00+08:00'),at('2026-09-23T10:00:00+08:00'),
                                repeat={'frequency':'daily','count':5}), 'chat')
        series=core.store.get('series',first['series_id'])
        change={**request(tmp_path,at('2026-09-23T09:00:00+08:00'),at('2026-09-24T09:30:00+08:00')),
                'scope':'current_only','reason':'想把当前轮延长到下一轮'}
        with pytest.raises(ValueError,match='首次重叠'):core.revise(change,'chat')
        assert core.store.get('task',first['id'])['revision']==1
        clock[0]=at('2026-10-10T12:00:00+08:00')
        core.tick()
        ended=core.store.get('series',series['id'])
        assert ended['status']=='completed' and ended['consumed']==5 and ended['missed']==5
        assert not core.live()
    finally:core.store.close()


def test_ai_can_change_strictness_without_another_permission_gate(tmp_path):
    now=time.time()
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None))
    try:
        task=core.plan(request(tmp_path,now+100,now+200,strictness='strict'),'chat')
        assert core.settings()['ui_locked']
        revised=core.revise({**request(tmp_path,now+100,now+200,strictness='normal'),
                             'task_id':task['id'],'reason':'用户与监工商定降低严苛度'},'chat')
        assert revised['strictness']=='normal' and not core.settings()['ui_locked']
        assert core.finish_ui({'task_id':task['id']})['status']=='cancelled'
    finally:core.store.close()


def test_restart_relinks_a_saved_occurrence_after_interrupted_series_write(tmp_path, monkeypatch):
    clock=[at('2026-09-23T08:00:00+08:00')]
    monkeypatch.setattr(time,'time',lambda:clock[0])
    lifecycle=SimpleNamespace(enable=lambda:None)
    core=Supervisor(tmp_path,lifecycle)
    first=core.plan(request(tmp_path,at('2026-09-23T09:00:00+08:00'),at('2026-09-23T10:00:00+08:00'),
                            repeat={'frequency':'daily','count':3}),'chat')
    series=core.store.get('series',first['series_id'])
    series['current_task_id']=None
    core.store.save('series',series)
    core.store.close()
    clock[0]=at('2026-09-24T08:00:00+08:00')
    restarted=Supervisor(tmp_path,lifecycle)
    try:
        assert restarted.store.get('series',series['id'])['current_task_id']==first['id']
        assert len(restarted.live())==1
        restarted.tick()
        live=restarted.live()
        assert len(live)==1 and live[0]['occurrence_index']==1
        assert restarted.store.get('task',first['id'])['status']=='invalidated'
    finally:restarted.store.close()


def test_restart_does_not_resurrect_a_cancelled_series_occurrence(tmp_path, monkeypatch):
    clock=[at('2026-09-23T08:00:00+08:00')]
    monkeypatch.setattr(time,'time',lambda:clock[0])
    lifecycle=SimpleNamespace(enable=lambda:None)
    core=Supervisor(tmp_path,lifecycle)
    first=core.plan(request(tmp_path,at('2026-09-23T09:00:00+08:00'),at('2026-09-23T10:00:00+08:00'),
                            repeat={'frequency':'daily','count':3}),'chat')
    series=core.store.get('series',first['series_id'])
    series['status']='cancelled'
    core.store.save('series',series)
    core.store.close()

    restarted=Supervisor(tmp_path,lifecycle)
    try:
        assert not restarted.live()
        assert restarted.store.get('task',first['id'])['status']=='cancelled'
        assert not restarted.live_series()
    finally:restarted.store.close()


def test_current_only_time_override_is_used_by_new_conflict_checks(tmp_path, monkeypatch):
    clock=[at('2026-09-23T08:00:00+08:00')]
    monkeypatch.setattr(time,'time',lambda:clock[0])
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None))
    try:
        first=core.plan(request(tmp_path,at('2026-09-23T09:00:00+08:00'),at('2026-09-23T10:00:00+08:00'),
                                repeat={'frequency':'daily','count':3}),'chat')
        core.revise(request(tmp_path,first['start_at'],at('2026-09-23T10:30:00+08:00'),
                            task_id=first['id'],scope='current_only',reason='本轮延长'),'chat')
        with pytest.raises(ValueError,match='时间冲突'):
            core.plan(request(tmp_path,at('2026-09-23T10:15:00+08:00'),at('2026-09-23T10:45:00+08:00'),
                              task_id='blocked'),'chat')
        core.revise(request(tmp_path,first['start_at'],at('2026-09-23T09:15:00+08:00'),
                            task_id=first['id'],scope='current_only',reason='本轮缩短'),'chat')
        free=core.plan(request(tmp_path,at('2026-09-23T09:30:00+08:00'),at('2026-09-23T10:00:00+08:00'),
                               task_id='free_slot'),'chat')
        assert free['id']=='free_slot'
    finally:core.store.close()
