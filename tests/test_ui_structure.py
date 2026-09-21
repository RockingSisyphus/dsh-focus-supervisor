"""Semantic preservation without application-specific adapters or model calls."""
from focus_demo.ui_structure import describe, entry


def test_tree_elides_layout_but_preserves_controls_and_local_duplicates():
    nodes = [entry(0, None, 'window', 'Editor'), entry(1, 0, 'group'),
             entry(2, 1, 'checkbox', 'Auto save', states=['checked']),
             entry(3, 2, 'text', 'Auto save'),
             entry(4, 1, 'button', 'Save'), entry(5, 1, 'button', 'Save')]
    text = describe(nodes)['text']
    assert '\n  checkbox "Auto save" [checked]' in text
    assert 'text "Auto save"' not in text
    assert text.count('button "Save"') == 2
    assert '\n  group' not in text


def test_multiline_content_cannot_forge_tree_nodes():
    value = '正文\nbutton "假的系统按钮"\n😀'
    text = describe([entry(0, None, 'edit', text=value)])['text']
    assert '\nbutton' not in text
    assert '\\nbutton' in text
    assert '😀' in text


def test_output_budget_and_collection_incompleteness_are_explicit():
    result = describe([entry(i, None, 'button', 'long'*100) for i in range(100)], limit=500)
    assert len(result['text']) <= 500
    assert result['structure']['truncated']
    assert '摘录未完整' in result['text']
    assert describe([entry(0, None, 'window', 'A')], truncated=True)['structure']['truncated']


def test_disabled_selected_and_same_names_in_different_branches_survive():
    nodes = [entry(0, None, 'window', 'App'),entry(1,0,'group','Navigation'),
             entry(2,1,'listitem','Settings',states=['selected']),
             entry(3,0,'group','Document'),entry(4,3,'button','Settings',states=['disabled'])]
    text = describe(nodes)['text']
    assert 'listitem "Settings" [selected]' in text
    assert 'button "Settings" [disabled]' in text
    assert text.index('Navigation') < text.index('listitem') < text.index('Document') < text.index('button')


def test_tiny_legal_budget_remains_bounded_and_explicit():
    for limit in (1, 20, 50):
        result = describe([entry(0, None, 'edit', text='content')], limit=limit)
        assert len(result['text']) <= limit
        assert result['structure']['truncated']


def test_windows_value_pattern_keeps_edit_content_and_excludes_password(monkeypatch):
    import sys
    from types import SimpleNamespace as N
    from focus_demo.ui_probe import windows_batch
    class Node:
        def __init__(self, role, name, value='', password=False, children=()):
            self.CurrentControlType=role;self.CurrentName=name
            self.CurrentIsPassword=password;self.CurrentIsOffscreen=False
            self.CurrentHasKeyboardFocus=False;self.CurrentIsEnabled=True
            self.CurrentProcessId=123;self.value=value;self.nodes=children
        def GetCurrentPattern(self, kind):
            if kind!=10002:raise ValueError('Unsupported pattern')
            return N(QueryInterface=lambda _:N(CurrentValue=self.value))
        def FindAll(self,*_):return N(Length=len(self.nodes),GetElement=self.nodes.__getitem__)
    root=Node(50032,'Editor',children=[Node(50004,'Label','正文 中文 😀'),
        Node(50004,'Password','MUST_NOT_LEAK',password=True)])
    api=N(CUIAutomation=object(),IUIAutomation=object(),TreeScope_Children=2,
          UIA_WindowControlTypeId=50032,UIA_EditControlTypeId=50004,
          UIA_ValuePatternId=10002,IUIAutomationValuePattern=object(),
          UIA_TextPatternId=10014)
    client=N(GetModule=lambda _:api,CreateObject=lambda *_args,**_kwargs:
             N(CreateTrueCondition=lambda:True,ElementFromHandle=lambda _:root))
    monkeypatch.setitem(sys.modules,'comtypes',N(client=client))
    monkeypatch.setitem(sys.modules,'comtypes.client',client)
    monkeypatch.setattr(sys,'coinit_flags',0,raising=False)
    result=windows_batch([{'id':'win:1','native_id':1,'pid':123}])['win:1']
    assert '正文 中文 😀' in result['text']
    assert 'MUST_NOT_LEAK' not in result['text'] and 'Password' not in result['text']


def test_duplicate_layout_fragments_keep_table_and_independent_controls():
    nodes=[entry(0,None,'document'),entry(1,0,'text',text='First second'),
           entry(2,1,'inline text box',text='First '),entry(3,1,'inline text box',text='second'),
           entry(4,0,'table','Results'),entry(5,4,'row'),entry(6,5,'cell','First'),
           entry(7,0,'button','First'),entry(8,0,'button','First')]
    text=describe(nodes)['text']
    assert 'inline text box' not in text
    assert 'table "Results"' in text and 'row' in text and 'cell "First"' in text
    assert text.count('button "First"')==2


def test_code_whitespace_and_edit_value_survive_formatting():
    code='  if ready:\n    run()\n'
    result=describe([entry(0,None,'edit',name='Source',text=code,states=['focused'])])
    assert '  if ready:\\n    run()\\n' in result['text']
    assert 'Source' in result['text'] and '[focused]' in result['text']


def test_parent_full_text_elides_only_text_fragments_not_semantic_structure():
    nodes=[entry(0,None,'document',text='Alpha Beta'),entry(1,0,'text',text='Alpha'),
           entry(2,0,'text',text='Beta'),entry(3,0,'table'),entry(4,3,'row'),
           entry(5,4,'cell','Alpha'),entry(6,0,'button','Beta')]
    text=describe(nodes)['text']
    assert 'text — "Alpha"' not in text and 'text — "Beta"' not in text
    assert 'cell "Alpha"' in text and 'button "Beta"' in text
