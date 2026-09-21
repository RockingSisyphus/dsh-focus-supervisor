"""fixture scenario actions; expectations are supplied by JSON."""
import json,os,re,time,socket,http.client,shutil,subprocess,sys,tempfile,threading
from pathlib import Path
from urllib.parse import urlparse
from dsh_test_harness.desktop import Desktop
from dsh_test_harness.wait import until
from ui import *
PACK=Path(__file__).resolve().parents[2];ROOT=PACK.parent

def file_write(self,step):
    op=step["op"];p=self.page;b=self.backend
    path = Path(step['path']).resolve()
    if not path.is_relative_to(Path(self.values['project'])):
        raise ValueError('Test writes must stay in the private project')
    path.write_text(step['text'], encoding='utf-8')
    return None

def file_exists(self,step):
    op=step["op"];p=self.page;b=self.backend
    return Path(step['path']).exists()

def python_dependency(self,step):
    """Temporarily remove the real prerequisite in a disposable install guest."""
    def move(source,destination):
        if os.name=='nt':
            from dsh_test_harness.vm.input import request
            request('move_file',source=str(source),destination=str(destination))
        else:subprocess.run(['sudo','mv','--',str(source),str(destination)],check=True,capture_output=True)
    if step['available']:
        self.restore_python_dependency()
        return {'available':True}
    import uuid
    source=Path(sys._base_executable) if os.name=='nt' else Path('/usr/bin/python3')
    backup=source.with_name(source.name+'.dsh-test-'+uuid.uuid4().hex)
    def restore():
        if backup.exists():move(backup,source)
    self.restore_python_dependency=restore
    self.backend.cleanup_callbacks.append(restore)
    move(source,backup)
    return {'available':source.exists(),'path':str(source),'fault':'real executable temporarily renamed'}

def desktop_browser(self,step):
    op=step["op"];p=self.page;b=self.backend
    url=(PACK/'fixtures'/step['file']).as_uri()
    if 'legacy-browser' not in self.entities.items:
        self.entities.browser({'entity':'legacy-browser','url':url})
    else:self.entities.items['legacy-browser']['page'].goto(url)
    b.fixture_page=self.entities.items['legacy-browser']['page']
    b.fixture_page.bring_to_front()
    window=self.entities.observe('legacy-browser')['window']
    Desktop().activate(window)
    window=self.entities.observe('legacy-browser')['window']
    text=b.fixture_page.locator('body').inner_text()
    if step.get('expect_text') and step['expect_text'] not in text:raise AssertionError('Fixture page did not render expected content')
    established_at=time.time()
    b.core.capture()
    self.execute({'op':'report.drain'})
    return {**window,'ui_text':text,'established_at':established_at,'observed_by':'browser DOM and native window driver'}

def desktop_notepad(self,step):
    op=step["op"];p=self.page;b=self.backend
    spec=json.loads((PACK/'fixtures'/step.get('fixture','notepad.json')).read_text(encoding='utf-8'))
    for i,row in enumerate(spec['windows']):row['id']=step['id']+'-'+str(i)
    self.entities.app({'entity':step['id'],**spec})
    identifier=spec['windows'][0]['id']
    pid=self.entities.items[identifier]['pid']
    window=self.entities.observe(identifier)['window']
    Desktop().activate(window)
    value=self.entities.interact({'entity':identifier,'action':'read'})
    if step.get('expect_text') and step['expect_text'] not in value['input_text']:raise AssertionError('Native fixture control did not contain expected text')
    established_at=time.time()
    b.core.capture()
    self.execute({'op':'report.drain'})
    return {**value['window'],'ui_text':value['input_text'],'established_at':established_at,'observed_by':'native control driver'}

def desktop_activity(self,step):
    op=step["op"];p=self.page;b=self.backend
    identifier=step.get('entity','legacy-0')
    item=self.entities.items[identifier]
    self.entities.configure_app(identifier,{str(item['index']):{'title':step['title']}})
    until(lambda:self.entities.observe(identifier)['window']['title']==step['title'])
    value=self.entities.interact({'entity':identifier,'action':'fill','text':step['text']})
    window=self.entities.observe(identifier)['window']
    if step.get('expect_text') and step['expect_text'] not in value['input_text']:raise AssertionError('Native fixture edit did not contain expected text')
    established_at=time.time()
    b.core.capture()
    self.execute({'op':'report.drain'})
    return {**window,'ui_text':value['input_text'],'established_at':established_at,'observed_by':'native control driver'}

def desktop_fixture_alive(self,step):
    op=step["op"];p=self.page;b=self.backend
    import psutil
    pid = self.entities.items[step.get('entity','legacy-0')]['pid']
    return psutil.pid_exists(pid)

def registry(scenario):
    from dsh_test_harness.entities import Entities
    entities=Entities(scenario)
    scenario.entities=entities
    return {
    'fixture.process':entities.process_action,
    'fixture.page':entities.current_page,
    'fixture.browser_inventory':entities.browser_inventory,
    'fixture.watch_input':entities.watch_input,
    'fixture.browser_state':entities.browser_state,
    'fixture.app':entities.app,
    'fixture.configure':entities.configure,
    'fixture.browser':entities.browser,
    'fixture.extension':entities.extension,
    'fixture.browser_restart':entities.browser_restart,
    'fixture.window':entities.window_action,
    'fixture.interact':entities.interact,
    'fixture.wait':entities.wait_observed,
    'fixture.observe':lambda step:entities.observe(step['entity']),
    'file.write': lambda step: file_write(scenario,step),
    'file.exists': lambda step: file_exists(scenario,step),
    'fault.python_dependency':lambda step:python_dependency(scenario,step),
    'desktop.browser': lambda step: desktop_browser(scenario,step),
    'desktop.notepad': lambda step: desktop_notepad(scenario,step),
    'desktop.activity': lambda step: desktop_activity(scenario,step),
    'desktop.fixture_alive': lambda step: desktop_fixture_alive(scenario,step),
}
