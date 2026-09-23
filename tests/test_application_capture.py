"""通用应用回归：Wayland 关联、深层正文和实际进程日志。"""
import os
import subprocess
import sys
from pathlib import Path

from focus_demo.ui_probe import match_window
from focus_demo.generic_logs import GenericLogs
from focus_demo.platforms import process_info


def test_completed_window_survives_later_provider_timeout():
    import json
    from focus_demo.details import probe_results
    code="import json,time;print(json.dumps({'win:1':{'text':'已完成正文'}}),flush=True);print('{\"win:2\":',end='',flush=True);time.sleep(30)"
    try:
        subprocess.run([sys.executable,'-c',code],capture_output=True,timeout=.5)
    except subprocess.TimeoutExpired as error:
        assert probe_results(error.stdout)=={'win:1':{'text':'已完成正文'}}
    else:raise AssertionError('The blocking provider did not time out')


def test_wayland_local_coordinates_require_unique_title_and_size():
    window = {'title': 'folder', 'rect': [900, 400, 800, 600]}
    candidate = {'title': 'folder', 'rect': [0, 0, 800, 600], 'node': 'actual'}
    assert match_window(window, [candidate])['node'] == 'actual'
    assert match_window(window, [candidate, dict(candidate, node='other')]) is None
    assert match_window(window, [dict(candidate, title='other')]) is None
    assert match_window(window, [dict(candidate, rect=[0, 0, 700, 600])]) is None
    assert match_window(window, [dict(candidate, rect=[1, 1, 800, 600])]) is None


def test_same_geometry_remains_ambiguous():
    window = {'title': 'first', 'rect': [10, 20, 800, 600]}
    candidates = [dict(window, node=1), dict(window, title='second', node=2)]
    assert match_window(window, candidates) is None


