import json
from dsh_test_harness.catalog import discover,select
from dsh_test_harness.results import write_report

def test_explicit_selection_does_not_expand_manual_or_install(tmp_path):
    (tmp_path/'cases').mkdir()
    for name,group in [('normal','regular'),('extra','extended'),('installation','manual')]:
        (tmp_path/'cases'/f'{name}.json').write_text(json.dumps({'id':name,'engine':'dsh','group':group,'steps':[]}))
    cases=discover(tmp_path)
    assert [c['id'] for _,c in select(cases,ids=['extra'])]==['extra']
    assert [c['id'] for _,c in select(cases)]==['normal']
    assert {c['id'] for _,c in select(cases,extended=True)}=={'normal','extra'}

def test_contracts_never_prove_product_and_not_run_is_not_pass(tmp_path):
    features=[{'id':'close','title':'Close'}]
    result=write_report(tmp_path,[{'id':'unit','verification':'contract','features':['close'],'status':'passed'}, {'id':'actual','verification':'product','features':['close'],'status':'not_run'}],features)
    assert result['status']=='not_run'
    assert not result['all_features_verified']
    assert result['features'][0]['status']=='not_run'

def test_failed_independent_assertion_never_turns_into_pass(tmp_path):
    import pytest
    from dsh_test_harness.scenario import ScenarioEngine
    case={'steps':[{'id':'bad','op':'assert','actual':False,'operator':'equals','expected':True,'continue_on_failure':True},
                   {'id':'observe','op':'observe'}, {'id':'good','op':'assert','actual':True,'operator':'equals','expected':True}]}
    engine=ScenarioEngine(case,tmp_path,actions={'observe':lambda step:{'actual_window_present':True}})
    with pytest.raises(AssertionError):engine.run()
    assert [s['status'] for s in engine.steps]==['failed','passed','passed']
    assert engine.steps[0]['failure_stage']=='assertion'

def test_unknown_operation_leaves_dependents_not_run(tmp_path):
    import pytest
    from dsh_test_harness.scenario import ScenarioEngine
    engine=ScenarioEngine({'steps':[{'id':'bad','op':'missing'}, {'id':'later','op':'assert','actual':True,'operator':'equals','expected':True}]},tmp_path)
    with pytest.raises(ValueError):engine.run()
    assert [s['status'] for s in engine.steps]==['failed','not_run']


def test_coverage_requires_each_platform_and_keeps_all_rounds(tmp_path):
    case={'id':'close','features':['close'],'verification':'product','verification_layer':'dsh','platforms':['linux','windows']}
    row={**case,'platform':'linux','status':'passed'}
    result=write_report(tmp_path,[row],catalog=[case])
    assert result['features'][0]['status']=='not_run'
    windows=next(c for c in result['coverage_matrix'] if c['platform']=='windows' and c['layer']=='dsh')
    assert windows['not_run']==['close']
    result=write_report(tmp_path,[{**row,'status':'failed'},row,{**row,'platform':'windows'}],catalog=[case])
    assert result['features'][0]['status']=='failed'
    assert all(c['status']=='not_run' for c in result['coverage_matrix'] if c['layer']=='real_ai')


def test_desktop_capture_does_not_count_as_complete_dsh(tmp_path):
    row={'id':'capture','features':['evidence'],'verification':'product','verification_layer':'desktop','platform':'linux','status':'passed'}
    result=write_report(tmp_path,[row])
    assert result['features'][0]['status']=='not_run'
    assert next(c for c in result['coverage_matrix'] if c['layer']=='desktop')['status']=='passed'


def test_public_capabilities_are_inventoried_even_without_a_case(tmp_path):
    from dsh_test_harness.catalog import capability_features,inferred_features
    (tmp_path/'dsh-plugin').mkdir()
    (tmp_path/'dsh-plugin/chat-host.mjs').write_text("tool('focus_new','New',{},execute);")
    features=capability_features(tmp_path)
    result=write_report(tmp_path/'report',[],features)
    assert result['features'][0]['id']=='tool.focus_new'
    assert result['features'][0]['status']=='not_run'
    case={'steps':[{'op':'model.call','tool':'focus_act','arguments':{'action':'force_close'}},
                   {'op':'ui.settings','values':{'mascot_size':200}}]}
    assert set(inferred_features(case))=={'tool.focus_act','tool.focus_act.force_close.process','setting.mascot_size'}


def test_wait_pumps_the_supplied_event_loop():
    from dsh_test_harness.wait import until
    events=[]
    assert until(lambda: events or None,wait=lambda seconds:events.append('target-resumed'))==['target-resumed']
