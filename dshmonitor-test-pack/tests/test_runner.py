"""Exercise failure reporting itself; these are not product feature evidence."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PACK = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('monitor_pack_runner', PACK / 'run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@pytest.mark.parametrize("timeout", [False, True])
def test_failure_exit_continuation_and_regression(tmp_path, timeout):
    # Run the real CLI with one deliberate failure followed by one success.
    # This catches a runner that prints failure but exits zero or stops early.
    pack = tmp_path / 'pack'
    pack.mkdir()
    shutil.copyfile(PACK / 'run.py', pack / 'run.py')
    shutil.copytree(PACK.parent / 'test-support',tmp_path / 'test-support',ignore=shutil.ignore_patterns('__pycache__'))
    (pack/'cases').mkdir()
    cases = []
    for name, code in [('broken', 1), ('healthy', 0)]:
        case = {'id': name, 'title': name, 'engine': 'command',
                'features': [name], 'platforms':['linux','windows'],'group':'regular','verification':'contract','argv': ['$python', '-c', f'raise SystemExit({code})']}
        if timeout and name == 'broken':
            case['argv'] = ['$python', '-c', 'import time; time.sleep(10)']
            case['timeout'] = 0.1
        (pack / 'cases' / f'{name}.json').write_text(json.dumps(case))
        cases.append(f'{name}.json')
    suite = {'name': 'runner-self-test', 'cases': cases, 'features': [
        {'id': name, 'title': name} for name in ['broken', 'healthy', 'uncovered']]}
    (pack / 'suite.json').write_text(json.dumps(suite))
    baseline = tmp_path / 'baseline.json'
    baseline.write_text(json.dumps({'cases': [{'id': 'broken', 'status': 'passed'}]}))
    output = tmp_path / 'output'
    result = subprocess.run([sys.executable, str(pack / 'run.py'), 'test', '--local',
                             '--workers', '17', '--baseline', str(baseline), '--output', str(output)],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 1, result.stdout + result.stderr
    summary = json.loads((output / 'summary.json').read_text())
    assert summary['status'] == 'failed'
    assert summary['automated_passed'] == summary['automated_failed'] == 1
    assert [f['status'] for f in summary['features']] == ['not_run', 'not_run', 'not_run']
    assert not summary['all_features_verified']
    assert ('exceeded 0.1 seconds' if timeout else 'exit 1') in (output / 'report.md').read_text()


def test_partial_run_does_not_reuse_historical_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'PACK', tmp_path)
    (tmp_path / 'case.json').write_text(json.dumps({'id': 'case', 'features': ['feature']}))
    suite = {'name': 'partial', 'cases': ['case.json'],
             'features': [{'id': 'feature', 'title': 'feature'}]}
    summary = runner.report(tmp_path, [], suite, {'cases': [{'id': 'case', 'status': 'passed'}]})
    assert summary['features'][0]['status'] == 'not_run'
    assert not summary['all_features_verified']


def test_unknown_steps_and_wrong_expectations_fail(monkeypatch):
    monkeypatch.syspath_prepend(str(PACK / 'runtime'))
    from json_case import Scenario
    scenario = Scenario.__new__(Scenario)
    scenario.page = scenario.backend = None
    scenario.actions={}
    with pytest.raises(ValueError, match='Unknown operation'):
        scenario.execute({'op': 'pretend-success'})
    with pytest.raises(AssertionError, match='actual 6'):
        scenario.compare(6, 'equals', 600)
    with pytest.raises(ValueError, match='Unknown assertion'):
        scenario.compare(600, 'pretend-equal', 600)


def test_new_json_is_discovered_without_changing_python_or_suite(tmp_path,monkeypatch):
    (tmp_path/'cases').mkdir()
    case={'id':'new-scenario','title':'New','engine':'dsh','features':[],
          'group':'regular','verification':'product','platforms':['linux','windows'],
          'steps':[{'id':'a','op':'assert','actual':1,'operator':'equals','expected':1}]}
    (tmp_path/'cases/new.json').write_text(json.dumps(case))
    monkeypatch.setattr(runner,'PACK',tmp_path)
    assert [c['id'] for _,c in runner.load_cases({'cases':[]},False)]==['new-scenario']


def test_cleanup_import_failure_does_not_hide_scenario_timeout(tmp_path,monkeypatch):
    """Contract injection: a timed-out host and broken cleanup must both be reported."""
    from types import SimpleNamespace
    runtime=tmp_path/'runtime';runtime.mkdir()
    (runtime/'host.py').write_text("import sys,time;from pathlib import Path;p=Path(sys.argv[sys.argv.index('--output')+1]);p.mkdir();(p/'cleanup-state.json').write_text('{}');time.sleep(10)")
    (runtime/'backend.py').write_text("raise ModuleNotFoundError('cleanup dependency missing')")
    monkeypatch.setattr(runner,'PACK',tmp_path)
    monkeypatch.delitem(sys.modules,'backend',raising=False)
    output=tmp_path/'output';output.mkdir()
    case={'id':'timeout','title':'timeout','engine':'dsh','verification':'product','features':[],
          'platforms':['linux','windows'],'timeout':.5}
    args=SimpleNamespace(modules=tmp_path,browser_plugin=tmp_path,human_review=False)
    result=runner.execute_case(tmp_path/'case.json',case,output,args)
    assert 'Scenario exceeded 0.5 seconds' in result['error']
    cleanup=json.loads((output/'timeout/interrupted-cleanup.json').read_text())
    assert cleanup['status']=='failed'
    assert 'cleanup dependency missing' in cleanup['error']
