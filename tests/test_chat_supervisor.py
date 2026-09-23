"""Chat-native agreements; no model substitute is claimed as semantic AI validation."""
import time
from types import SimpleNamespace
import pytest
from focus_demo.supervisor import Supervisor

@pytest.fixture
def core(tmp_path):
    lifecycle=SimpleNamespace(enable=lambda:None)
    c=Supervisor(tmp_path,lifecycle,interval=10,test_mode=True)
    yield c
    c.store.close()

def plan(core,**kw):
    req=dict(task_id='t',task_prompt='请结合论文内容向我提问核实理解。',project_dir=str(core.directory),agreement='读完论文，讨论我真正理解的内容。',start_at=time.time()-5,end_at=time.time()+100,allow_early_finish=True,deadline_policy='discuss')
    req.update(kw)
    return core.plan(req,'chat')

def test_reading_needs_no_artifact(core):
    plan(core)
    r=core.finish(dict(task_id='t',verdict='completed',reason='经过内容讨论已确认理解'), 'chat')
    assert r['status']=='completed' and not core.live()

def test_plan_persists_and_idempotent(core):
    t=plan(core,start_at=time.time()+60)
    assert plan(core)['id']==t['id']
    other=Supervisor(core.directory,core.lifecycle)
    assert other.live()[0]['status']=='scheduled'
    other.store.close()

def test_other_chat_cannot_release(core):
    plan(core)
    with pytest.raises(ValueError,match='会话'):
        core.finish(dict(task_id='t',verdict='completed',reason=''), 'other')

def test_no_early_finish_waits_until_deadline(core):
    t=plan(core,allow_early_finish=False)
    result=core.finish(dict(task_id='t',verdict='completed',reason='确认完成'), 'chat')
    assert result['status']=='verified_waiting'
    core.tick(t['end_at']+1)
    assert not core.live() and core.store.get('task','t')['status']=='completed'

@pytest.mark.parametrize('policy',['stop','discuss','continue'])
def test_deadline_behavior(core,policy):
    t=plan(core,deadline_policy=policy)
    assert t['deadline_policy']=='stop'
    core.tick(t['end_at']+1)
    assert not core.live() and core.store.get('task','t')['status']=='not_completed'

def test_pending_delivery_not_duplicated_but_delivered_heartbeat_recurs(core):
    t=plan(core)
    core.tick(t['next_check']+1)
    r=core.due()[0]
    core.tick(t['next_check']+40)
    assert len(core.store.all('report'))==1
    core.delivered(r['id'])
    core.observe(dict(report_id=r['id'],decision='uncertain',reason='采集不可用'), 'chat')
    core.tick(time.time()+20)
    assert len(core.store.all('report'))==2

def test_revision_cancels_stale_checks(core):
    t=plan(core)
    r=core.make_report(t)
    req={k:t[k] for k in ['agreement','start_at','end_at','allow_early_finish','deadline_policy']}
    core.revise(dict(req,task_id='t',reason='讨论后延期',end_at=t['end_at']+100),'chat')
    with pytest.raises(ValueError,match='报告已结束'):
        core.observe(dict(report_id=r['id'],decision='on_task',reason=''), 'chat')

def test_first_suspicion_cannot_close(core):
    r=core.make_report(plan(core))
    with pytest.raises(ValueError,match='focus_act'):
        core.observe(dict(report_id=r['id'],decision='off_task',reason='游戏',close_window=True),'chat')
    core.observe(dict(report_id=r['id'],decision='suspect',reason='是在任务需要的资料吗？'),'chat')
    assert core.store.all('incident')[0]['state']=='awaiting_explanation'

def test_explanation_and_return_resolves_incident(core):
    t=plan(core);r=core.make_report(t)
    core.observe(dict(report_id=r['id'],decision='suspect',reason='解释用途'),'chat')
    r2=core.make_report(core.store.get('task','t'))
    core.observe(dict(report_id=r2['id'],decision='returned',reason='解释合理且已返回阅读'),'chat')
    assert core.store.get('task','t')['incident'] is None
    assert core.store.all('incident')[0]['state']=='resolved'

