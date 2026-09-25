from focus_demo.activity import activity_changes
from focus_demo.reports import EvidenceTools, overview


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
    assert len(actual)==len(rows)
    assert {row['id'] for row in actual}=={row['id'] for row in rows}


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


def test_window_focus_total_is_not_attributed_to_its_first_page_title():
    def obj(title):
        return {'id':'chrome-window','app':'chrome','title':title,
                'process':{'identity':'chrome-process'},'focused':True,'visible':True}
    effective={'segments':[
        {'id':'s1','real_duration_seconds':2,'objects':[obj('Video')]},
        {'id':'s2','real_duration_seconds':4,'duration_seconds':99,'objects':[obj('Paper editor')]},
    ],'activity_changes':[{'id':'chrome-process:chrome-window','window_id':'chrome-window',
        'title':'Video','last_state':{'title':'Paper editor'},'focus_seconds':6,
        'visible_seconds':6,'longest_focus_seconds':4,'changes':[],
        'evidence_refs':['video-ref','paper-ref']}]}
    short=overview(effective)['activity_changes'][0]
    assert 'title' not in short
    assert short['last_title']=='Paper editor'
    assert short['focus_titles']==[{'title':'Paper editor','seconds':4},{'title':'Video','seconds':2}]
    assert short['focus_seconds']==6 and short['latest_evidence']==['paper-ref']
    full=EvidenceTools(effective).call('read_activity_changes',{'offset':0})['changes'][0]
    assert full['focus_titles']==short['focus_titles']
    assert 'title' not in full


def test_browser_overview_shows_recent_distinct_titles_not_first_snapshots():
    def snapshot(title,when):
        return {'native_window_id':'chrome-window','title':title,'url':'https://example.test/'+title,
                'captured_at':when,'snapshot':{'text':title}}
    summary=overview({'browser_snapshots':[
        snapshot('Video',1),snapshot('Video',2),snapshot('Paper editor',3),snapshot('Paper editor',4)
    ]})['browser_semantics']
    assert summary['snapshots']==4
    assert [page['title'] for page in summary['pages']]==['Paper editor','Video']
    assert [page['captured_at'] for page in summary['pages']]==[4,2]
