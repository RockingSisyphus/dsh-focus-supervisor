import base64
import json
import unittest
from unittest.mock import Mock
from focus_demo.prompts import timeline
from focus_demo.evidence_export import export_request


class BrowserSemanticHistoryTests(unittest.TestCase):
    def collector(self):
        # Frozen evidence fixture; live observer transport has separate contracts and VM cases.
        return Mock(collect_once=lambda: {'available':True,'snapshots':[{'tab_id':1,
            'browser_instance_id':'b1','captured_at':1,'title':'论文',
            'snapshot':{'text':'heading 论文\nparagraph 事务提交'},
            'visibility_class':'focused_visible','source':'browser accessibility tree'}]})

    def test_history_keeps_past_visible_and_hidden_identity_without_body(self):
        window = {'id':'w1','app':'browser','title':'论文','focused':True,'visible':True,'mapped':True,'ui_text':'visible text'}
        samples = [{'ts':1,'mono':1,'sample_id':'1','desktop':{'available':True,'windows':[window]},'browser':{'available':False,'pages':[]}},
                   {'ts':2,'mono':2,'sample_id':'2','desktop':{'available':True,'windows':[{**window,'focused':False,'visible':False,'mapped':False,'ui_text':'hidden text'}]},'browser':{'available':False,'pages':[]}}]
        result = timeline(samples,1)
        # Stage 3 retains hidden identities for actions, but never hidden bodies.
        self.assertEqual([w['id'] for w in result['window_inventory']], ['w1'])
        self.assertFalse(result['window_inventory'][0]['visible'])
        self.assertNotIn('ui_text',result['window_inventory'][0])
        self.assertEqual(len(result['segments'][0]['objects']), 1)
        self.assertNotIn('hidden text', json.dumps(result))

    def test_frozen_export_deduplicates_cache_without_focus_duration(self):
        semantic = self.collector().collect_once()
        samples = [{'ts': n, 'mono': n, 'sample_id': str(n), 'desktop': {'available': True, 'windows': []},
                    'browser': {'available': False, 'pages': [], 'semantic': semantic}} for n in (1, 2, 3)]
        effective = timeline(samples, 1)
        self.assertEqual(len(effective['browser_snapshots']), 1)
        self.assertTrue(all(not segment['objects'] for segment in effective['segments']))
        request, hashes = export_request({'id': 'test', 'project_dir': '/tmp/test'},
                                        {'id': 'report', 'effective': effective, 'raw': effective}, '/tmp')
        document = json.loads(base64.b64decode(request['files']['browser-snapshots.json']))
        self.assertIn('事务提交', document['snapshots'][0]['snapshot']['text'])
        self.assertIn('browser-snapshots.json', hashes)
        overview = json.loads(base64.b64decode(request['files']['overview.json']))
        self.assertEqual(overview['browser_semantics']['snapshots'], 1)
        self.assertEqual(overview['program_count'], 0)
