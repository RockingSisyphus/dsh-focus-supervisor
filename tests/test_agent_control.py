import json
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from focus_demo.supervisor import Supervisor

@pytest.fixture
def core(tmp_path):
    c=Supervisor(tmp_path/'backend',SimpleNamespace(enable=lambda:None))
    c.project=tmp_path/'project';c.project.mkdir()
    yield c
    c.store.close()

def plan(c,scheduled=True):
    return c.plan({'task_id':'t','agreement':'理解论文','task_prompt':'请问我论文的关键假设。','project_dir':str(c.project),
        'start_at':time.time()+(100 if scheduled else -10),'end_at':time.time()+1000,
        'allow_early_finish':True},'chat')

def test_settings_permission_matrix(core):
    core.configure({'patch':{'instructions':'我的使用说明','heartbeat_prompt':'我的心跳','mascot_size':200}},'ui')
    task=plan(core)
    core.configure({'patch':{'instructions':'改说明','heartbeat_prompt':'UI修改'}},'ui')
    task['status']='active';core.store.save('task',task)
    core.configure({'patch':{'heartbeat_prompt':'进行中修改'}},'ai','chat')
    core.configure({'task_id':'t','patch':{'task_prompt':'新的任务附加要求','mascot_size':240}},'ai','chat')
    assert core.store.get('task','t')['task_prompt']=='新的任务附加要求'
    with pytest.raises(ValueError):core.configure({'task_id':'t','patch':{'task_prompt':'越权'}},'ai','other')
    core.finish({'task_id':'t','verdict':'completed','reason':'理解已确认'},'chat')
    assert 'task_prompt' not in core.store.get('task','t')
    core.configure({'patch':{'instructions':'任务结束后可以修改'}},'ai','chat')
    assert core.settings()['instructions']=='任务结束后可以修改'

def test_task_prompt_required(core):
    with pytest.raises(ValueError,match='task_prompt'):
        core.plan({'task_id':'t','agreement':'读论文','start_at':1,'end_at':2,'allow_early_finish':True},'chat')

def test_unmodified_prompt_defaults_are_not_saved_with_other_settings(core):
    core.configure({'patch':{'mascot_size':180}},'ai','chat')
    stored=core.store.get('settings','global')
    assert stored['mascot_size']==180
    assert all(key not in stored for key in ('instructions','instructions_full','heartbeat_prompt'))


def test_only_legacy_shipped_prompts_migrate(tmp_path, monkeypatch):
    import hashlib
    import focus_demo.supervisor as supervisor_module
    from focus_demo.control import DEFAULTS
    monkeypatch.setattr(supervisor_module,'PREVIOUS_DEFAULT_PROMPT_HASHES',{
        'instructions':hashlib.sha256('old shipped default'.encode()).hexdigest(),
        'heartbeat_prompt':hashlib.sha256('old heartbeat'.encode()).hexdigest(),
    })
    directory=tmp_path/'legacy'
    old=Supervisor(directory,SimpleNamespace(enable=lambda:None))
    old.store.save('settings',{'id':'global','instructions':'old shipped default',
                               'instructions_full':'user custom manual','heartbeat_prompt':'old heartbeat'})
    old.store.close()
    upgraded=Supervisor(directory,SimpleNamespace(enable=lambda:None))
    try:
        stored=upgraded.store.get('settings','global')
        assert 'instructions' not in stored and 'heartbeat_prompt' not in stored
        assert stored['instructions_full']=='user custom manual'
        assert upgraded.settings()['instructions']==DEFAULTS['instructions']
        assert upgraded.settings()['heartbeat_prompt']==DEFAULTS['heartbeat_prompt']
    finally:upgraded.store.close()


