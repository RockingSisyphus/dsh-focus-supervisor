"""Start real DSH, real plugin/core, logged-in desktop, and fixed model transport."""
import argparse,json,os,re,signal,subprocess,sys,time,secrets,threading,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from dsh_response_lab import FixedModel
from dsh_test_harness.desktop import Desktop
from .wait import until
import importlib.util
from playwright.sync_api import sync_playwright

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--modules',type=Path,required=True)
    parser.add_argument('--browser-plugin',type=Path,default=Path.home()/'.dsh/profiles/web/node_modules/@wxg-prc-cpg/browser-skill-dsh-plugin')
    parser.add_argument('--inspect',action='store_true')
    parser.add_argument('--human-review',action='store_true')
    parser.add_argument('--human-step-delay',type=float,default=2.0)
    parser.add_argument('--test-file',type=Path,required=True)
    parser.add_argument('--case',type=Path,required=True,help='Python scenario with setup(out,start) and run(page,subject,model,project,out)')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False,mode=0o700)
    (out/'case.json').write_text(args.test_file.read_text(encoding='utf-8'), encoding='utf-8')
    modules=args.modules.resolve();session_root=Path(os.environ.get('DSH_TEST_SESSION_DIRECTORY',str(out)));home=session_root/'home';project=session_root/'project';project.mkdir(parents=True,exist_ok=True);profile=home/'profiles/web';profile.mkdir(parents=True,exist_ok=True)
    resuming=(session_root/'checkpoint.json').exists()
    processes=[];logs=[];backend=model=None;browser=None;fixture_server=None;user_data=None;default_browser=None
    original_env=os.environ.copy()
    service_host=None
    sys.path.insert(0,str(args.case.resolve().parent))
    spec=importlib.util.spec_from_file_location('dsh_case',args.case.resolve());case=importlib.util.module_from_spec(spec);spec.loader.exec_module(case)
    def start(argv,env=None,cwd=None):
        log=(out/f'process-{len(processes)}.log').open('w',encoding='utf-8');logs.append(log)
        p=subprocess.Popen(argv,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),stdout=log,stderr=log,env=env,cwd=cwd,start_new_session=True);processes.append(p);return p
    def interrupted(signum, frame):
        raise InterruptedError("Test host received termination signal")
    desktop=Desktop()
    previous_signal=signal.signal(signal.SIGTERM,interrupted)
    try:
        definition=json.loads(args.test_file.read_text(encoding='utf-8'))
        desktop.setup(out,start,visible=args.human_review,settings=definition.get('desktop_settings'),size=definition.get('desktop_size'))
        backend,case_patch=case.setup(out,start,args.test_file);model=FixedModel(out/'model')
        backend.start_process=start;backend.cleanup_callbacks=[]
        if resuming:
            saved=json.loads((session_root/'checkpoint.json').read_text(encoding='utf-8'))
            backend.original_tasks.discard(saved['task']['value']['id'])
            backend.original_settings=saved['initial_settings']
        if definition.get('live_desktop') and desktop.windows:backend.notification_env=original_env
        if definition.get('browser_skill'):
            if os.name=='nt':
                os.environ['BSK_HOME']=str(out/'bsk');os.environ['BSK_AUTO_START']='0'
                bsk=str(Path.home()/'.local/bin/bsk.exe')
                start([bsk,'daemon','start','--foreground'],env=os.environ.copy())
            case_patch.append({'id':'browserskill','config':{'bskPath':shutil.which('bsk') or str(Path.home()/'.local/bin'/('bsk.exe' if os.name=='nt' else 'bsk')),'lazyTools':True}})
        from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
        from functools import partial
        fixture_server=ThreadingHTTPServer(('127.0.0.1',0),partial(SimpleHTTPRequestHandler,directory=str(args.test_file.resolve().parent.parent/'fixtures')))
        threading.Thread(target=fixture_server.serve_forever,daemon=True).start()
        backend.fixture_url=f'http://127.0.0.1:{fixture_server.server_port}'
        # npm installs the real plugin into every isolated DSH profile.
        if not (profile/'package.json').exists():(profile/'package.json').write_text(json.dumps({'private':True,'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'],'patchReload':'live'}}}), encoding='utf-8')
        (profile/'cordis.yml').write_text('[]\n', encoding='utf-8')
        import yaml
        patch=[{'id':'session-title-llm','disabled':True},{'id':'directory-picker','disabled':True},
            {'insert':[{'name':'@deepseek-ai/dsh-host-directory-picker-browse'},{'name':'@deepseek-ai/dsh-client-ui-directory-picker-browse'}]},
            {'id':'llm-deepseek','config':{'apiKeyEnv':'DSH_TEST_KEY','baseURL':model.url,'protocol':'chat-completions','thinking':'enabled','models':[{'id':'test-model','name':'Fixed local test','inputModalities':['text','image'],'contextWindow':128000}]}},
            {'id':'agent-default-model','config':{'provider':'deepseek-official','model':'test-model','reasoningEffort':'high'}},
            *case_patch]
        if definition.get('cold_install'):patch=[x for x in patch if x not in case_patch]
        (profile/'cordis.patch.yml').write_text(yaml.safe_dump(patch,allow_unicode=True), encoding='utf-8')
        # Installation is handled once by prepare_profile for all product scenarios.
        if hasattr(case,'prepare_profile') and (definition.get('plugin_update') or (not resuming and not (profile/'node_modules/dsh-focus-supervisor/package.json').exists())):
            prepared=case.prepare_profile(profile,modules,definition)
            if prepared:(out/'profile-install.json').write_text(json.dumps(prepared,ensure_ascii=False,indent=2),encoding='utf-8')
        # A real desktop session always has ProgramData; omitting it here made the plugin
        # spawn installer children with a bare environment and install to the drive root.
        env={k:os.environ[k] for k in ['PATH','SYSTEMROOT','WINDIR','PROGRAMDATA','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','COMSPEC','PATHEXT','DISPLAY','XAUTHORITY','GDK_BACKEND','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP','DBUS_SESSION_BUS_ADDRESS','XDG_RUNTIME_DIR','WAYLAND_DISPLAY','BSK_HOME','BSK_AUTO_START'] if k in os.environ}
        env.update(DSH_HOME=str(home),DSH_TEST_KEY='local-fixed-not-a-real-key',LANG='C.UTF-8')
        if os.environ.get('DSH_TEST_INSTALLED_HOST')=='1':
            from .service_host import UserServiceHost
            logfile=out/'process-installed-service.log'
            service_host=UserServiceHost(logfile);dsh=service_host
        else:
            dsh=start(['node',str(modules/'@deepseek-ai/dsh/lib/bin.js'),'--profile','web','--host','127.0.0.1','--port','0','--no-open'],env=env,cwd=project)
            logfile=out/f'process-{len(processes)-1}.log'
        def login_url():
            if dsh.poll() is not None:raise RuntimeError('DSH exited; see '+str(logfile))
            matches=re.findall(r'http://127\.0\.0\.1:\d+/\?token=[^\s\x1b]+',logfile.read_text(encoding='utf-8'))
            return matches[-1] if matches else None
        url=until(login_url,60)
        def restart_dsh():
            nonlocal dsh,logfile
            from urllib.parse import urlparse
            if service_host:
                service_host.restart();until(login_url,60)
                return {'restarted':True,'profile_preserved':True,'host':'installed-user-service'}
            desktop.stop_process(dsh)
            dsh=start(['node',str(modules/'@deepseek-ai/dsh/lib/bin.js'),'--profile','web','--host','127.0.0.1','--port',str(urlparse(url).port),'--no-open'],env=env,cwd=project)
            logfile=out/f'process-{len(processes)-1}.log'
            until(login_url,60)
            return {'restarted':True,'profile_preserved':True}
        backend.restart_dsh=restart_dsh
        with sync_playwright() as pw:
            from .review import inspect_until_closed
            # A case that checks window activation needs a real window on the desktop; the
            # default headless page has none to raise.
            # Playwright's default focus emulation makes hidden tabs report visible.
            # Attach without overrides to a normal browser for native tab-switch tests.
            options=desktop.browser_options(True,os.environ.copy())
            executable=options.get('executable_path')
            if not executable:
                executable=next(str(Path(os.environ[k])/'Microsoft/Edge/Application/msedge.exe') for k in ('PROGRAMFILES(X86)','PROGRAMFILES') if k in os.environ and (Path(os.environ[k])/'Microsoft/Edge/Application/msedge.exe').exists())
            # Edge's broker may run with a different integrity token. Do not put
            # its profile under the test artifact directory's Windows 0700 ACL.
            import tempfile,uuid
            browser_record=session_root/'browser-profile.json'
            persistent_browser=bool(os.environ.get('DSH_TEST_SESSION_DIRECTORY'))
            profile_root=Path.home()/'.local/share/dsh-test/browser-profiles' if persistent_browser else Path(tempfile.gettempdir())
            user_data=Path(json.loads(browser_record.read_text())) if persistent_browser and browser_record.exists() else profile_root/('dsh-browser-'+uuid.uuid4().hex)
            profile_existed=user_data.exists()
            user_data.mkdir(parents=True,exist_ok=True)
            (out/'browser-profile-state.json').write_text(json.dumps({'path':str(user_data),'reused':profile_existed,'persistent':persistent_browser}),encoding='utf-8')
            if persistent_browser:browser_record.write_text(json.dumps(str(user_data)),encoding='utf-8')
            import socket,urllib.request
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));debug_port=listener.getsockname()[1]
            browser_args=desktop.browser_arguments(executable,user_data)+['--remote-debugging-port='+str(0 if definition.get('browser_dynamic_port') else debug_port)]
            if not desktop.windows:
                browser_args+=['--disable-dev-shm-usage','--window-size=1280,850']
            if definition.get('browser_skill'):
                extension=Path(os.environ.get('BSK_TEST_EXTENSION',str(Path.home()/'.local/share/dsh-test/browserskill-extension')))
                if not (extension/'manifest.json').exists():raise FileNotFoundError('BrowserSkill extension: '+str(extension))
                # Chrome stable requires installation through its actual extension manager.
            if definition.get('default_browser'):
                from .default_browser import DefaultBrowser
                default_browser=DefaultBrowser(browser_args)
            start([*browser_args,'about:blank'])
            if definition.get('browser_dynamic_port'):
                port_file=user_data/'DevToolsActivePort'
                until(port_file.exists,30)
                debug_port=int(port_file.read_text().splitlines()[0])
            backend.browser_profile=user_data
            endpoint='http://127.0.0.1:'+str(debug_port)
            backend.browser_endpoint=endpoint
            def debug_ready():
                try:
                    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
                    with opener.open(endpoint+'/json/version',timeout=1) as response:return response.status==200
                except OSError:return False
            until(debug_ready,30)
            browser=pw.chromium.connect_over_cdp(endpoint,no_defaults=True)
            context=browser.contexts[0]
            import platform
            runtime={'system':platform.platform(),'python':sys.version,'browser':browser.version,
                     'node':subprocess.check_output(['node','--version'],text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).strip(),'packages':{}}
            runtime['packages']=json.loads(subprocess.check_output([
                'node','-e',"const r=require('node:module').createRequire(process.argv[1]); console.log(JSON.stringify(Object.fromEntries(['@deepseek-ai/dsh','@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app'].map(n=>[n,r(n+'/package.json').version]))));",
                str(modules/'@deepseek-ai/dsh/package.json')],text=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)))
            (out/'runtime-versions.json').write_text(json.dumps(runtime,ensure_ascii=False,indent=2),encoding='utf-8')
            extension_state={}
            for filename in ('Preferences','Secure Preferences'):
                preference=user_data/'Default'/filename
                if preference.exists():
                    settings=json.loads(preference.read_text(encoding='utf-8')).get('extensions',{}).get('settings',{})
                    extension_state[filename]={key:{field:value.get(field) for field in ('path','state','disable_reasons','location')} for key,value in settings.items()}
            (out/'browser-extension-state.json').write_text(json.dumps(extension_state,ensure_ascii=False,indent=2),encoding='utf-8')
            # Initial user setup only; later product focus assertions never activate here.
            from .entities import Entities
            from types import SimpleNamespace
            initial_page=context.pages[0] if context.pages else context.new_page()
            initial=Entities(SimpleNamespace(page=initial_page))
            bound=initial.current_page({'entity':'dsh-start'})
            desktop.activate(bound['window'])
            if definition.get('browser_skill'):
                from .browser_extension import load
                bsk=shutil.which('bsk') or str(Path.home()/'.local/bin'/('bsk.exe' if os.name=='nt' else 'bsk'))
                bsk_probe=subprocess.run([bsk,'--json','browsers'],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                (out/'browserskill-cli.log').write_bytes(bsk_probe.stdout+bsk_probe.stderr)
                if bsk_probe.returncode:raise RuntimeError('BrowserSkill daemon: '+(bsk_probe.stdout+bsk_probe.stderr).decode('utf-8','replace')[-1000:])
                load(context,extension,out)
                extension_page=context.new_page()
                extension_page.goto('chrome-extension://hhcmgoofomhgciiibhipgmgkgnoenaoi/popup.html')
                extension_page.get_by_text('Connected',exact=True).wait_for(timeout=30000)
                extension_page.screenshot(path=str(out/'browserskill-connected.png'))
                extension_page.close()
            page=context.pages[0] if context.pages else context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            network=[]
            page.on('response',lambda r:network.append({'method':r.request.method,'url':r.url.split('?')[0],'status':r.status}))
            page.goto(url,wait_until='domcontentloaded',timeout=60000)
            try:
                page.locator('aside[aria-label="大肥鱼监工"] > button').or_(page.get_by_role('button',name='Continue',exact=True)).first.wait_for(timeout=40000)
            except Exception:
                page.screenshot(path=str(out/'startup-failure.png'));(out/'startup-failure.txt').write_text(page.locator('body').first.inner_text(),encoding='utf-8');raise
            if not desktop.windows:
                from dsh_test_harness.gnome import call
                actual=call('snapshot')
                windows=[w for w in actual['windows'] if w['id']==bound['window_id']]
                if not windows or any(w['client_type']!='wayland' for w in windows):raise RuntimeError('DSH browser has no native Wayland window')
                (out/'browser-desktop.json').write_text(json.dumps(actual,ensure_ascii=False),encoding='utf-8')
            (out/'ui.txt').write_text(page.locator('body').first.inner_text(), encoding='utf-8');page.screenshot(path=str(out/'initial.png'))
            backend.human_step_delay=args.human_step_delay if args.human_review else 0
            def render_state():
                return page.evaluate("""()=>new Promise(resolve=>{
                  let frames=0;let done=false;
                  const tick=()=>{frames++;if(!done)requestAnimationFrame(tick)};
                  requestAnimationFrame(tick);
                  setTimeout(()=>{done=true;resolve({frames,visibility:document.visibilityState,focused:document.hasFocus(),width:innerWidth,height:innerHeight})},500);
                })""")
            (out/'before-input-render.json').write_text(json.dumps(render_state()),encoding='utf-8')
            if not desktop.windows:
                from .gnome import call
                window=next(w for w in call('snapshot')['windows'] if w['id']==bound['window_id'])
                call('screenshot',{'path':str(out/'initial-desktop.png')})
                (out/'browser-setup.json').write_text(json.dumps({'method':'initial native activation','window_id':bound['window_id'],'phase':'initial loaded page'}),encoding='utf-8')
            (out/'initial-render.json').write_text(json.dumps(render_state()),encoding='utf-8')
            if not args.inspect:
                try:case.run(page,backend,model,project,out,args.test_file)
                except Exception as error:
                    if desktop.windows:
                        try:
                            from .vm.input import request
                            request('screenshot',name=out.name)
                        except Exception as capture_error:
                            (out/'failure-display-error.txt').write_text(str(capture_error),encoding='utf-8')
                        try:
                            import win32gui
                            state={'cursor':win32gui.GetCursorPos(),'foreground':win32gui.GetForegroundWindow()}
                            state['foreground_title']=win32gui.GetWindowText(state['foreground'])
                            state['foreground_class']=win32gui.GetClassName(state['foreground'])
                            import win32service,win32api,win32con
                            state['thread_desktop']=win32service.GetUserObjectInformation(win32service.GetThreadDesktop(win32api.GetCurrentThreadId()),win32con.UOI_NAME)
                            try:
                                input_desktop=win32service.OpenInputDesktop(0,False,win32con.DESKTOP_READOBJECTS)
                                try:state['input_desktop']=win32service.GetUserObjectInformation(input_desktop,win32con.UOI_NAME)
                                finally:input_desktop.CloseDesktop()
                            except Exception as desktop_error:state['input_desktop_error']=str(desktop_error)
                            from .entities import Entities
                            state['desktop']=Entities(None).snapshot()
                            (out/'failure-input-state.json').write_text(json.dumps(state),encoding='utf-8')
                            from PIL import ImageGrab
                            ImageGrab.grab().save(out/'failure-desktop.png')
                        except Exception as diagnostic_error:
                            (out/'failure-input-state-error.txt').write_text(str(diagnostic_error),encoding='utf-8')
                    try:
                        if browser.is_connected() and not page.is_closed():
                            session_state=page.evaluate("""()=>({
                              visibility:document.visibilityState, focused:document.hasFocus(),
                              nodes:[...document.querySelectorAll('[data-phase], [data-slot="conversation.session.header"]')].map(node=>{
                                const ancestors=[];
                                for(let e=node;e && ancestors.length<6;e=e.parentElement){
                                  const style=getComputedStyle(e);
                                  ancestors.push({tag:e.tagName,slot:e.dataset.slot,phase:e.dataset.phase,
                                    display:style.display,visibility:style.visibility,rect:e.getBoundingClientRect().toJSON()});
                                }
                                return ancestors;
                              })
                            })""")
                            (out/'failure-session.json').write_text(json.dumps(session_state),encoding='utf-8')
                            (out/'failure-render.json').write_text(json.dumps(render_state()),encoding='utf-8')
                            page.screenshot(path=str(out/'failure.png'));(out/'failure-ui.txt').write_text(page.locator('body').first.inner_text(), encoding='utf-8')
                    except Exception as capture_error:
                        (out/'failure-capture-error.txt').write_text(str(capture_error),encoding='utf-8')
                    (out/'result.json').write_text(json.dumps({'status':'failed','failure_stage':'assertion' if isinstance(error,AssertionError) else 'scenario','error':str(error),'requests':len(model.requests),'page_errors':errors,'backend_errors':backend.errors},ensure_ascii=False,indent=2), encoding='utf-8')
                    raise
            (out/'result.json').write_text(json.dumps({'status':'failed' if errors or backend.errors else 'inspected' if args.inspect else 'passed','requests':len(model.requests),'page_errors':errors,'backend_errors':backend.errors},ensure_ascii=False,indent=2), encoding='utf-8')
            assert not errors and not backend.errors,(errors,backend.errors)
            (out/'network.json').write_text(json.dumps(network,ensure_ascii=False,indent=2), encoding='utf-8')
            if args.human_review:
                (out/'automation-result.json').write_text((out/'result.json').read_text(encoding='utf-8'), encoding='utf-8')
                (out/'result.json').write_text(json.dumps({'status':'inspecting','requests':len(model.requests)}), encoding='utf-8')
                inspect_until_closed(page,out)
                (out/'result.json').write_text((out/'automation-result.json').read_text(encoding='utf-8'), encoding='utf-8')
            # The Playwright scope disconnects the automation transport. Owned
            # browser processes are stopped once in the native cleanup below.
        print('DSH harness finished:',out)
    except Exception as error:
        import traceback
        (out/'error-traceback.txt').write_text(traceback.format_exc(),encoding='utf-8')
        if os.name=='nt':
            try:
                from PIL import ImageGrab
                ImageGrab.grab(all_screens=True).save(out/'failure-desktop.png')
            except Exception as capture_error:
                (out/'failure-desktop-error.txt').write_text(str(capture_error),encoding='utf-8')
        if not (out/'result.json').exists():
            (out/'result.json').write_text(json.dumps({'status':'failed','failure_stage':'environment','error':str(error)},ensure_ascii=False),encoding='utf-8')
        raise
    finally:
        signal.signal(signal.SIGTERM,previous_signal)
        cleanup_errors=[]
        if 'bsk_probe' in locals():
            try:
                diagnostic=subprocess.run([bsk,'logs','--lines','120'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                log=re.sub(r'([?&]token=)[^\s&]+',r'\1[redacted]',diagnostic.stdout+diagnostic.stderr)
                (out/'browserskill-daemon.log').write_text(log,encoding='utf-8')
            except Exception as error:
                (out/'browserskill-diagnostic-error.txt').write_text(str(error),encoding='utf-8')
        if os.name=='nt' and 'bsk_probe' in locals():
            stopped=subprocess.run([bsk,'daemon','stop'],capture_output=True,timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if stopped.returncode:cleanup_errors.append('BrowserSkill cleanup: '+(stopped.stdout+stopped.stderr).decode('utf-8','replace'))
        if backend:
            for cleanup in getattr(backend,'cleanup_callbacks',[]):
                try:cleanup()
                except Exception as error:cleanup_errors.append(str(error))
            try:backend.close()
            except Exception as error:cleanup_errors.append(str(error))
            backend=None
        if service_host:
            try:service_host.close()
            except Exception as error:cleanup_errors.append(str(error))
        for p in reversed(processes):
            try:desktop.stop_process(p)
            except Exception as error:cleanup_errors.append(str(error))
        if default_browser:
            try:default_browser.close()
            except Exception as error:cleanup_errors.append('Default browser restore: '+str(error))
        try:desktop.close()
        except Exception as error:cleanup_errors.append('Desktop settings restore: '+str(error))
        if cleanup_errors:
            result_path=out/'result.json'
            detail=json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else {}
            detail['cleanup_errors']=cleanup_errors
            if detail.get('status')!='failed':detail.update(status='failed',failure_stage='cleanup',error='; '.join(cleanup_errors))
            result_path.write_text(json.dumps(detail,ensure_ascii=False,indent=2),encoding='utf-8')
        if user_data and not os.environ.get('DSH_TEST_SESSION_DIRECTORY'):shutil.rmtree(user_data,ignore_errors=True)
        if fixture_server:fixture_server.shutdown();fixture_server.server_close()
        if backend:backend.close()
        if model:model.close()
        for log in logs:log.close()
        # Login credentials are ephemeral; don't preserve them in process logs.
        for path in out.glob('process-*.log'):
            text=path.read_text(encoding='utf-8');path.write_text(re.sub(r'(\?token=)[^\s\x1b]+',r'\1[redacted]',text), encoding='utf-8')
        os.environ.clear();os.environ.update(original_env)

if __name__=='__main__':main()
