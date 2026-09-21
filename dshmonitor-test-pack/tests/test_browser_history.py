import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('browser_history', Path(__file__).resolve().parents[1]/'runtime/browser_history.py')
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)


def test_model_input_does_not_include_ground_truth(tmp_path):
    for name in ('overview.json','timeline.json','browser-snapshots.json'):
        (tmp_path/name).write_text('{"observed":"测试正文"}')
    (tmp_path/'truth.json').write_text('DO_NOT_LEAK')
    text = history.make_input(tmp_path, '阅读任务')
    assert '测试正文' in text and 'DO_NOT_LEAK' not in text


def test_piecewise_clock_mapping_preserves_stage_boundaries():
    spans = [{'real_start':10,'real_end':15,'start_seconds':0,'seconds':120,'end_seconds':120},
             {'real_start':16,'real_end':26,'start_seconds':120,'seconds':480,'end_seconds':600}]
    assert history.project_time(12.5, spans) == 60
    assert history.project_time(15.5, spans) == 120
    assert history.project_time(21, spans) == 360
    assert history.project_time(30, spans) == 600
