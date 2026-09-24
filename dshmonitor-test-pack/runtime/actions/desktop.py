"""desktop scenario actions; expectations are supplied by JSON."""
import json,os,re,time,socket,http.client,shutil,subprocess,sys,tempfile,threading
from pathlib import Path
from urllib.parse import urlparse
from dsh_test_harness.desktop import Desktop
from dsh_test_harness.wait import until
from ui import *
PACK=Path(__file__).resolve().parents[2];ROOT=PACK.parent

def inject_input():
    from json_case import inject_input as inject
    return inject()

def desktop_input(self,step):
    op=step["op"];p=self.page;b=self.backend
    inject_input()
    return {'injected': True}

def desktop_keys(self,step):
    from dsh_test_harness.vm.input import request
    return request('keys',keys=step['keys'])

def desktop_snapshot(self,step):
    facts=self.entities.snapshot()
    if 'entity' in step:
        pid=self.entities.items[step['entity']]['pid']
        facts['windows']=[window for window in facts['windows'] if window['pid']==pid]
    return facts

def desktop_wait_window(self,step):
    return until(lambda:next((window for window in desktop_snapshot(self,step)['windows']
        if all(window.get(key)==value for key,value in step['match'].items())),None),step.get('timeout',10))

def desktop_popup_position(self,step):
    pid=step['pid']
    window=until(lambda:next((w for w in self.entities.snapshot()['windows'] if w['pid']==pid and w['title']=='大肥鱼监工提醒'),None),10)
    x,y,width,height=window['rect']
    if os.name=='nt':
        import win32api
        from dsh_test_harness.vm.input import request
        screen=[win32api.GetSystemMetrics(0),win32api.GetSystemMetrics(1)]
        target_x=screen[0]-width-5 if step.get('side')=='right' else 5
        request('drag',point=[x+width//2,y+26],destination=[target_x+width//2,y+26])
    else:
        from dsh_test_harness.gnome import call
        screen=call('snapshot')['screen'];target_x=screen[0]-width-5 if step.get('side')=='right' else 5
        call('layout',{'window_id':window['id'],'rect':[target_x,y,width,height]})
    return until(lambda:next((w for w in self.entities.snapshot()['windows'] if w['id']==window['id'] and abs(w['rect'][0]-target_x)<5),None),5)

def desktop_popup_click(self,step):
    op=step["op"];p=self.page;b=self.backend
    pid=step.get('pid') or b.last_notification_pid
    self.popup_previous_request=((self.plugin_state() or {}).get('focus_request') or {}).get('id') if step.get('state_probe',True) and not hasattr(self,'closed_page_token') else None
    self.popup_click_started=time.monotonic()
    if step.get('observe_page',True) and not p.is_closed():
        p.evaluate("""()=>{
            globalThis.__DSH_TEST_TITLE_OBSERVER__?.disconnect();
            const ids=new WeakMap();let next=0;
            const rows=[];globalThis.__DSH_TEST_TITLE_LOG__=rows;
            const record=()=>rows.push({at:Date.now(),title:document.title,
                nodes:[...document.querySelectorAll('title')].map(node=>{
                    if(!ids.has(node))ids.set(node,++next);
                    return {id:ids.get(node),text:node.textContent};})});
            record();
            const observer=new MutationObserver(changes=>{
                if(changes.some(c=>c.target.nodeName==='TITLE'||c.target.parentNode?.nodeName==='TITLE'||
                    [...c.addedNodes,...c.removedNodes].some(n=>n.nodeName==='TITLE')))record();
            });
            observer.observe(document.head,{subtree:true,childList:true,characterData:true});
            globalThis.__DSH_TEST_TITLE_OBSERVER__=observer;
        }""")
    python=str(Path(sys.executable).with_name('python.exe')) if sys.platform=='win32' else sys.executable
    if getattr(b,'browser_endpoint',None):
        b.start_process([python,str(ROOT/'test-support/desktop_trace.py'),str(self.out/(step['id']+'-desktop-trace.jsonl')),str(step.get('observation_seconds',12)),b.browser_endpoint])
    argv = [python, str(PACK / 'runtime/click_popup.py'), str(pid)]
    point = getattr(b, 'last_popup_button', None)
    if isinstance(point, list) and len(point) == 2:
        argv += ['click', str(int(point[0])), str(int(point[1]))]
    result=subprocess.run(argv, capture_output=True, env=getattr(b, 'notification_env', None), timeout=40, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    (self.out/(step['id']+'-popup-click.log')).write_bytes(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('Native popup click failed: '+(result.stdout+result.stderr).decode('utf-8','replace')[-2000:])
    observations=[]
    def closed():
        windows=self.entities.snapshot()['windows']
        observations.append({'elapsed_seconds':round(time.monotonic()-self.popup_click_started,3),
                             'page_title':None if not step.get('observe_page',True) or p.is_closed() else p.title(),
                             'windows':[{k:w.get(k) for k in ('id','pid','title','focused')} for w in windows]})
        (self.out/(step['id']+'-popup-observations.json')).write_text(json.dumps(observations,ensure_ascii=False),encoding='utf-8')
        return not any(w['pid']==pid for w in windows)
    if step.get('wait_closed',True):
        try:until(closed,step.get('timeout',10))
        except TimeoutError:
            observed={'windows':self.entities.snapshot()['windows'],'focus_request':(self.plugin_state() or {}).get('focus_request')}
            (self.out/(step['id']+'-popup-timeout.json')).write_text(json.dumps(observed,ensure_ascii=False),encoding='utf-8')
            raise
    return {'clicked': True, 'popup_closed': closed()}

def desktop_popup_key(self,step):
    op=step["op"];p=self.page;b=self.backend
    pid=b.last_notification_pid
    subprocess.run([sys.executable, str(PACK / 'runtime/click_popup.py'), str(pid), 'keys'], check=True, env=getattr(b, 'notification_env', None), timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    import psutil
    time.sleep(1.5)
    return {'keys_sent': True, 'popup_still_open': psutil.pid_exists(pid)}

def desktop_find_window(self,step):
    op=step["op"];p=self.page;b=self.backend
    sample = {'desktop':self.entities.snapshot()}
    window = next((w for w in sample['desktop']['windows'] if step['title'] in (w.get('title') or '')), None)
    if not window:
        raise AssertionError('桌面上找不到标题包含「' + step['title'] + '」的窗口')
    return {'id': window.get('id'), 'title': window.get('title', ''), 'app': window.get('app', ''), 'focused': bool(window.get('focused'))}

def desktop_focused_title(self,step):
    op=step["op"];p=self.page;b=self.backend
    sample = {'desktop':self.entities.snapshot()}
    window = next((w for w in sample['desktop']['windows'] if w.get('focused')), None)
    return {'id': (window or {}).get('id'), 'title': (window or {}).get('title', ''), 'app': (window or {}).get('app', ''), 'present': bool(window)}

def desktop_capture(self,step):
    op=step["op"];p=self.page;b=self.backend
    return {'desktop':self.entities.snapshot()}

def desktop_popup(self,step):
    picture = self.out / (step['id'] + '.png')
    backend=self.backend
    # Observe the actual notifier by PID, independently of the sampler being tested.
    result = subprocess.run([sys.executable,str(PACK/'runtime/capture_popup.py'),
                             str(step.get('pid') or backend.last_notification_pid),str(picture)],
                            env=getattr(backend,'notification_env',None),capture_output=True,text=True,
                            timeout=8,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError(result.stderr)
    return json.loads(result.stdout)

def native_dialog(self,step):
    import uuid
    if step.get('entity'):
        pid=self.entities.items[step['entity']]['pid']
    else:
        session=self.page.context.browser.new_browser_cdp_session()
        try:pid=int(next(p['id'] for p in session.send('SystemInfo.getProcessInfo')['processInfo'] if p['type']=='browser'))
        finally:session.detach()
    try:
        window=until(lambda:next((w for w in self.entities.snapshot()['windows'] if w['pid']==pid and w['title']==step['title']),None),step.get('timeout',5))
    except TimeoutError:
        if step.get('optional'):return {'present':False,'pid':pid,'title':step['title']}
        raise
    key='dialog-'+uuid.uuid4().hex
    self.entities.items[key]={'window_id':window['id'],'pid':pid}
    try:
        result=self.entities.interact({'entity':key,'action':'click','control':{'title':step['button'],'control_type':'Button'},'name':step['button'],'role':'button'})
        if step.get('menu_item'):
            from pywinauto import Desktop as Native
            def menu_item():
                return next((item for root in Native(backend='uia').windows(process=pid)
                             for item in root.descendants(control_type='MenuItem')
                             if item.window_text()==step['menu_item']),None)
            until(menu_item,5).click_input()
        until(lambda:not any(w['id']==window['id'] for w in self.entities.snapshot()['windows']),5)
        return {'present':True,'clicked':step['button'],'menu_item':step.get('menu_item'),'closed':True,'window':window,'interaction':result}
    finally:self.entities.items.pop(key,None)

def native_authorize(self,step):
    if os.name=='nt':
        from dsh_test_harness.vm.input import request
        return request('authorize',timeout=120,accept=step.get('accept',True))
    # This credential belongs only to the disposable Linux guest account.
    started=int(time.time())
    from dsh_test_harness.gnome import call
    shell_pid=int(subprocess.check_output(['pgrep','-u',str(os.getuid()),'-x','gnome-shell'],text=True).strip())
    def password_control():
        result=subprocess.run([sys._base_executable,str(ROOT/'test-support/dsh_test_harness/native_control.py')],input=json.dumps({'pid':shell_pid,'op':'probe','role':'password text'}),capture_output=True,text=True,timeout=12)
        (self.out/'authorization-control.log').write_text(result.stdout+result.stderr,encoding='utf-8')
        return json.loads(result.stdout) if result.returncode==0 else None
    control=until(password_control,30)
    if not step.get('accept',True):
        call('keys',{'keys':['Escape']})
        until(lambda:not password_control(),10)
        return {'authorization_input_sent':True,'authenticated':False,'native_control':control}
    password=os.environ['DSH_TEST_ADMIN_PASSWORD']
    for character in password:
        call('keys',{'keys':[character]});time.sleep(.04)
    call('keys',{'keys':['Return']})
    def authenticated():
        evidence=subprocess.check_output(['sudo','journalctl','-u','polkit','--since','@'+str(started),'--no-pager'],text=True)
        (self.out/'polkit-authorization.log').write_text(evidence,encoding='utf-8')
        return 'successfully authenticated' in evidence
    until(authenticated,30)
    return {'authorization_input_sent':True,'authenticated':True,'native_control':control}

def extension_state(self,step):
    uuid='focus-demo@local.demo'
    def set_enabled(enabled):subprocess.run(['gnome-extensions','enable' if enabled else 'disable',uuid],check=True,capture_output=True)
    set_enabled(step['enabled'])
    if not step['enabled']:self.backend.cleanup_callbacks.append(lambda:set_enabled(True))
    return {'enabled':step['enabled']}

def workspace(self,step):
    if os.name=='nt':
        from pyvda import VirtualDesktop,AppView
        original=VirtualDesktop.current();destination=VirtualDesktop.create()
        self.backend.cleanup_callbacks.append(lambda:(original.go(),destination.remove(original)))
        for entity in step['entities']:AppView(int(self.entities.items[entity]['window_id'].split(':')[1])).move(destination)
        return {'original':str(original.id),'target':str(destination.id),'current':str(VirtualDesktop.current().id)}
    from dsh_test_harness.gnome import call
    state=call('snapshot');original=state['active_workspace'];destination=state['workspace_count']-1
    if destination==original:raise RuntimeError('No empty workspace available in GNOME dynamic workspace setup')
    self.backend.cleanup_callbacks.append(lambda:call('workspace-switch',{'workspace':original}))
    for entity in step['entities']:call('workspace-move',{'window_id':self.entities.items[entity]['window_id'],'workspace':destination})
    return {'original':original,'target':destination,'current':call('snapshot')['active_workspace']}

def hide_browser_connection(self,step):
    # Real dependency failure: the test keeps its already-open WebSocket, while
    # new consumers cannot discover the ephemeral browser endpoint anymore.
    path=(Path(self.entities.items[step['entity']]['profile']) if step.get('entity') else self.backend.browser_profile)/'DevToolsActivePort'
    existed=path.exists();path.unlink()
    return {'discovery_file_removed':existed,'browser_still_connected':self.page.context.browser.is_connected()}

def browser_close_page(self,step):
    self.closed_page_origin=self.page.url.split('/')[0]+'//'+self.page.url.split('/')[2]
    self.closed_page_token=self.page.evaluate('globalThis.__DAFEIYU__?.token')
    self.closed_page_context=self.page.context
    self.page.close()
    return {'closed':self.page.is_closed(),'browser_alive':self.closed_page_context.browser.is_connected()}

def browser_exit(self,step):
    import psutil
    self.closed_page_origin=self.page.url.split('/')[0]+'//'+self.page.url.split('/')[2]
    self.closed_page_token=self.page.evaluate('globalThis.__DAFEIYU__?.token')
    from dsh_test_harness.entities import Entities
    self.closed_browser_windows=Entities(None).snapshot()['windows']
    session=self.page.context.browser.new_browser_cdp_session()
    processes=session.send('SystemInfo.getProcessInfo')['processInfo']
    pid=next(p['id'] for p in processes if p['type']=='browser')
    self.closed_browser_pid=pid
    session.send('Browser.close')
    def exited():
        try:return psutil.Process(pid).status()==psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:return True
    until(exited,20)
    return {'pid':pid,'alive':False,'windows_before':self.closed_browser_windows}

def browser_reopened(self,step):
    from dsh_test_harness.entities import Entities
    from dsh_test_harness.native_text import read_window
    before={w['id'] for w in self.closed_browser_windows}
    def observed():
        snapshot=Entities(None).snapshot()
        (self.out/'reopened-desktop.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
        windows=[w for w in snapshot['windows'] if w['id'] not in before and 'DeepSeek Harness' in w.get('title','')]
        if not windows:return None
        self.backend.reopened_windows=windows
        rows=[{**w,'ui_text':read_window(w)} for w in windows]
        (self.out/'reopened-browser.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        if any(step['text'] in r['ui_text'] for r in rows):return {'windows':rows,'session_text_found':True}
    return until(observed,step.get('timeout',45))

def accessibility_inventory(self,step):
    """Observe native and accessibility identities without moving or focusing windows."""
    windows=self.entities.snapshot()['windows']
    pids={v['pid'] for v in self.entities.items.values() if v.get('pid')}
    windows=[w for w in windows if w.get('pid') in pids]
    if os.name=='nt':
        from pywinauto import Desktop as UIADesktop
        return {'windows':windows,'roots':[{'pid':w.process_id(),'handle':w.handle,'rect':[w.rectangle().left,w.rectangle().top,w.rectangle().right,w.rectangle().bottom]} for w in UIADesktop(backend='uia').windows() if w.process_id() in pids]}
    from focus_demo.atspi_dbus import Bus,ROOT,ACCESSIBLE
    bus=Bus(seconds=5);roots=[];errors=[]
    try:
        for owner in bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames'):
            if not owner.startswith(':'):continue
            try:
                pid=bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID','s',owner)
                if pid not in pids:continue
                for name,path in bus.call(owner,ROOT,ACCESSIBLE,'GetChildren'):
                    row={'pid':pid,'bus':name,'path':path}
                    for key,interface,method,signature,args in [
                        ('rect','org.a11y.atspi.Component','GetExtents','u',(0,)),
                        ('z_order','org.a11y.atspi.Component','GetMDIZOrder','',()),
                        ('properties','org.freedesktop.DBus.Properties','GetAll','s',(ACCESSIBLE,)),
                        ('attributes',ACCESSIBLE,'GetAttributes','',()),
                        ('state',ACCESSIBLE,'GetState','',())]:
                        try:row[key]=bus.call(name,path,interface,method,signature,*args)
                        except RuntimeError as error:row[key]={'error':str(error)}
                    roots.append(row)
            except RuntimeError as error:errors.append(str(error))
    finally:bus.close()
    return {'windows':windows,'roots':roots,'errors':errors}

def registry(scenario):return {
    'desktop.keys':lambda step:desktop_keys(scenario,step),
    'desktop.snapshot':lambda step:desktop_snapshot(scenario,step),
    'desktop.wait_window':lambda step:desktop_wait_window(scenario,step),
    'native.accessibility_inventory':lambda step:accessibility_inventory(scenario,step),
    'desktop.popup_position':lambda step:desktop_popup_position(scenario,step),
    'desktop.browser_close_page':lambda step:browser_close_page(scenario,step),
    'desktop.extension':lambda step:extension_state(scenario,step),
    'desktop.workspace':lambda step:workspace(scenario,step),
    'desktop.hide_browser_connection':lambda step:hide_browser_connection(scenario,step),
    'desktop.browser_exit':lambda step:browser_exit(scenario,step),
    'desktop.browser_reopened':lambda step:browser_reopened(scenario,step),
    'native.dialog':lambda step:native_dialog(scenario,step),
    'native.authorize':lambda step:native_authorize(scenario,step),
    'desktop.input': lambda step: desktop_input(scenario,step),
    'desktop.popup_click': lambda step: desktop_popup_click(scenario,step),
    'desktop.popup_key': lambda step: desktop_popup_key(scenario,step),
    'desktop.find_window': lambda step: desktop_find_window(scenario,step),
    'desktop.focused_title': lambda step: desktop_focused_title(scenario,step),
    'desktop.capture': lambda step: desktop_capture(scenario,step),
    'desktop.popup': lambda step: desktop_popup(scenario,step),
}
