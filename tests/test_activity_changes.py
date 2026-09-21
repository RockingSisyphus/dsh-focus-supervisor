from focus_demo.activity import activity_changes
from focus_demo.reports import EvidenceTools


def sample(i,focused=True,available=True):
    return {'sample_id':i,'ts':100+i*2,'mono':i*2,'desktop':{'available':available,'windows':[
        {'id':'w1','title':'A','process':{'identity':'p1'},'focused':focused,'visible':True,'ui_text':'body'}]}}


def test_unknown_interval_does_not_join_focus_streaks():
    rows=activity_changes([sample(0),sample(1),sample(2,available=False),sample(3),sample(4)],{})
    assert rows[0]['focus_seconds']==4
    assert rows[0]['longest_focus_seconds']==2
    assert rows[0]['visible_seconds']==4


def test_previous_report_content_and_focus_changes_are_facts():
    first=activity_changes([sample(0),sample(1)],{})
    changed=sample(2,False);changed['desktop']['windows'][0]['ui_text']='different'
    row=activity_changes([changed],{},first)[0]
    assert row['changes'][0]['type']=='changed'
    assert row['changes'][0]['fields']['focused'] is False
    assert row['changes'][0]['fields']['body_changed'] is True
    assert row['focus_seconds']==0


def test_activity_pagination_has_no_gaps():
    rows=[{'id':str(i)} for i in range(13)]
    tool=EvidenceTools({'activity_changes':rows})
    actual=[];offset=0
    while offset is not None:
        result=tool.call('read_activity_changes',{'offset':offset})
        actual+=result['changes'];offset=result['next_offset']
    assert actual==rows


def test_hidden_and_budget_missing_body_do_not_claim_content_changed():
    first=sample(0)
    first['desktop']['windows'][0]['browser_documents']=[{'url':'https://page','text':'same','captured_at':100}]
    hidden=sample(1,False)
    hidden['desktop']['windows'][0].update(visible=False,minimized=True)
    hidden['desktop']['windows'][0].pop('ui_text')
    restored=sample(2)
    restored['desktop']['windows'][0]['browser_documents']=first['desktop']['windows'][0]['browser_documents']
    row=activity_changes([first,hidden,restored],{})[0]
    assert all(not c.get('fields',{}).get('body_changed') for c in row['changes'])
    assert row['last_body_captured_at']==100
