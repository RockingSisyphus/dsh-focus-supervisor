"""Domain operations for JSON scenarios; expectations live in the case files."""
import json,os,re,time,socket,http.client,shutil,subprocess,sys,tempfile,threading
from datetime import datetime,timezone
from urllib.parse import urlparse
from pathlib import Path
from backend import Backend
from dsh_test_harness.desktop import Desktop
from ui import until
ROOT=Path(__file__).resolve().parents[2]
PACK=Path(__file__).resolve().parents[1]
MISSING=object()

def inject_input():
    if os.environ.get('DSH_TEST_DESKTOP_DRIVER')=='host':
        subprocess.run(['ydotool','key','185:1','185:0'],check=True,capture_output=True,timeout=5)
    elif os.environ.get('DSH_TEST_GUEST'):
        from dsh_test_harness.vm.input import request
        request('keys',keys='f15')
    else:
        from dsh_test_harness.gnome import call
        call('keys',{'keys':['F15']})

def keep_user_present(interval=4.0):
    """A case that assumes an attentive user must say so: the plugin deliberately stops
    delivering heartbeats after N input-free ones, which is covered by its own case."""
    stop=threading.Event();stop.errors=[]
    def loop():
        while not stop.wait(interval):
            try:inject_input()
            except Exception as error:stop.errors.append(str(error))
    stop.worker=threading.Thread(target=loop,daemon=True);stop.worker.start()
    return stop

