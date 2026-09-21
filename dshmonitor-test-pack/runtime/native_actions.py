"""Monitor-specific actions for the reusable JSON harness; no expected outcomes."""
import json,time
from pathlib import Path
from focus_demo.common import write_json
from support import *
from dsh_test_harness.wait import until

class NativeActions:
    def __init__(self,core,collector,fixture,out,ready,samples):
        self.core,self.collector,self.fixture,self.out,self.ready,self.samples=core,collector,fixture,out,ready,samples
        self.ids={}
    def call(self,step):
        methods={'plan','revise','configure','observe','delivered','finish','settings','state'}
        if step['method'] not in methods:raise ValueError('Unsupported monitor method')
        try:return getattr(self.core,step['method'])(*step.get('args',[]))
        except ValueError as error:
            if step.get('capture_error'):return {'error':str(error)}
            raise
    def phase(self,step):
        phase=step['phase'];write_json(self.fixture/'command.json',phase)
        def applied():
            try:
                value=json.loads((self.fixture/'applied.json').read_text(encoding='utf-8'))
                return value if value['id']==phase['id'] else None
            except (OSError,ValueError):return None
        value=until(applied)
        import sys
        prefix='win:' if sys.platform=='win32' else 'gnome:'
        self.ids={k:prefix+str(v) for k,v in (self.ready.get('windows') or value['windows']).items()}
        if sys.platform!='win32':
            from dsh_test_harness.gnome import action
            for key,opts in phase['windows'].items():
                record={'id':self.ids[key]}
                if not opts.get('visible',True):
                    action('minimize',record);continue
                action('restore',record)
                if 'rect' in opts:action('layout',record,rect=opts['rect'])
                if opts.get('minimized'):action('minimize',record)
        if phase.get('focus'):
            from dsh_test_harness.desktop import Desktop
            Desktop().activate({'id':self.ids[phase['focus']]})
        return self.observe(step)

    def observe(self,step):
        deadline=time.monotonic()+step.get('seconds',0)
        observations=[]
        while True:
            self.core.capture()
            if self.core.capture_error:raise RuntimeError(self.core.capture_error)
            observations.append(self.samples[-1])
            if time.monotonic()>=deadline:break
            time.sleep(.25)
        write_json(self.out/(step['id']+'-samples.json'),observations)
        own={k:next((w for w in self.samples[-1]['desktop']['windows'] if w['id']==wid),{}) for k,wid in self.ids.items()}
        write_json(self.out/(step['id']+'-observed.json'),own)
        return {k:{'raw':w,'present':bool(w),'visible':w.get('visible',False),'focused':w.get('focused',False),
            'text':w.get('ui_text',''),'nodes':(w.get('ui_structure') or {}).get('captured_nodes',0),
            'scope':(w.get('screenshot') or {}).get('scope'),
            'logs_text':'\n'.join(log.get('text','') for log in w.get('logs',[])),
            'has_content':any(w.get(field) for field in ('ui_text','logs','screenshot'))} for k,w in own.items()}
    def report(self,step):
        self.core.tick();r=self.core.make_report(self.core.store.get('task',step['task_id']))
        exported=self.core.report_tool({'report_id':r['id'],'operation':'get_overview'})
        write_json(self.out/(step['name']+'-report.json'),r)
        self.core.delivered(r['id']);return {'report':r,'export':exported['evidence_export']}
    def stale_minimize(self,step):return self.collector.minimize_window_verified(step['window'])
    def minimize(self,step):
        report=self.core.make_report(self.core.store.get('task',step['task_id']))
        ref=next(k for k,v in report['effective']['evidence'].items() if v['id']==self.ids[step['target']])
        result=self.core.act({'task_id':step['task_id'],'action':'minimize_window','report_id':report['id'],'target_ref':ref},step['session'])
        if result.get('minimized'):until(lambda:next((w for w in self.collector.capture()['desktop']['windows'] if w['id']==self.ids[step['target']] and w.get('mapped') is False),None))
        return result
    def resources(self,step):return {'reports':len(self.core.store.all('report')),'exports':len(self.core.store.all('export')),'settings':self.core.settings()}
    def registry(self):return {'monitor.call':self.call,'native.phase':self.phase,'native.observe':self.observe,'monitor.report':self.report,'native.stale_minimize':self.stale_minimize,'native.minimize':self.minimize,'monitor.resources':self.resources}
