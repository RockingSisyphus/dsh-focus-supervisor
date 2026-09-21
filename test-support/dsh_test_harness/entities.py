"""Real application and browser fixtures with scenario-local identity mapping."""
import json,os,subprocess,sys,time,uuid
from pathlib import Path
from .desktop import Desktop
from .wait import until

class Entities:
    def __init__(self,scenario):
        self.scenario=scenario;self.items={};self.desktop=Desktop();self.last_browser=None
    def snapshot(self):
        if os.name!='nt':
            from .gnome import call
            return call('snapshot')
        import win32gui,win32process
        windows=[];foreground=win32gui.GetForegroundWindow()
        def visit(hwnd,_):
            if win32gui.IsWindowVisible(hwnd):
                x,y,r,b=win32gui.GetWindowRect(hwnd)
                windows.append({'id':'win:'+str(hwnd),'pid':win32process.GetWindowThreadProcessId(hwnd)[1], 'title':win32gui.GetWindowText(hwnd),'class_name':win32gui.GetClassName(hwnd),'rect':[x,y,r-x,b-y],'focused':foreground==hwnd,'minimized':bool(win32gui.IsIconic(hwnd)),'mapped':not bool(win32gui.IsIconic(hwnd))})
        win32gui.EnumWindows(visit,None)
        return {'backend':'windows','windows':windows,'foreground_handle':foreground}
    def observe(self,identifier):
        item=self.items[identifier]
        w=next((w for w in self.snapshot()['windows'] if w['id']==item['window_id']),None)
        value={'entity':identifier,'window_id':item['window_id'],'present':bool(w),'window':w}
        if item.get('children') is not None:value['alive_children']=[c.pid for c in item['children'] if c.is_running() and c.status()!='zombie']
        if item.get('page'):
            page=item['page'];value.update(tab_closed=page.is_closed(),tab_id=item['tab_id'],browser_window_id=item['browser_window_id'])
            if not page.is_closed():
                try:value.update(title=page.title(),url=page.url,visibility=page.evaluate('document.visibilityState'))
                except Exception:
                    if not page.is_closed():raise
            value['tab_closed']=page.is_closed()
        return value
    def wait_observed(self,step):
        deadline=time.monotonic()+step.get('timeout',10)
        while True:
            value=self.observe(step['entity'])
            def field(path):
                item=value
                for key in path.split('.'):
                    item=item.get(key) if isinstance(item,dict) else None
                return item
            matched=all(field(k)==v for k,v in step['expected'].items())
            if matched or time.monotonic()>=deadline:return {**value,'matched':matched}
            time.sleep(.1)

    def app(self,step):
        spec={'log_text':step.get('log_text'), 'windows':step['windows'],'refuse_close':step.get('refuse_close',False),'close_behavior':step.get('close_behavior'),'child_processes':step.get('child_processes',0)}
        marker=uuid.uuid4().hex[:10]
        import copy
        spec=copy.deepcopy(spec)
        for i,row in enumerate(spec['windows']):row['title']=f'DSH fixture {marker} {i}'
        root=self.scenario.out/('fixture-'+step['entity']);root.mkdir()
        config=root/'gui.json';config.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
        ready=root/'ready';env={**os.environ,'DSH_TEST_GUI_READY':str(ready)}
        process=self.scenario.backend.start_process([self.desktop.python(),str(Path(__file__).resolve().parents[1]/'fixtures/gui.py'),str(config)],env=env)
        def ready_or_exited():
            if process.poll() is not None:raise RuntimeError('Native fixture exited before becoming ready; see process log')
            return ready.exists()
        until(ready_or_exited)
        endpoint=json.loads(ready.read_text());native_pid=endpoint['pid']
        import psutil
        children=[psutil.Process(pid) for pid in json.loads((root/'children.json').read_text())] if (root/'children.json').exists() else []
        def cleanup_children():
            for child in children:
                try:
                    if child.is_running():child.kill()
                except psutil.NoSuchProcess:pass
        self.scenario.backend.cleanup_callbacks.append(cleanup_children)
        created={}
        for i,row in enumerate(step['windows']):
            title=spec['windows'][i]['title']
            win=until(lambda:next((w for w in self.snapshot()['windows'] if w['pid']==native_pid and w['title']==title),None))
            if os.name!='nt' and win.get('client_type')!='wayland':raise RuntimeError('Native fixture is not a Wayland client')
            key=row['id'];self.items[key]={'window_id':win['id'],'pid':native_pid,'root':root,'command_port':endpoint['port'],'index':i,'process':process,'native_name':row['id'],'children':children}
            created[key]=self.observe(key)
        # Only the fixture's initial content/title is prepared through its data channel.
        self.configure_app(step['windows'][0]['id'],{str(i):{'title':row['title']} for i,row in enumerate(step['windows'])})
        for row in step['windows']:until(lambda: (w if (w:=self.observe(row['id']))['window']['title']==row['title'] else None))
        for row in step['windows']:
            if 'rect' in row:self.window_action({'entity':row['id'],'action':'layout','rect':row['rect']})
        return {k:self.observe(k) for k in created}
    def configure_app(self,identifier,windows):
        import socket
        with socket.create_connection(('127.0.0.1',self.items[identifier]['command_port']),timeout=5) as channel:
            channel.sendall((json.dumps({'windows':windows},ensure_ascii=False)+'\n').encode())
            json.loads(channel.makefile('rb').readline())

    def configure(self,step):
        item=self.items[step['entity']]
        self.configure_app(step['entity'],{str(item['index']):{'title':step['title']}})
        return self.observe(step['entity'])

    def browser(self,step):
        context=self.scenario.page.context
        if step.get('native_only'):
            import psutil
            root=self.scenario.out/('browser-'+step['entity']);root.mkdir()
            html=root/'page.html';html.write_text(step['html'],encoding='utf-8')
            probe=context.browser.new_browser_cdp_session()
            pid=int(next(p['id'] for p in probe.send('SystemInfo.getProcessInfo')['processInfo'] if p['type']=='browser'));probe.detach()
            argv=self.desktop.browser_arguments(psutil.Process(pid).exe(),root)+['--new-window']
            process=self.scenario.backend.start_process([*argv,html.as_uri()])
            def located():
                pids=[]
                for proc in psutil.process_iter(['pid','cmdline']):
                    args=proc.info['cmdline'] or []
                    if '--user-data-dir='+str(root) in args and not any(a.startswith('--type=') for a in args):pids.append(proc.pid)
                return next((w for w in self.snapshot()['windows'] if w['pid'] in pids and step['title'] in w['title']),None)
            window=until(located,20)
            self.items[step['entity']]={'window_id':window['id'],'pid':window['pid'],'profile':str(root),'process':process}
            return {**self.observe(step['entity']),'remote_debugging':False}
        if step.get('instance'):
            context=self.items[step['instance']]['page'].context
        elif step.get('separate_instance'):
            import psutil
            root=self.scenario.out/('browser-'+step['entity']);root.mkdir()
            probe=context.browser.new_browser_cdp_session()
            pid=int(next(p['id'] for p in probe.send('SystemInfo.getProcessInfo')['processInfo'] if p['type']=='browser'));probe.detach()
            executable=psutil.Process(pid).exe()
            argv=self.desktop.browser_arguments(executable,root)+['--remote-debugging-port=0']
            process=self.scenario.backend.start_process(argv)
            port_file=root/'DevToolsActivePort'
            def published_port():
                # Windows can expose the filename while Chrome still holds the
                # initial write handle exclusively. Wait for readable contents.
                try:lines=port_file.read_text().splitlines()
                except (FileNotFoundError,PermissionError):return None
                return lines[0] if lines and lines[0].isdigit() else None
            port=until(published_port)
            browser=context.browser.browser_type.connect_over_cdp('http://127.0.0.1:'+port,no_defaults=True)
            context=browser.contexts[0]
        if step.get('new_window',True):
            session=context.browser.new_browser_cdp_session()
            with context.expect_page() as pending:
                target=session.send('Target.createTarget',{'url':'about:blank','newWindow':True})
            page=pending.value;session.detach()
        else:
            parent=step.get('window') or self.last_browser
            if not parent:raise ValueError('A new tab needs an existing logical browser window')
            self.items[parent]['page'].bring_to_front()
            self.desktop.activate(self.observe(parent)['window'])
            session=context.browser.new_browser_cdp_session()
            with context.expect_page() as pending:
                session.send('Target.createTarget',{'url':'about:blank','newWindow':False})
            page=pending.value;session.detach()
        marker='DSH fixture '+uuid.uuid4().hex
        page.set_content('<title>'+marker+'</title>')
        page.bring_to_front()
        window=until(lambda:next((w for w in self.snapshot()['windows'] if marker in w['title']),None))
        session=context.new_cdp_session(page)
        target_info=session.send('Target.getTargetInfo')['targetInfo']
        browser_window=session.send('Browser.getWindowForTarget',{'targetId':target_info['targetId']})['windowId']
        session.detach()
        self.items[step['entity']]={'window_id':window['id'],'page':page,'pid':window['pid'],'tab_id':target_info['targetId'],'browser_window_id':browser_window,'profile':str(root) if step.get('separate_instance') else None}
        self.last_browser=step['entity']
        if 'url' in step:page.goto(step['url'])
        elif 'html' in step:page.set_content(step['html'])
        return self.observe(step['entity'])
    def extension(self,step):
        from .browser_extension import load
        page=self.items[step['entity']]['page']
        directory=Path(step['directory'])
        target=self.scenario.out/step['id'];target.mkdir()
        load(page.context,directory,target,name=step['name'])
        return {'directory':str(directory),'name':step['name'],'loaded_through_ui':True}

    def browser_restart(self,step):
        """Restart an owned fixture profile, optionally without an automation port."""
        import psutil
        item=self.items[step['entity']]
        if not item.get('profile'):raise ValueError('Restart requires a separate fixture browser profile')
        process=psutil.Process(item['pid']);executable=process.exe()
        page=item['page'];url=step.get('url') or page.url;title=page.title()
        session=page.context.browser.new_browser_cdp_session()
        session.send('Browser.close')
        _,alive=psutil.wait_procs([process],timeout=10)
        if alive:raise TimeoutError('Fixture browser did not exit')
        argv=self.desktop.browser_arguments(executable,Path(item['profile']))
        if step.get('remote_debugging',False):raise ValueError('Use fixture.browser for a connected instance')
        started=self.scenario.backend.start_process([*argv,url])
        def located():
            pids=[]
            for candidate in psutil.process_iter(['pid','cmdline']):
                args=candidate.info['cmdline'] or []
                if '--user-data-dir='+item['profile'] in args and not any(a.startswith('--type=') for a in args):pids.append(candidate.pid)
            return next((w for w in self.snapshot()['windows'] if w['pid'] in pids and title in w['title']),None)
        window=until(located,20)
        self.items[step['entity']]={'window_id':window['id'],'pid':window['pid'],'profile':item['profile'],'process':started}
        arguments=psutil.Process(window['pid']).cmdline()
        return {**self.observe(step['entity']),'remote_debugging':any(a.startswith('--remote-debugging') for a in arguments),
                'force_renderer_accessibility':any(a.startswith('--force-renderer-accessibility') for a in arguments)}

    def current_page(self,step):
        page=self.scenario.page
        browser_session=page.context.browser.new_browser_cdp_session()
        browser_pid=int(next(p['id'] for p in browser_session.send('SystemInfo.getProcessInfo')['processInfo'] if p['type']=='browser'))
        browser_session.detach()
        owned=[w for w in self.snapshot()['windows'] if w['pid']==browser_pid]
        if len(owned)==1:window=owned[0]
        else:
            title=page.title();marker='DSH identity '+uuid.uuid4().hex
            page.evaluate('(title)=>document.title=title',marker)
            try:window=until(lambda:next((w for w in self.snapshot()['windows'] if w['pid']==browser_pid and marker in w['title']),None))
            finally:page.evaluate('(title)=>document.title=title',title)
        session=page.context.new_cdp_session(page)
        info=session.send('Target.getTargetInfo')['targetInfo']
        browser_window=session.send('Browser.getWindowForTarget',{'targetId':info['targetId']})['windowId'];session.detach()
        self.items[step['entity']]={'window_id':window['id'],'pid':window['pid'],'page':page,'tab_id':info['targetId'],'browser_window_id':browser_window,'profile':str(root) if step.get('separate_instance') else None}
        return self.observe(step['entity'])

    def process_action(self,step):
        import psutil
        process=psutil.Process(self.items[step['entity']]['pid'])
        action=step['action']
        if action=='suspend':process.suspend()
        elif action=='resume':process.resume()
        else:raise ValueError('Unknown fixture process action '+action)
        return {'pid':process.pid,'action':action,'status':process.status()}

    def window_action(self,step):
        identifier=step['entity'];operation=step['action']
        if operation=='activate' and self.items[identifier].get('page'):self.items[identifier]['page'].bring_to_front()
        window=self.observe(identifier)['window']
        if operation not in ('activate','minimize','restore','layout','close'):raise ValueError('Unknown fixture window action '+operation)
        if os.name!='nt':
            from .gnome import action
            action(operation,window,**({'rect':step['rect']} if operation=='layout' else {}))
        else:
            import win32gui,win32con
            hwnd=int(window['id'].split(':')[1])
            if operation=='activate':self.desktop.activate(window)
            elif operation=='minimize':win32gui.ShowWindow(hwnd,win32con.SW_MINIMIZE)
            elif operation=='restore':win32gui.ShowWindow(hwnd,win32con.SW_RESTORE)
            elif operation=='layout':win32gui.ShowWindow(hwnd,win32con.SW_RESTORE);win32gui.MoveWindow(hwnd,*step['rect'],True)
            elif operation=='close':win32gui.PostMessage(hwnd,win32con.WM_CLOSE,0,0)
        def observed():
            result=self.observe(identifier);w=result['window']
            ok=(not w) if operation=='close' else bool(w) and (w['focused'] if operation=='activate' else w['minimized'] if operation=='minimize' else not w['minimized'] if operation=='restore' else all(abs(a-b)<=2 for a,b in zip(w['rect'],step['rect'])))
            return result if ok else None
        try:return {**until(observed,step.get('timeout',10)),'observed_at':time.time()}
        except TimeoutError as error:
            raise TimeoutError(f"{operation} did not reach requested state {step.get('rect')}; observed {self.observe(identifier)}") from error
    def browser_inventory(self,step):
        """Count actual browser windows containing tabs, separately from native dialogs."""
        context=self.scenario.page.context
        if step.get('entity'):context=self.items[step['entity']]['page'].context
        rows=[]
        for page in context.pages:
            session=context.new_cdp_session(page)
            try:
                target=session.send('Target.getTargetInfo')['targetInfo']
                window=session.send('Browser.getWindowForTarget',{'targetId':target['targetId']})
                rows.append({'tab_id':target['targetId'],'window_id':window['windowId'],'bounds':window.get('bounds',{}),'title':target.get('title',''),'url':target.get('url','').split('?')[0]})
            finally:session.detach()
        return {'total':len(rows),'window_count':len({r['window_id'] for r in rows}),'tabs':rows}

    def browser_state(self,step):
        item=self.items[step['entity']];rows=[]
        for page in item['page'].context.pages:
            session=page.context.new_cdp_session(page)
            try:
                target=session.send('Target.getTargetInfo')['targetInfo']['targetId']
                window=session.send('Browser.getWindowForTarget',{'targetId':target})['windowId']
                if window==item['browser_window_id']:rows.append({'tab_id':target,'visibility':page.evaluate('document.visibilityState'),'title':page.title()})
            finally:session.detach()
        native=self.observe(step['entity'])['window']
        visible=[r for r in rows if r['visibility']=='visible']
        titled=[r for r in rows if native and native['title'].startswith(r['title'])]
        candidates=visible if len(visible)==1 else titled
        known=len(candidates)==1
        selected=candidates[0]['tab_id'] if known else None
        for row in rows:row['selected']=row['tab_id']==selected if known else None
        return {'tabs':rows,'count':len(rows),'selected':[selected] if known else [],'selection_known':known,'selection_source':'visible-page' if len(visible)==1 else 'unique-selected-window-title' if known else 'unavailable','window':native}

    def watch_input(self,step):
        identifier=step['entity'];samples=[];started=time.monotonic();next_input=0;index=0
        chunks=step.get('chunks',[])
        while time.monotonic()-started<step['seconds']:
            elapsed=time.monotonic()-started
            state=self.snapshot();focused=next((w['id'] for w in state['windows'] if w['focused']),None)
            samples.append({'at':elapsed,'focused':focused})
            if index<len(chunks) and elapsed>=next_input:
                if os.name=='nt':
                    from pywinauto.keyboard import send_keys
                    send_keys(chunks[index],with_spaces=True,pause=.03)
                else:
                    from .gnome import call
                    for char in chunks[index]:call('keys',{'keys':[ord(char)]})
                index+=1;next_input=index*step['seconds']/max(1,len(chunks))
            time.sleep(.1)
        (self.scenario.out/(step['id']+'-focus.json')).write_text(json.dumps(samples),encoding='utf-8')
        retained=all(s['focused']==self.items[identifier]['window_id'] for s in samples)
        # Reading a control must never repair the focus being measured.
        value=self.interact({'entity':identifier,'action':'read','activate':False}) if retained else {}
        return {'focus_retained':retained,'samples':len(samples),'input_text':value.get('input_text'),'chunks_sent':index}

    def interact(self,step):
        item=self.items[step['entity']];operation=step['action']
        if 'page' in item:
            page=item['page']
            if operation=='select':page.bring_to_front();return until(lambda:self.observe(step['entity']) if page.evaluate('document.visibilityState')=='visible' else None)
            if operation=='navigate':page.goto(step['url'])
            elif operation=='fill':page.locator(step['selector']).fill(step['text'])
            elif operation=='click':page.locator(step['selector']).click()
            elif operation=='scroll':page.mouse.wheel(0,step['dy'])
            elif operation=='beforeunload_probe':
                page.locator(step.get('selector','input')).click()
                with page.expect_event('dialog',timeout=5000) as pending:page.evaluate('setTimeout(()=>location.reload(),0)')
                dialog=pending.value
                value={'type':dialog.type,'message':dialog.message}
                dialog.dismiss()
                return value
            return self.observe(step['entity'])
        # This is an explicit user switch. Reveal the requested window before
        # clicking its control; otherwise an overlapping browser receives the click.
        if step.get('activate',True):self.desktop.activate(self.observe(step['entity'])['window'])
        if os.name=='nt':
            from pywinauto import Desktop as Native
            window=Native(backend='uia').window(handle=int(item['window_id'].split(':')[1]))
            control=window.child_window(**step.get('control',{'control_type':'Edit','found_index':0}))
            if operation=='fill':control.set_edit_text(step['text'])
            elif operation=='click':control.click_input()
            elif operation=='focus':
                from .vm.input import request
                import win32gui
                rectangle=control.rectangle()
                request('click',point=[(rectangle.left+rectangle.right)//2,(rectangle.top+rectangle.bottom)//2])
                until(lambda:win32gui.GetForegroundWindow()==int(item['window_id'].split(':')[1]) and control.has_keyboard_focus(),5)
            elif operation!='read':raise ValueError('Unknown native control action '+operation)
            interaction={'input_text':control.get_value()} if operation in ('fill','read') else {}
        else:
            request={'pid':item['pid'],'op':operation,'active_window':True,'role':step.get('role','text'),'name':step.get('name'),'text':step.get('text','')}
            result=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('native_control.py'))],input=json.dumps(request),text=True,capture_output=True,timeout=12)
            if result.returncode:raise RuntimeError('Native control failed: '+result.stderr[-1500:])
            interaction=json.loads(result.stdout)
        return {**self.observe(step['entity']),**interaction}