def test_test_patch_cannot_change_content_or_sent_report(core):
    r=core.make_report(plan(core))
    with pytest.raises(ValueError):core.patch_time(r['id'],{'title':'changed'})
    core.delivered(r['id'])
    with pytest.raises(ValueError):core.patch_time(r['id'],{})

def test_production_rejects_time_patch(core):
    core.test_mode=False
    r=core.make_report(plan(core))
    with pytest.raises(ValueError,match='测试模式'):core.patch_time(r['id'],{})

def test_recovery_never_claims_completed(core):
    plan(core);core.recover('模型持续不可用，管理员恢复')
    assert not core.live()
    assert core.store.get('task','t')['status']=='recovered_not_completed'

def test_preview_holds_real_report_until_time_edit_and_release(core):
    core.hold_reports=True
    t=plan(core)
    core.tick(t['next_check']+1)
    r=core.store.all('report')[0]
    assert r['status']=='preview' and core.due()==[]
    core.patch_time(r['id'],{'reason':'短时真实采集的测试预览'})
    core.tick(t['next_check']+40)
    assert len(core.store.all('report'))==1
    core.release_preview(r['id'])
    assert core.due()[0]['id']==r['id']

def test_shutdown_never_accepts_new_commitment(core):
    core.shutting_down=True
    with pytest.raises(ValueError,match='退出'):plan(core)
    assert not core.live()


def test_per_task_interval_and_restart(core):
    a=plan(core,check_interval_seconds=300,start_at=time.time()+60)
    b=plan(core,task_id='b',check_interval_seconds=900,start_at=a['end_at'],end_at=a['end_at']+100)
    assert a['next_check']==a['start_at']+300
    assert b['next_check']==b['start_at']+900
    other=Supervisor(core.directory,core.lifecycle)
    assert other.task_interval(other.store.get('task','t'))==300
    other.store.close()


def test_revision_keeps_or_changes_interval(core):
    t=plan(core,check_interval_seconds=120)
    req={k:t[k] for k in ['agreement','start_at','end_at','allow_early_finish','deadline_policy']}
    t=core.revise(dict(req,task_id='t',reason='延长时间'),'chat')
    assert t['check_interval_seconds']==120
    t=core.revise(dict(req,task_id='t',reason='调整间隔',check_interval_seconds=30),'chat')
    assert t['check_interval_seconds']==30
    assert 29< t['next_check']-time.time()<=30
    r=core.make_report(t)
    core.observe(dict(report_id=r['id'],decision='on_task',reason='正常'), 'chat')
    assert 29<core.store.get('task','t')['next_check']-time.time()<=30


@pytest.mark.parametrize('value',[0,-1,True,1.5,'300',None])
def test_invalid_interval(core,value):
    with pytest.raises(ValueError,match='正整数秒'):plan(core,check_interval_seconds=value)


def test_default_and_legacy_interval(core):
    assert plan(core)['check_interval_seconds']==core.interval
    assert core.task_interval({})==core.interval
    normal=Supervisor(core.directory/'default',core.lifecycle)
    assert normal.interval==600
    normal.store.close()


def test_observation_does_not_change_heartbeat_interval(core):
    t=plan(core,check_interval_seconds=900);r=core.make_report(t)
    core.observe(dict(report_id=r['id'],decision='suspect',reason='解释用途'),'chat')
    assert 899<core.store.get('task','t')['next_check']-time.time()<=900
    r=core.make_report(core.store.get('task','t'))
    core.observe(dict(report_id=r['id'],decision='returned',reason='返回任务'),'chat')
    assert 899<core.store.get('task','t')['next_check']-time.time()<=900


