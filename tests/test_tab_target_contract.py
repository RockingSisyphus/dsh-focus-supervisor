"""A readable browser document is not automatically an addressable tab."""


def test_grouped_document_is_not_an_actionable_tab():
    from focus_demo.prompts import timeline

    process = {'pid': 16136, 'identity': 'chrome-instance'}
    snapshot = {
        'native_window_id': None,
        'native_window_ids': ['gnome:164', 'gnome:5'],
        'process': process,
        'pid': process['pid'],
        'browser_instance_id': process['identity'],
        'document_index': 2,
        'title': 'Example',
        'url': 'https://example.test/',
        'selected': None,
        'captured_at': 1.0,
        'connection_kind': 'system_accessibility',
        'snapshot': {'text': 'A readable page'},
    }
    sample = {
        'sample_id': 1, 'mono': 1.0, 'ts': 1.0,
        'desktop': {'available': True, 'windows': []},
        'browser': {'available': False, 'pages': [], 'action_targets': [],
                    'semantic': {'snapshots': [snapshot]}},
    }
    evidence = list(timeline([sample], 2)['evidence'].values())
    assert len(evidence) == 1
    assert evidence[0]['kind'] == 'browser_document'
    assert evidence[0]['snapshot']['text'] == 'A readable page'


def test_grouped_document_with_exact_tab_identity_is_actionable():
    from focus_demo.prompts import timeline

    process = {'pid': 12, 'identity': 'chrome-instance'}
    tab = {'native_window_id': None, 'native_window_ids': ['gnome:1', 'gnome:2'],
           'process': process, 'pid': 12, 'browser_instance_id': process['identity'],
           'tab_id': 'atspi:owner:/tab', 'native_tab': {'owner': 'owner', 'path': '/tab'},
           'title': 'Example', 'url': 'https://example.test/', 'captured_at': 1.0,
           'snapshot': {'text': 'A readable page'}}
    sample = {'sample_id': 1, 'mono': 1.0, 'ts': 1.0,
              'desktop': {'available': True, 'windows': []},
              'browser': {'available': True, 'pages': [], 'action_targets': [],
                          'semantic': {'snapshots': [tab]}}}
    evidence = list(timeline([sample], 2)['evidence'].values())
    assert len(evidence) == 1
    assert evidence[0]['kind'] == 'browser_tab'
    assert evidence[0]['native_window_id'] is None


def test_old_document_reference_cannot_kill_browser_as_a_tab(monkeypatch):
    from focus_demo import close_actions

    monkeypatch.setattr('focus_demo.actions.force_close_authorization',
                        lambda *a: {'authorized': True, 'pid': 12, 'identity': 'life'})
    monkeypatch.setattr(close_actions, 'close_tab',
                        lambda *a: (_ for _ in ()).throw(AssertionError('no tab identity')))
    monkeypatch.setattr('focus_demo.actions.kill_verified_process',
                        lambda *a: (_ for _ in ()).throw(AssertionError('must not kill')))
    result = close_actions.force_close(None, {
        'kind': 'browser_tab', 'id': 'document:life:2:1',
        'process': {'pid': 12, 'identity': 'life'}}, 'browser_tab')
    assert result['closed'] is False
    assert result['actual_scope'] == 'none'
    assert [a['scope'] for a in result['attempts']] == ['browser_tab']
    assert result['escalation_available'] is True
    assert 'force_kill=true' in result['reason']


