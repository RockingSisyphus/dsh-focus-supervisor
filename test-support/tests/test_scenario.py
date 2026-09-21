import json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dsh_test_harness.scenario import ScenarioEngine

def test_new_case_only_needs_json(tmp_path):
    spec={'variables':{'text':'中文 😀'},'steps':[
        {'id':'echo','op':'echo','value':{'$ref':'text'},'bind':'response'},
        {'id':'exact','op':'assert','actual':{'$ref':'response'},'operator':'equals','expected':'中文 😀'}]}
    file=tmp_path/'new.json';file.write_text(json.dumps(spec),encoding='utf-8')
    ScenarioEngine(json.loads(file.read_text()),tmp_path,actions={'echo':lambda s:s['value']}).run()
    records=json.loads((tmp_path/'steps.json').read_text())
    assert [(s['id'],s['status']) for s in records]==[('echo','passed'),('exact','passed')]

def test_failed_expectation_preserves_evidence_and_does_not_run_later_actions(tmp_path):
    called=[]
    spec={'steps':[{'id':'wrong','op':'assert','actual':1,'operator':'equals','expected':2},{'id':'later','op':'later'}]}
    with pytest.raises(AssertionError):ScenarioEngine(spec,tmp_path,actions={'later':lambda s:called.append(1)}).run()
    assert called==[]
    assert json.loads((tmp_path/'steps.json').read_text())[0]['status']=='failed'