@pytest.mark.parametrize('offsets',[(20,80),(-20,120),(50,150),(-50,50),(0,100)])
def test_conflicting_plans_rejected_with_details(core,offsets):
    start=time.time()+100
    t=plan(core,start_at=start,end_at=start+100)
    with pytest.raises(ValueError,match='任务时间冲突') as error:
        plan(core,task_id='new',start_at=start+offsets[0],end_at=start+offsets[1])
    assert t['id'] in str(error.value) and t['agreement'] in str(error.value)
    assert len(core.live())==1 and core.store.get('task','new') is None


def test_adjacent_tasks_and_self_retry_allowed(core):
    start=time.time()+100
    a=plan(core,start_at=start,end_at=start+100)
    plan(core,task_id='b',start_at=start+100,end_at=start+200)
    plan(core,task_id='c',start_at=start-100,end_at=start)
    assert plan(core)['id']==a['id']
    core.revise(dict(a,task_id='t',reason='仅修改文字',agreement='新的约定'),'chat')
    assert len(core.live())==3


def test_revision_conflict_keeps_original_and_report(core):
    start=time.time()+100
    a=plan(core,start_at=start,end_at=start+100)
    plan(core,task_id='b',start_at=start+100,end_at=start+200)
    report=core.make_report(a)
    original=core.store.get('task','t')
    with pytest.raises(ValueError,match='b：'):
        core.revise(dict(original,task_id='t',reason='延期',end_at=start+150),'chat')
    assert core.store.get('task','t')==original
    assert core.store.get('report',report['id'])['status']==report['status']


@pytest.mark.parametrize('status',['completed','cancelled','not_completed'])
def test_finished_tasks_do_not_block(core,status):
    t=plan(core);core.finish(dict(task_id='t',verdict=status,reason='结束'),'chat')
    assert plan(core,task_id='new')['status']=='active'


def test_overdue_task_does_not_reserve_time_after_end(core):
    plan(core,start_at=time.time()-200,end_at=time.time()-100,deadline_policy='continue')
    assert plan(core,task_id='new')['status']=='active'


def test_concurrent_conflicting_plans_only_admit_one(core):
    from concurrent.futures import ThreadPoolExecutor
    start=time.time()+100
    def create(i):
        try:return plan(core,task_id=str(i),start_at=start,end_at=start+100)['id']
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,range(2)))
    assert sum(r is not None for r in results)==1
    assert len(core.live())==1


def test_http_conflict_returns_specific_task(core):
    import http.client
    import threading
    import json
    from http.server import ThreadingHTTPServer
    from focus_demo.http_api import Handler
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.core=core
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    t=plan(core)
    try:
        conn=http.client.HTTPConnection(*server.server_address)
        request=dict(t,task_id='conflicting',session_id='chat')
        conn.request('POST','/plan',body=json.dumps(request),headers={'Content-Type':'application/json'})
        response=conn.getresponse();data=json.loads(response.read());conn.close()
        assert response.status==400
        assert 't：' in data['error'] and t['agreement'] in data['error']
        assert core.store.get('task','conflicting') is None
    finally:
        server.shutdown();server.server_close();thread.join()


def test_loopback_http_requires_configured_token(core):
    import http.client,threading
    from http.server import ThreadingHTTPServer
    from focus_demo.http_api import Handler
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.core=core;server.api_token='local-test-token'
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        for header,expected in [({},403),({'Authorization':'Bearer wrong'},403),({'Authorization':'Bearer local-test-token'},200)]:
            connection=http.client.HTTPConnection(*server.server_address)
            connection.request('POST','/state',body='{}',headers=header);response=connection.getresponse()
            assert response.status==expected
            response.read();connection.close()
    finally:server.shutdown();server.server_close();thread.join()


def desktop_sample(title,mono):  # 功能：构造一个带命名窗口的真实采样结构，供检查报告使用。
    return {'ts':time.time(),'mono':mono,
            'desktop':{'available':True,'backend':'fixture','limitations':[],
                       'windows':[{'id':'gnome:1','app':'test','title':title,'pid':1,'process':{'identity':'x'},
                                   'focused':True,'visible':True,'mapped':True,'ui_text':'','screenshot':{'sha256':'aa'}}]},
            'browser':{'available':False,'pages':[],'limitations':[]}}