def test_ambiguous_root_keeps_its_exact_accessibility_tabs(monkeypatch):
    from focus_demo import atspi_dbus, native_tabs

    class Bus:
        def __init__(self, *args): pass
        def call(self, owner, path, interface, method, *args):
            if method == 'ListNames': return [':1.12']
            if method == 'GetConnectionUnixProcessID': return 12
            if method == 'GetChildren' and path == atspi_dbus.ROOT:
                return [(':1.12', '/window1'), (':1.12', '/window2')]
            if method == 'GetChildren':
                return [(':1.12', path.replace('window', 'tab'))] if 'window' in path else []
            if method == 'GetExtents': return [0, 0, 900, 560]
            if method == 'GetAll': return {'Name': {'data': 'Same title'}}
            if method == 'GetRole': return 37 if '/tab' in path else 1
            if method == 'GetState': return [1 << 23, 0]
            if method == 'GetRoleName': return 'page tab'
            raise AssertionError((path, method))
        def close(self): pass

    monkeypatch.setattr(atspi_dbus, 'Bus', Bus)
    windows = [{'id': f'gnome:{n}', 'pid': 12, 'app': 'google-chrome.desktop',
                'process': {'pid': 12, 'name': 'chrome'},
                'title': 'Same title', 'buffer_rect': [n, 0, 900, 560]}
               for n in (1, 2)]
    result = native_tabs.capture(windows, include_background=True)
    assert len(result['tabs']) == 2
    assert {row['a11y_root']['path'] for row in result['tabs']} == {'/window1', '/window2'}
    assert all(row['window_id'] is None for row in result['tabs'])
    assert all(row['window_ids'] == ['gnome:1', 'gnome:2'] for row in result['tabs'])


def test_exact_unmapped_tab_failure_does_not_escalate_to_process(monkeypatch):
    from focus_demo import close_actions

    monkeypatch.setattr('focus_demo.actions.force_close_authorization',
                        lambda *a: {'authorized': True, 'pid': 12, 'identity': 'life'})
    monkeypatch.setattr(close_actions, 'close_tab',
                        lambda *a: {'closed': False, 'reason': 'native action failed'})
    monkeypatch.setattr(close_actions, 'close_window',
                        lambda *a: (_ for _ in ()).throw(AssertionError('unknown window')))
    monkeypatch.setattr('focus_demo.actions.kill_verified_process',
                        lambda *a: (_ for _ in ()).throw(AssertionError('must not kill')))
    result = close_actions.force_close(None, {
        'kind': 'browser_tab', 'tab_id': 'atspi:owner:/tab',
        'native_tab': {'owner': 'owner', 'path': '/tab'},
        'process': {'pid': 12, 'identity': 'life'}}, 'browser_tab')
    assert result['closed'] is False
    assert [attempt['scope'] for attempt in result['attempts']] == ['browser_tab']
    assert result['actual_scope'] == 'none'
    assert result['escalation_scope'] == 'process'


def test_explicit_tab_escalation_kills_owning_process_without_retry(monkeypatch):
    from focus_demo import close_actions

    monkeypatch.setattr('focus_demo.actions.force_close_authorization',
                        lambda *a: {'authorized': True, 'pid': 987654, 'identity': 'life'})
    monkeypatch.setattr(close_actions, 'close_tab',
                        lambda *a: (_ for _ in ()).throw(AssertionError('explicit kill must not retry tab')))
    monkeypatch.setattr(close_actions, 'close_window',
                        lambda *a: (_ for _ in ()).throw(AssertionError('tab must not close a window')))
    monkeypatch.setattr('focus_demo.actions.kill_verified_process',
                        lambda pid, identity: {'closed': True, 'pid': pid, 'identity': identity})
    expected = {'kind': 'browser_tab', 'tab_id': 'atspi:owner:/tab',
                'process': {'pid': 987654, 'identity': 'life'}}
    result = close_actions.force_close(None, expected, 'browser_tab', force_kill=True)
    assert result['closed'] is True
    assert result['actual_scope'] == 'process'
    assert [a['scope'] for a in result['attempts']] == ['process']


def test_saved_old_heartbeat_close_guidance_updates_without_losing_custom_text():
    from focus_demo.supervisor import Supervisor

    old = ('我的自定义检查要求。窗口再次出现或仍持续分心时，先用 remind 告知用户将要强制关闭，'
           '再用 force_close 强制结束进程（可能丢失未保存内容），这是最后手段。')

    class Store:
        def __init__(self): self.settings = {'id': 'global', 'heartbeat_prompt': old}
        def get(self, kind, identity): return self.settings
        def all(self, kind): return []
        def save(self, kind, value): self.settings = value

    supervisor = Supervisor.__new__(Supervisor)
    supervisor.store = Store()
    supervisor._migrate_task_defaults()
    current = supervisor.store.settings['heartbeat_prompt']
    assert current.startswith('我的自定义检查要求。')
    assert 'force_kill=true' in current
    assert '再用 force_close 强制结束进程' not in current