def test_automatic_logs_from_actual_child_and_skip_database(tmp_path, monkeypatch):
    code = """import sys,time
from pathlib import Path
root=Path(sys.argv[1])
a=(root/'runtime.log').open('w');a.write('CHILD_REAL_ACTIVITY_MARKER\\n');a.flush()
b=(root/'000003.log').open('w');b.write('DATABASE_WAL_MUST_NOT_READ\\n');b.flush()
print('ready',flush=True)
time.sleep(30)
"""
    # Use the actual executable, not a Windows venv launcher with its own child process.
    executable = process_info(os.getpid())['exe']
    process = subprocess.Popen([executable, '-c', code, str(tmp_path)], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert process.stdout.readline().strip() == 'ready'
        # 这里只隔离系统日志；子进程和 open_files 使用真实系统接口。
        monkeypatch.setattr(GenericLogs, 'journal', lambda *a: {'source': 'system_journal', 'text': '[]'})
        rows = GenericLogs(system=True).read({'pid': os.getpid(), 'process': process_info(os.getpid())})
        assert any('CHILD_REAL_ACTIVITY_MARKER' in row.get('text', '') and row.get('query_pid') == process.pid for row in rows)
        assert not any('DATABASE_WAL_MUST_NOT_READ' in row.get('text', '') for row in rows)
        assert GenericLogs().read({'pid': os.getpid(), 'process': process_info(os.getpid())}) == []
    finally:
        process.terminate(); process.wait(timeout=5)


def test_gnome_snapshot_visibility_uses_real_stacking(monkeypatch):
    from focus_demo.collectors import GnomeDesktop
    monkeypatch.setattr('focus_demo.desktop_bridge.call', lambda *a, **k: {
        'screen':[0,0,800,600], 'windows':[
            {'id':'covered','mapped':True,'rect':[0,0,800,600]},
            {'id':'top','mapped':True,'rect':[0,0,800,600]},
            {'id':'min','mapped':False,'rect':[0,0,800,600]}]})
    result=GnomeDesktop().capture()
    assert [w['visible'] for w in result['windows']]==[False,True,False]


def test_probe_protocol_preserves_unicode_under_gbk():
    import json
    environment = dict(os.environ, PYTHONIOENCODING='gbk')
    code = """import sys
import focus_demo.ui_probe as probe
sys.argv = ['ui_probe', '--batch']
probe.linux_batch = probe.windows_batch = lambda windows, emit=None: {'w': {'text': '\\u200b\\U0001f600正文'}}
probe.main()
"""
    reply = subprocess.run([sys.executable, '-c', code], input=b'[]',
                           capture_output=True, env=environment, check=True)
    assert json.loads(reply.stdout)['w']['text'] == '\u200b😀正文'


def test_launcher_logs_do_not_include_unrelated_app_tree():
    class Process:
        def __init__(self, executable, children=()):
            self.executable, self.descendants = executable, list(children)
        def exe(self): return self.executable
        def children(self): return self.descendants
    hidden_helper = Process('/bin/launcher')
    launched_app = Process('/opt/app/program', [hidden_helper])
    helper = Process('/bin/launcher')
    root = Process('/bin/launcher', [launched_app, helper])
    assert GenericLogs.application_processes(root) == [root, helper]


def test_transparent_overlay_does_not_hide_underlying_work():
    from focus_demo.collectors import mark_visibility
    windows = [
        {'id': 'work', 'rect': [0, 0, 100, 100], 'mapped': True},
        {'id': 'alpha', 'rect': [0, 0, 100, 100], 'mapped': True,
         'occludes': False, 'visibility_uncertain': True},
    ]
    mark_visibility(windows, [0, 0, 100, 100])
    assert windows[0]['visible'] is True
    assert windows[0]['visible_fraction_estimate'] == 1
    assert windows[1]['visible'] is None
    assert windows[1]['visible_fraction_estimate'] is None


def test_native_region_hole_and_hidden_window():
    from focus_demo.collectors import mark_visibility
    windows = [
        {'id': 'work', 'rect': [0, 0, 100, 100], 'mapped': True},
        {'id': 'region', 'rect': [0, 0, 100, 100], 'mapped': True,
         'shape_rects': [[0, 0, 25, 100], [75, 0, 25, 100]]},
        {'id': 'cloaked', 'rect': [0, 0, 100, 100], 'mapped': False},
    ]
    mark_visibility(windows, [0, 0, 100, 100])
    assert windows[0]['visible_fraction_estimate'] == .5
    assert windows[2]['visible'] is False


def test_uncertain_overlay_survives_report_without_visible_time():
    from focus_demo.prompts import timeline
    from focus_demo.reports import build_reports
    window = {'id': 'alpha', 'app': 'overlay', 'title': 'floating', 'pid': 1,
              'mapped': True, 'focused': False, 'visible': None,
              'visibility_note': 'alpha unknown', 'ui_text': 'float', 'rect': [0, 0, 10, 10]}
    samples = [{'sample_id': i, 'mono': i*2, 'ts': i*2,
                'desktop': {'available': True, 'windows': [window]},
                'browser': {'available': False, 'pages': []}} for i in range(2)]
    result = timeline(samples, 2)
    branch = next(iter(build_reports(result).values()))
    assert branch['visible_seconds'] == 0
    assert branch['events'][0]['objects'][0]['visibility_note'] == 'alpha unknown'
    assert result['window_inventory'][0]['visible'] is None


def test_wayland_focus_does_not_reject_a_unique_window():
    from focus_demo.ui_probe import match_windows
    window={'id':'chrome','title':'Page','rect':[0,716,1147,884],
            'buffer_rect':[-16,706,1179,926],'focused':False}
    root={'node':'document-root','title':'Page','rect':[0,0,1179,926],'active':True}
    assert match_windows([window],[root])['chrome']['node']=='document-root'


def test_wayland_duplicate_geometry_reports_group_without_guessing_from_focus():
    from focus_demo.ui_probe import match_windows
    windows=[{'id':'left','title':'same','buffer_rect':[4,14,492,372],'focused':False},
             {'id':'right','title':'same','buffer_rect':[484,14,492,372],'focused':True}]
    roots=[{'node':'a','title':'same','rect':[0,0,492,372],'active':True},
           {'node':'b','title':'same','rect':[0,0,492,372],'active':False}]
    result=match_windows(windows,roots)
    assert result['left']==result['right']
    assert result['left']['nodes']==['a','b']
    assert 'node' not in result['left']
    assert '隐藏' in result['left']['association']
    # User accepts hidden content in this ambiguity, so one visible member is
    # still allowed to read the group; no renewed visibility qualification.
    assert match_windows(windows[:1],roots)['left']['nodes']==['a','b']