def post(core,path,body):  # 功能：走真实 HTTP 处理器，不直接调用内部方法。
    import http.client,json,threading
    from http.server import ThreadingHTTPServer
    from focus_demo.http_api import Handler
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.core=core
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        connection=http.client.HTTPConnection(*server.server_address)
        connection.request('POST',path,body=json.dumps(body),headers={'Content-Type':'application/json'})
        response=connection.getresponse();data=json.loads(response.read());connection.close()
        assert response.status==200,data
        return data
    finally:server.shutdown();server.server_close();thread.join()


def titles(report):  # 功能：读取一份报告当前对象里的窗口标题。
    return {item.get('title') for item in report['effective']['current_objects']}


def test_check_returns_fresh_report_and_new_ref(core):  # focus_check 必须真的重新取证。
    task=plan(core)
    core.store.add_sample('t',desktop_sample('旧标题',10.0))
    core.store.add_sample('t',desktop_sample('旧标题',10.5))
    frozen=core.make_report(task)  # 心跳报告冻结在"旧标题"。
    assert '旧标题' in titles(frozen)
    core.store.add_sample('t',desktop_sample('新标题',11.0))
    data=post(core,'/check',{'task_id':'t','session_id':'chat'})
    assert data['report_id']!=frozen['id']
    assert '新标题' in {item.get('title') for item in data['overview']['current_objects']}


def test_check_does_not_move_schedule(core):  # 重新取证不能打乱心跳节奏。
    task=plan(core)
    core.store.add_sample('t',desktop_sample('标题',10.0))
    core.tick(task['next_check']+1)
    before=core.store.get('task','t')
    post(core,'/check',{'task_id':'t','session_id':'chat'})
    after=core.store.get('task','t')
    assert after['cursor']==before['cursor'] and after['next_check']==before['next_check']


def test_check_supersedes_pending_report(core):  # 检查后下一次心跳仍会发生，不被 pending 挡住。
    task=plan(core)
    core.store.add_sample('t',desktop_sample('标题',10.0))
    core.tick(task['next_check']+1)
    assert core.due()
    post(core,'/check',{'task_id':'t','session_id':'chat'})
    current=core.store.get('task','t')
    core.tick(current['next_check']+1)
    assert core.due()


def test_standby_does_not_cancel_reports_already_given_to_the_agent(core):
    """待机只作废没发出去的报告；已经交给 AI 的那份必须还能 focus_observe。"""
    task=plan(core)
    core.store.add_sample('t',desktop_sample('标题',10.0))
    handed=core.make_report(task);core.delivered(handed['id'])  # 已交给 AI。
    quiet=core.make_report(core.store.get('task','t'))  # 还没发出去。
    limit=core.settings()['away_heartbeats']
    current=core.store.get('task','t');current.update(no_input_reports=limit-1,absence_input_at=100.0);core.store.save('task',current)
    core.presence={'available':True,'last_input_at':100.0,'idle_seconds':500}  # 真实输入计数显示一直没有新输入。
    core.make_report(core.store.get('task','t'),count_input=True)  # 这一拍跨过阈值 → 进入待机。
    assert core.store.get('task','t')['standby'] is True
    assert core.store.get('report',quiet['id'])['status']=='cancelled'  # 没发出去的照样作废。
    assert core.store.get('report',handed['id'])['status']=='delivered'  # 已交给 AI 的保留下来。
    core.observe(dict(report_id=handed['id'],decision='uncertain',reason='用户离席，暂不打扰'),'chat')  # 不再抛"报告已结束"。


def test_explicit_admission_refreshes_idle_timer_but_cannot_revive_exit(core):
    core.empty_since=time.time()-20
    assert not core.ensure()['shutting_down']
    assert time.time()-core.empty_since<1
    core.shutting_down=True
    before=core.empty_since
    assert core.ensure()['shutting_down']
    assert core.empty_since==before
    assert not core.live()