def prepare_profile(profile,modules,definition):
    """Install the plugin the way the marketplace does: a real `npm pack` tarball,
    then DSH's own `plugin add` (pnpm in the profile) so the bundle layer mounts it."""
    profile=Path(profile)
    # The live marketplace profile uses a hoisted linker and does not install peers;
    # DSH supplies those from the install anchor through .dsh-module-fallback.
    (profile/'pnpm-workspace.yaml').write_text('packages:\n  - .\nnodeLinker: hoisted\nautoInstallPeers: false\n',encoding='utf-8')
    # On Windows npm is npm.cmd, which subprocess cannot exec without PATHEXT lookup.
    npm=shutil.which('npm') or 'npm'
    # text=True alone uses the Windows locale codec and dies on UTF-8 installer output.
    packed=subprocess.run([npm,'pack','--pack-destination',str(profile)],cwd=str(ROOT/'dsh-plugin'),capture_output=True,text=True,
        encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if packed.returncode:raise RuntimeError('npm pack 失败：'+(packed.stderr or packed.stdout)[-800:])
    names=[line.strip() for line in packed.stdout.splitlines() if line.strip().endswith('.tgz')]
    if not names:raise RuntimeError('npm pack 没有产出 tarball：'+packed.stdout[-400:])
    tarball=profile/names[-1]
    env={**os.environ,'DSH_HOME':str(profile.parents[1])}
    cli=Path(modules)/'@deepseek-ai/dsh/lib/bin.js'
    result=subprocess.run(['node',str(cli),'plugin','--profile','web','add',str(tarball)],cwd=str(profile),capture_output=True,text=True,
        encoding='utf-8',errors='replace',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if result.returncode:raise RuntimeError('dsh plugin add 失败：'+(result.stderr or result.stdout)[-1200:])
    if definition.get('browser_skill'):
        browser_install=subprocess.run(['node',str(cli),'plugin','--profile','web','add','@wxg-prc-cpg/browser-skill-dsh-plugin@0.3.0'],cwd=str(profile),capture_output=True,text=True,encoding='utf-8',errors='replace',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if browser_install.returncode:raise RuntimeError('BrowserSkill plugin install: '+browser_install.stderr[-1200:])
    installed=profile/'node_modules/dsh-focus-supervisor'
    if not installed.is_dir():raise RuntimeError('市场安装后没有找到 dsh-focus-supervisor：'+str(installed))
    manifest=json.loads((profile/'package.json').read_text(encoding='utf-8'))
    bundles=(manifest.get('dsh',{}).get('profile',{}) or {}).get('bundles',[])
    if 'dsh-focus-supervisor' not in bundles:raise RuntimeError('市场安装后 profile 没有把插件并入 bundles：'+json.dumps(bundles,ensure_ascii=False))
    return {'tarball':str(tarball),'installed':str(installed),'bundles':bundles}

def setup(out,start,test_file):
    definition=json.loads(test_file.read_text(encoding='utf-8'))
    backend=Backend(out/'backend',definition)
    config=backend.plugin_config
    return backend,[{'id':'focus-supervisor-chat','config':config}]

from support import *
from dsh_test_harness.scenario import ScenarioEngine, MISSING

class Scenario(ScenarioEngine):
    def __init__(self,page,backend,model,project,out,case):
        self.page,self.backend,self.model,self.out=page,backend,model,out
        self.observed_reports={r['id'] for r in backend.core.store.all('report')} if (backend.directory/'events.sqlite3').exists() else set()
        self.values={'scenario_started_at':time.time(),'project':str(project),'defaults':{**backend.core.settings(),**json.loads((ROOT/'dsh-plugin/default-prompts.json').read_text(encoding='utf-8'))},'initial_settings':backend.core.settings(),'fixture_url':getattr(backend,'fixture_url',None),
            'platform_installer':'install-windows.ps1' if sys.platform=='win32' else 'install-chat.sh','desktop_user':__import__('getpass').getuser()}
        if os.environ.get('DSH_TEST_SESSION_DIRECTORY'):
            self.values['installed_backend_script']=str(Path(os.environ['DSH_TEST_SESSION_DIRECTORY'])/'home/profiles/web/node_modules/dsh-focus-supervisor/backend/deploy'/self.values['platform_installer'])
        from actions import registry
        super().__init__(case,out,self.values,actions=registry(self),step_delay=getattr(backend,'human_step_delay',0))
    @property
    def ball(self):return self.page.locator('aside[aria-label="大肥鱼监工"] > button')
    def open_settings(self):
        if self.ball.get_attribute('aria-expanded')!='true':self.ball.click()
        button=self.page.get_by_role('button',name='设置 · 采集与提示词',exact=True)
        if button.count():button.click()
        self.page.get_by_role('slider',name='形象大小').wait_for()
    def close_panel(self):
        button=self.page.get_by_role('button',name='收起监工',exact=True)
        if button.count():button.click()
    def model_call(self,step):
        call=self.model.tool(step['user'],step['tool'],step.get('arguments',{}))
        # This step simulates a user typing into DSH. A fixture may have taken
        # native focus; DOM input alone does not switch the OS foreground app.
        from dsh_test_harness.entities import Entities
        from types import SimpleNamespace
        target=Entities(SimpleNamespace(page=self.page)).current_page({'entity':'message-target'})
        self.page.bring_to_front()
        try:Desktop().activate(target['window'])
        except TimeoutError:
            facts={'target':target,'windows':Entities(None).snapshot()['windows']}
            (self.out/(step['id']+'-activation.json')).write_text(json.dumps(facts,ensure_ascii=False,default=str),encoding='utf-8')
            raise
        editor=self.page.locator('[contenteditable="true"]');editor.fill(step['user']);editor.press('Enter')
        def response():
            for request in self.model.requests:
                for m in request['messages']:
                    if m.get('role')=='tool' and m.get('tool_call_id')==call:return m
        # Pump Playwright while DSH is executing: newly created browser targets
        # must receive Runtime.runIfWaitingForDebugger from its CDP auto-attach.
        message=until(response,step.get('timeout',60),wait=lambda seconds:self.page.wait_for_timeout(seconds*1000));raw=message['content']
        # A first message creates a real DSH session asynchronously;
        # wait for the sessionId-dependent slot to mount. Its paint/animation
        # state is not a prerequisite for a tool result that DSH already returned.
        self.page.locator('[data-slot="conversation.session.header"]').wait_for(state='attached',timeout=10000)
        # Follow DSH's spill locator through DSH itself, under the same user.
        # JSON selects fields to keep the second tool output within the inline cap.
        spilled=re.search(r'Full formatted result stored at: (.+?)\. Use read',raw)
        if spilled and step.get('result_fields'):
            import base64
            source="const fs=require('fs');const value=JSON.parse(fs.readFileSync("+json.dumps(spilled.group(1))+",'utf8'));const fields="+json.dumps(step['result_fields'])+";console.log(JSON.stringify(Object.fromEntries(fields.map(k=>[k,value[k]]))));"
            encoded=base64.b64encode(source.encode()).decode()
            extracted=self.model_call({'user':step['user']+'：读取 DSH 保存的完整结果字段','tool':'pwsh' if os.name=='nt' else 'bash',
                'arguments':{'command':"node -e \"eval(Buffer.from('"+encoded+"','base64').toString())\"",'description':'Read selected fields from saved tool result'},'timeout':step.get('timeout',60)})
            return {**extracted,'original_call_id':call,'inline_raw':raw,'spill_file':spilled.group(1)}
        # DSH appends attachment descriptions after the JSON tool report.
        try:value=json.JSONDecoder().raw_decode(raw.lstrip())[0]
        except (ValueError,TypeError):value={'error':raw}
        delivery=value.get('delivery',{}) if isinstance(value,dict) else {}
        if delivery.get('pid'):self.backend.track_notification(delivery['pid'])
        return {'value':value,'raw':raw,'call_id':call}
    def ui_state(self):
        slider=self.page.get_by_role('slider',name='形象大小')
        img=self.ball.locator('img')
        controls={}
        schema=self.page.evaluate('globalThis.__DAFEIYU__?.samplingSchema||{}')
        if slider.count():
            for group,fields in schema.items():
                controls[group]={}
                for key,spec in fields.items():
                    value=self.page.get_by_label(spec['label'],exact=True).input_value()
                    controls[group][key]=float(value) if value else None
        return {**controls,'ball':self.ball.bounding_box(),'kind':img.get_attribute('src').split('/')[-1] if img.count() else None,
            'size':int(slider.input_value()) if slider.count() else None,'locked':slider.is_disabled() if slider.count() else None,
            'manual_finish_buttons':self.page.get_by_role('button',name='手动结束任务',exact=True).count(),
            'protection_disabled':self.page.get_by_label('防任务中修改模式',exact=True).is_disabled() if slider.count() else None,
            'protect_task_changes':self.page.get_by_label('防任务中修改模式',exact=True).is_checked() if slider.count() else None,
            'instructions':self.page.get_by_label('插件使用说明（全局）').input_value() if slider.count() else None,
            'instructions_full':self.page.get_by_label('完整 API 文档（focus_help 返回，全局）').input_value() if slider.count() else None,
            'heartbeat_prompt':self.page.get_by_label('每次心跳的监工要求（全局）').input_value() if slider.count() else None,
            'away_heartbeats':int(self.page.get_by_label('离席判定次数').input_value()) if slider.count() else None,
            'task_groups':self.task_groups(),
            'setup_card':self.setup_card(),
            'panel':self.page.locator('aside > section').first.bounding_box() if self.page.locator('aside > section').count() else None}
    def plugin_state(self):
        if not self.ball.count():return None
        return self.page.evaluate("""async()=>{const response=await fetch('/focus/status',{headers:{'x-focus-token':(window.__DAFEIYU__&&window.__DAFEIYU__.token)||''},cache:'no-store'});return await response.json()}""")
    def setup_card(self):
        if not self.ball.count():return None
        return self.page.evaluate('''()=>{const el=document.querySelector('[data-dafeiyu-setup]');
          return el?{state:el.dataset.dafeiyuSetup,text:el.innerText.slice(0,400),button:!!el.querySelector('button[data-dafeiyu-setup-install]')}:null}''')
    def task_groups(self):
        if not self.ball.count():return {'active':[],'scheduled':[]}
        return self.page.evaluate("""()=>{const read=(name)=>{const box=document.querySelector('[data-dafeiyu-group="'+name+'"]');
          return box?[...box.querySelectorAll('article[data-task-id]')].map(a=>({id:a.dataset.taskId,expanded:a.dataset.expanded==='1',start:a.dataset.startAt})):[]};
          return {active:read('active'),scheduled:read('scheduled')}}""")

def run(page,backend,model,project,out,test_file):
    case=json.loads(test_file.read_text(encoding='utf-8'))
    (out/'case.json').write_text(json.dumps(case,ensure_ascii=False,indent=2), encoding='utf-8')
    scenario=Scenario(page,backend,model,project,out,case)
    notice=page.get_by_role('button',name='Continue',exact=True)
    if notice.is_visible():notice.click()
    scenario.ball.wait_for(timeout=40000)
    present=keep_user_present() if case.get('present_user') else None
    try: scenario.run()
    finally:
        if present:
            present.set();present.worker.join(35)
            if present.worker.is_alive():present.errors.append('User-input worker did not stop')
            if present.errors:
                (out/'user-input-errors.json').write_text(json.dumps(present.errors,ensure_ascii=False),encoding='utf-8')
                backend.errors.extend(present.errors)