def test_full_instructions_fall_back_to_defaults_and_stay_locked_like_instructions(core):
    from focus_demo.control import DEFAULTS
    # An installation upgraded from an older version stores a row without the new field.
    core.store.save('settings',{'id':'global','instructions':'自定义说明','heartbeat_prompt':'自定义心跳','mascot_size':200})
    value=core.settings()
    assert value['instructions']=='自定义说明' and value['heartbeat_prompt']=='自定义心跳' and value['mascot_size']==200
    assert value['instructions_full']==DEFAULTS['instructions_full'] and value['instructions_full']
    core.configure({'patch':{'instructions_full':'自定义完整说明'}},'ai','chat')
    assert core.settings()['instructions_full']=='自定义完整说明'
    core.configure({'patch':{'instructions_full':DEFAULTS['instructions_full']}},'ai','chat')
    assert core.settings()['instructions_full']==DEFAULTS['instructions_full']
    plan(core)
    core.configure({'patch':{'instructions_full':'有预约时也可改'}},'ai','chat')
    task=core.store.get('task','t');task['status']='active';core.store.save('task',task)
    core.configure({'patch':{'instructions_full':'任务进行中也可改'}},'ui')
    assert core.settings()['instructions_full']=='任务进行中也可改'

def test_export_real_files_detect_tampering_and_cleanup(core):
    task=plan(core,False);report=core.make_report(task)
    obj={'id':'window:reader','ref':'e:reader','app':'Reader','title':'论文阅读','focused':True,'visible':True}
    report['effective']['segments']=[{'id':'s:1','duration_seconds':600,'objects':[obj]}]
    report['effective']['evidence']={'e:reader':{**obj,'text':'实际分支正文'}}
    core.store.save('report',report)
    response=core.report_tool({'report_id':report['id'],'operation':'get_overview'})
    exported=response['evidence_export'];assert 'error' not in exported,exported
    folder=Path(exported['folder']);assert folder.is_relative_to(core.project)
    row=response['overview']['programs'][0]
    branch=json.loads((folder/row['detail_file']).read_text(encoding='utf-8'))
    assert branch['evidence']['e:reader']['text']=='实际分支正文'
    assert (folder/'timeline.json').exists()
    assert core.report_tool({'report_id':report['id'],'operation':'verify_files'})['verified']
    (folder/'timeline.json').write_text('{"fake":"user changed this"}')
    # Rewriting the exported manifest cannot rewrite the root-held digest.
    (folder/'manifest.json').write_text('{}')
    verify=core.report_tool({'report_id':report['id'],'operation':'verify_files'})
    assert not verify['verified'] and 'timeline.json' in verify['changed_or_missing']
    core.finish({'task_id':'t','verdict':'completed','reason':'完成'},'chat')
    assert not folder.exists() and not core.store.all('report') and not core.store.all('export')
    assert 'task_prompt' not in core.store.get('task','t')

def test_agent_action_has_no_semantic_escalation_gate(core):
    task=plan(core,False);report=core.make_report(task)
    report['effective']['evidence']['window:1']={'id':'window:1','pid':123}
    core.store.save('report',report)
    calls=[]
    core.sensor=SimpleNamespace(call=lambda op,arg:(calls.append((op,arg)) or {'minimized':True}))
    outcome=core.act({'task_id':'t','action':'minimize_window','report_id':report['id'],'target_ref':'window:1'},'chat')
    assert outcome['minimized'] and calls[0][0]=='minimize'
    alert=core.act({'task_id':'t','action':'remind','action_id':'a','message':'解释一下？','image':'question','popup':True,'sound':True},'chat')
    assert calls[-1][0]=='notify' and alert['image']=='question'
    core.act({'task_id':'t','action':'remind','action_id':'a','message':'重试'},'chat')
    assert len(calls)==2
    with pytest.raises(ValueError):core.act({'task_id':'t','action':'minimize_window','report_id':report['id'],'target_ref':'window:1'},'other')

def test_heartbeat_continues_after_delivery_and_uses_latest_prompts(core):
    task=plan(core,False);core.tick()
    first=core.due()[0];assert first['phase']=='start'
    core.delivered(first['id'])
    current=core.store.get('task','t');core.tick(current['next_check']+1)
    second=core.due()[0];assert second['id']!=first['id']
    core.configure({'task_id':'t','patch':{'task_prompt':'实时新要求'}},'ai','chat')
    data=core.report_tool({'report_id':second['id'],'operation':'get_overview'})
    assert data['task']['task_prompt']=='实时新要求' and data['heartbeat_prompt']


def test_finish_cleans_capture_even_with_future_task(core):
    task=plan(core,False)
    core.plan({**task,'task_id':'future','start_at':task['end_at']+100,'end_at':task['end_at']+1000},'chat')
    shots=core.directory/'screenshots';shots.mkdir();(shots/'old.png').write_bytes(b'old capture')
    core.finish({'task_id':'t','verdict':'completed','reason':'已完成'},'chat')
    assert core.live()[0]['id']=='future' and not list(shots.iterdir())


