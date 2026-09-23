import json
import time
from types import SimpleNamespace
import pytest
from focus_demo.sampling_settings import DEFAULTS,merge
from focus_demo.supervisor import Supervisor
from focus_demo.reports import EvidenceTools

def test_partial_merge_and_validation():
    original=merge(patch={'sampling':{'text_chars':789}})
    current=merge(original,{'sampling':{'interval_seconds':8}})
    assert current['sampling']['text_chars']==789
    assert original['sampling']['interval_seconds']==2
    assert current['sampling']['browser_pages'] is None
    for bad in [True,0,-1,float('nan'),float('inf'),'2']:
        with pytest.raises(ValueError):merge(patch={'sampling':{'interval_seconds':bad}})
    with pytest.raises(ValueError):merge(patch={'sampling':{'text_nodes':2.5}})
    with pytest.raises(ValueError):merge(patch={'sampling':{'typo':3}})

def test_settings_persist_and_keep_existing_permissions(tmp_path):
    core=Supervisor(tmp_path,SimpleNamespace(enable=lambda:None),test_mode=True)
    core.configure({'patch':{'instructions':'CUSTOM','sampling':{'text_chars':900}}},actor='ui')
    task=core.plan(dict(task_id='t',task_prompt='observe',agreement='work',project_dir=str(tmp_path),start_at=time.time()-1,end_at=time.time()+300,allow_early_finish=True,strictness='strict'),'chat')
    with pytest.raises(ValueError,match='锁定'):core.configure({'patch':{'sampling':{'text_chars':100}}},actor='ui')
    core.configure({'patch':{'sampling':{'interval_seconds':7}}},actor='ai',session_id='chat')
    assert core.live()[0]['id']==task['id']
    other=Supervisor(tmp_path,core.lifecycle)
    assert other.settings()['sampling']['text_chars']==900
    assert other.settings()['sampling']['interval_seconds']==7
    assert other.settings()['instructions']=='CUSTOM'
    other.store.close();core.store.close()

def test_text_pagination_reconstructs_whole_evidence(tmp_path):
    text='正文0123456789'*90
    tools=EvidenceTools({'evidence':{'e':{'ui_text':text}}},tmp_path,reporting={'text_page_chars':73})
    pieces=[];offset=0
    while True:
        result=tools.call('read_evidence_text',{'reference':'e','source':'ui_text','offset':offset})
        assert len(result['text'])<=73
        pieces.append(result['text'])
        if result['next_offset'] is None:break
        offset=result['next_offset']
    assert ''.join(pieces)==text


def test_default_image_sizes_and_custom_resize(tmp_path):
    from PIL import Image
    from focus_demo.details import DetailCollector
    details=DetailCollector(SimpleNamespace(data_dir=tmp_path,screenshots=True))
    source=Image.new('RGB',(2000,1000),'blue')
    original=details.save_image(source,{})
    assert (original['width'],original['height'])==(1600,800)
    options=merge(patch={'sampling':{'image_width':400,'image_height':300}})['sampling']
    details.configure(options)
    resized=details.save_image(source,{})
    assert (resized['width'],resized['height'])==(400,200)
    assert source.size==(2000,1000)

def test_old_interval_is_used_for_historical_gap():
    from focus_demo.prompts import timeline
    def sample(i,interval):
        return {'sample_id':i,'ts':100+i*10,'mono':100+i*10,'desktop':{'available':True,'windows':[]},'browser':{'available':False,'pages':[]},'settings':{'sampling':{'interval_seconds':interval},'reporting':{'preview_chars':180}}}
    slow=[sample(0,10),sample(1,2)]
    assert timeline(slow,2)['unobserved_gap_seconds']==0
    fast=[sample(0,2),sample(1,10)]
    assert timeline(fast,10)['unobserved_gap_seconds']==10
    assert len(timeline(slow,2)['settings_timeline'])==2

def test_independent_detail_intervals(tmp_path):
    from focus_demo.details import DetailCollector
    details=DetailCollector(SimpleNamespace(data_dir=tmp_path))
    details.configure(merge(patch={'sampling':{'screenshot_interval_seconds':20,'text_interval_seconds':4,'log_interval_seconds':30}})['sampling'])
    now=time.monotonic()
    details.last_channels={'image':now-8,'text':now-8,'logs':now-8}
    assert details.channel_due('text',{'windows':[]})
    assert not details.channel_due('image',{'windows':[]})
    assert not details.channel_due('logs',{'windows':[]})

def test_browser_budget_is_shared_by_documents_not_iframes():
    from focus_demo.ui_structure import ReadBudget
    budget=ReadBudget({'browser_pages':2,'browser_due':True,'native_due':False})
    first={'document_url':'https://one'};frame={'document_url':'https://frame'}
    assert budget.enter(first)
    assert budget.enter(frame,first)
    assert budget.enter({'document_url':'https://two'})
    assert not budget.enter({'document_url':'https://three'})
    assert not budget.enter({'role':'edit'})

def test_preview_limit_keeps_full_local_evidence():
    from focus_demo.prompts import timeline
    sample={'sample_id':1,'ts':100,'mono':100,'desktop':{'available':True,'windows':[{'id':'w','app':'fixture','title':'window','focused':True,'visible':True,'ui_text':'FULL_LOCAL_EVIDENCE_'*40}]},'browser':{'available':False,'pages':[]},'settings':merge(patch={'reporting':{'preview_chars':20}})}
    later={**sample,'sample_id':2,'ts':102,'mono':102}
    result=timeline([sample,later],2)
    preview=result['segments'][0]['objects'][0]['text_preview']
    assert len(preview.split("\n[已截断]")[0])<=20
    assert preview.endswith("\n[已截断]")
    assert next(iter(result['evidence'].values()))['text']==sample['desktop']['windows'][0]['ui_text']


def test_hidden_windows_do_not_receive_published_body_images_or_logs(tmp_path, monkeypatch):
    from focus_demo.details import DetailCollector
    details=DetailCollector(SimpleNamespace(data_dir=tmp_path))
    details.worker=SimpleNamespace(is_alive=lambda:True)
    monkeypatch.setattr(details,'prepare_windows',lambda desktop:desktop)
    window={'id':'w','instance_key':'identity','title':'same','rect':[0,0,100,100]}
    details.published={'windows':{details.key(window):{'ui_text':'old body','logs':[{'text':'old log'}],'screenshot':{'file':'old.png'}}}}
    for state in ({'visible':False},{'mapped':False},{'minimized':True}):
        result=details.capture({'windows':[{**window,**state}]})['windows'][0]
        assert not any(key in result for key in ('ui_text','logs','screenshot'))
    assert details.capture({'windows':[{**window,'visible':True}]})['windows'][0]['ui_text']=='old body'
