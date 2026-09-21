import time
from focus_demo.native_browser import snapshots
from focus_demo.ui_structure import describe_window,entry


def test_document_tree_preserves_nested_frames_and_native_controls():
    nodes=[entry(0,None,'window','Chrome'),entry(1,0,'edit','Address',text='https://one'),
           dict(entry(2,0,'document','Article'),document_url='https://one'),
           entry(3,2,'table','Results'),entry(4,3,'row'),entry(5,4,'cell','42'),
           dict(entry(6,2,'document','Frame'),document_url='https://frame'),entry(7,6,'button','Submit')]
    result=describe_window(nodes)
    assert len(result['documents'])==1
    assert 'table "Results"' in result['documents'][0]['text']
    assert 'Submit' in result['documents'][0]['text']
    assert 'Address' in result['text'] and 'Submit' not in result['text']


def test_hidden_cache_and_old_period_are_not_reinterpreted():
    window={'id':'w','pid':10,'visible':True,'mapped':True,'process':{'identity':'p'},'browser_documents':[
        {'title':'Page','url':'https://one','selected':True,'text':'body','captured_at':time.time()-31,'capture_interval_seconds':10}]}
    assert not snapshots({'windows':[window]},{'browser_interval_seconds':100})['available']
    window['browser_documents'][0]['captured_at']=time.time()
    assert snapshots({'windows':[window]}, {})['available']
    for change in ({'visible':False},{'minimized':True},{'mapped':False}):
        assert not snapshots({'windows':[{**window,**change}]}, {})['available']


def test_ambiguous_documents_are_not_assigned_fake_window_or_tab_identity():
    document={'title':'Same title','url':'https://one','selected':None,'text':'group body',
              'captured_at':time.time(),'association':'ambiguous_process_group',
              'window_ids':['left','right'],'document_index':0}
    windows=[{'id':key,'pid':10,'visible':True,'process':{'identity':'p'},'browser_documents':[document]}
             for key in ('left','right')]
    result=snapshots({'windows':windows},{})
    assert len(result['snapshots'])==1
    record=result['snapshots'][0]
    assert record['native_window_id'] is None and 'tab_id' not in record
    assert record['selected'] is None and record['focused'] is None
    assert record['native_window_ids']==['left','right'] and record['may_include_hidden']