def test_export_collects_legacy_windows_screenshot_paths(tmp_path):
    from focus_demo.evidence_export import export_request
    from types import SimpleNamespace
    import base64
    folder=tmp_path/'screenshots';folder.mkdir();(folder/'image.png').write_bytes(b'actual fixture bytes')
    effective={'segments':[],'evidence':{}}
    effective['desktop_screenshot']={'path':r'screenshots\image.png','scope':'full_desktop'}
    report={'id':'r','effective':effective,'raw':effective}
    request,_=export_request({'id':'task','project_dir':str(tmp_path)},report,tmp_path)
    assert base64.b64decode(request['files']['screenshots/image.png'])==b'actual fixture bytes'


def reviewed_report(core,created_at=None):  # 功能：构造一份带窗口证据的报告，供关闭动作测试。
    task=plan(core,False);report=core.make_report(task)
    report['effective']['evidence']['window:1']={'id':'window:1','pid':123}
    if created_at is not None:report['created_at']=created_at
    core.store.save('report',report);return task,report


def test_minimize_allowed_with_old_report(core):  # 时效闸门已取消：很久以前审核的窗口证据仍可用于关闭。
    task,report=reviewed_report(core,created_at=time.time()-7200)  # 两小时前。
    calls=[]
    core.sensor=SimpleNamespace(call=lambda op,arg:(calls.append((op,arg)) or {'minimized':True}))
    outcome=core.act({'task_id':'t','action':'minimize_window','report_id':report['id'],'target_ref':'window:1'},'chat')
    assert outcome['minimized'] and calls[0][0]=='minimize'


def test_minimize_rejected_for_finished_task(core):  # 边界仍在：任务结束后不能再用旧报告动手。
    task,report=reviewed_report(core)
    core.finish({'task_id':'t','verdict':'completed','reason':'测试结束'},'chat')
    core.sensor=SimpleNamespace(call=lambda op,arg:{'minimized':True})
    with pytest.raises(ValueError):core.act({'task_id':'t','action':'minimize_window','report_id':report['id'],'target_ref':'window:1'},'chat')


def test_minimize_rejected_for_foreign_revision(core):  # 边界仍在：报告必须属于当前任务版本。
    task,report=reviewed_report(core)
    report['revision']=task['revision']+1;core.store.save('report',report)
    core.sensor=SimpleNamespace(call=lambda op,arg:{'minimized':True})
    with pytest.raises(ValueError):core.act({'task_id':'t','action':'minimize_window','report_id':report['id'],'target_ref':'window:1'},'chat')


def test_documents_require_check_before_close():  # 文档不能与关闭判据脱节。
    root=Path(__file__).resolve().parents[1]
    defaults=json.loads((root/'dsh-plugin/default-prompts.json').read_text(encoding='utf-8'))
    assert '先用 focus_check' in defaults['heartbeat_prompt'] and 'minimize_window' in defaults['heartbeat_prompt']
    assert '动手前应先用 focus_check' in defaults['instructions_full'] and 'minimize_window' in defaults['instructions_full']
    assert '不再限制证据时效' in defaults['instructions_full']  # 通用约定一节不能还写着旧的 120 秒闸门。
    assert '动手前应先用 focus_check' in (root/'dsh-plugin/chat-host.mjs').read_text(encoding='utf-8')
    from focus_demo.control import DEFAULTS
    assert DEFAULTS==defaults  # 后台与插件读取同一个定义。

@pytest.mark.parametrize('scheduled',[True,False])
def test_unprotected_live_settings_and_manual_finish(core,scheduled):
    task=plan(core,scheduled)
    assert not core.settings()['ui_locked']
    core.configure({'patch':{'instructions':'changed','heartbeat_prompt':'changed','sampling':{'text_chars':123}}},'ui')
    assert core.settings()['sampling']['text_chars']==123
    assert core.finish_ui({'task_id':task['id']})['status']=='cancelled'
    assert not core.live()

def test_removed_global_protection_switch_is_not_reintroduced(core):
    with pytest.raises(ValueError,match='未知设置字段'):
        core.configure({'patch':{'protect_task_changes':True}},'ui')
