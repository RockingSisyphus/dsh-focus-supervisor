"""ui scenario actions; expectations are supplied by JSON."""
import json,os,re,time,socket,http.client,shutil,subprocess,sys,tempfile,threading
from pathlib import Path
from urllib.parse import urlparse
from dsh_test_harness.desktop import Desktop
from dsh_test_harness.wait import until
from ui import *
PACK=Path(__file__).resolve().parents[2];ROOT=PACK.parent

def ui_use_opened_page(self,step):
    transport=self.closed_page_context.browser.new_browser_cdp_session()
    def opened():
        transport.send('Target.getTargets')
        return next((p for p in self.closed_page_context.pages if p.url.rstrip('/')==self.closed_page_origin and 'DeepSeek Harness' in p.title()),None)
    try:self.page=until(opened,step.get('timeout',10))
    finally:transport.detach()
    return self.entities.current_page({'entity':step['entity']})

def ui_use_claimant(self,step):
    owner=(self.plugin_state() or {})['focus_request']['page']
    for entity in step['entities']:
        item=self.entities.items[entity]
        if item['page'].evaluate('globalThis.__DAFEIYU__?.page')==owner:
            self.entities.items[step['entity']]=item;self.page=item['page']
            return {'owner':owner,'source_entity':entity,'window_id':item['window_id']}
    raise RuntimeError('Claiming page does not correspond to an observed fixture')

def ui_restart_dsh(self,step):
    previous=self.page.evaluate('globalThis.__DAFEIYU__?.token')
    result=self.backend.restart_dsh()
    def renewed():
        current=self.page.evaluate('globalThis.__DAFEIYU__?.token')
        return current and current!=previous
    try:until(renewed,step.get('timeout',30));changed=True
    except TimeoutError:changed=False
    return {**result,'page_token_changed':changed}

def ui_wait_focus_result(self,step):
    deadline=self.popup_click_started+step.get('timeout',10)
    observations=[]
    while True:
        if hasattr(self,'closed_page_token'):
            import urllib.request
            request=urllib.request.Request(self.closed_page_origin+'/focus/status',headers={'x-focus-token':self.closed_page_token})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request,timeout=2) as response:state=json.load(response)
        else:state=self.plugin_state()
        value=(state or {}).get('focus_request')
        observations.append({'elapsed_seconds':round(time.monotonic()-self.popup_click_started,3),
                             'request':value,'page_title':None if self.page.is_closed() else self.page.title(),
                             'windows':[{k:w.get(k) for k in ('id','pid','title','focused')} for w in self.entities.snapshot()['windows']]})
        (self.out/(step['id']+'-focus-observations.json')).write_text(json.dumps(observations,ensure_ascii=False),encoding='utf-8')
        if ((value or {}).get('id')!=getattr(self,'popup_previous_request',None) and (value or {}).get('status') in ('completed','failed')) or time.monotonic()>=deadline:
            if not self.page.is_closed():
                titles=self.page.evaluate('()=>{globalThis.__DSH_TEST_TITLE_OBSERVER__?.disconnect();return globalThis.__DSH_TEST_TITLE_LOG__||[]}')
                (self.out/(step['id']+'-title-mutations.json')).write_text(json.dumps(titles,ensure_ascii=False),encoding='utf-8')
            return {'request':value,'elapsed_seconds':time.monotonic()-self.popup_click_started}
        time.sleep(.1)

def ui_focus_diagnostics(self,step):
    state=self.plugin_state() or {}
    value={'focus_request':state.get('focus_request'),'pages':state.get('pages'),'desktop':self.entities.snapshot(),
           'page':self.page.evaluate('()=>({title:document.title,visibility:document.visibilityState,focusedSession:globalThis.__DAFEIYU__?.focusedSession,claimError:globalThis.__DAFEIYU__?.claimError,body:document.body.innerText.slice(-3000)})')}
    from dsh_test_harness.native_text import read_window
    value['popup_text']=[read_window(w) for w in value['desktop']['windows'] if w['title']=='大肥鱼监工提醒']
    if os.name=='nt':
        from PIL import ImageGrab
        ImageGrab.grab().save(self.out/(step['id']+'.png'))
        from pywinauto import Desktop as Native
        pid=self.entities.items['dsh']['pid'] if 'dsh' in self.entities.items else None
        value['native_tabs']=[];value['native_buttons']=[]
        for w in value['desktop']['windows']:
            if w['pid']!=pid:continue
            native=Native(backend='uia').window(handle=int(w['id'].split(':')[1]))
            from collections import deque
            queue=deque([native.wrapper_object()])
            while queue:
                node=queue.popleft();kind=node.element_info.control_type
                if kind=='Document':continue
                if kind=='Button':value['native_buttons'].append({'window_id':w['id'],'name':node.window_text()})
                if kind=='TabItem':value['native_tabs'].append({'window_id':w['id'],'name':node.window_text(),'selected':node.is_selected()})
                queue.extend(node.children())
    return value

def ui_use_page(self,step):
    self.page=self.entities.items[step['entity']]['page']
    self.page.locator('aside[aria-label="大肥鱼监工"] > button').wait_for()
    notice=self.page.get_by_role('button',name='Continue',exact=True)
    if step.get('accept_notice') and notice.is_visible():notice.click()
    return {'url':self.page.url}

def ui_settings(self,step):
    op=step["op"];p=self.page;b=self.backend
    self.open_settings()
    targets = {'mascot_size': p.get_by_role('slider', name='形象大小'), 'instructions': p.get_by_label('插件使用说明（全局）'), 'instructions_full': p.get_by_label('完整 API 文档（focus_help 返回，全局）'), 'heartbeat_prompt': p.get_by_label('每次心跳的监工要求（全局）'), 'away_heartbeats': p.get_by_label('离席判定次数')}
    schema=p.evaluate('globalThis.__DAFEIYU__.samplingSchema')
    for group in step.get('reset_groups',[]):
        section=p.locator('details').filter(has=p.locator('summary',has_text='采集设置' if group=='sampling' else '模型输出'))
        if section.get_attribute('open') is None:section.locator('summary').click()
        section.get_by_role('button',name='恢复本组默认值').click()
    for key, value in step.get('values', {}).items():
        if key=='protect_task_changes':
            p.get_by_label('防任务中修改模式',exact=True).set_checked(value);continue
        if key not in ('sampling','reporting'):
            targets[key].fill(str(value));continue
        section=p.locator('details').filter(has=p.locator('summary',has_text='采集设置' if key=='sampling' else '模型输出'))
        if section.get_attribute('open') is None:section.locator('summary').click()
        for field,number in value.items():
            spec=schema[key][field]
            if spec.get('nullable'):p.get_by_label(spec['label']+'不限',exact=True).set_checked(number is None)
            if number is not None:p.get_by_label(spec['label'],exact=True).fill(str(number))
    if step.get('save', False):
        p.get_by_role('button', name='保存设置', exact=True).click()
        p.get_by_text('设置已保存。', exact=True).wait_for()
    return self.ui_state()

def ui_open(self,step):
    op=step["op"];p=self.page;b=self.backend
    if self.ball.get_attribute('aria-expanded') != 'true':
        self.ball.click()
    self.page.get_by_role('button', name='收起监工', exact=True).wait_for()
    return self.ui_state()

def ui_click(self,step):
    op=step["op"];p=self.page;b=self.backend
    p.locator(step['selector']).click(timeout=step.get('timeout',30)*1000)
    return self.ui_state()

def ui_wait_card(self,step):
    op=step["op"];p=self.page;b=self.backend
    def card_ready():
        card = self.setup_card()
        return card if card and step['contains'] in card.get('text', '') else None
    return until(card_ready, step.get('timeout', 60))

def ui_plugin_state(self,step):
    op=step["op"];p=self.page;b=self.backend
    return self.plugin_state()

def ui_wait_plugin_state(self,step):
    def ready():
        state=self.plugin_state()
        value=state
        for key in step['path'].split('.'):
            value=value.get(key) if isinstance(value,dict) else None
        return state if (value in step['one_of'] if 'one_of' in step else value==step['equals']) else None
    return until(ready,step.get('timeout',60))

def ui_wait_tasks(self,step):
    op=step["op"];p=self.page;b=self.backend
    def ready():
        groups = self.task_groups()
        return self.ui_state() if len(groups['active']) + len(groups['scheduled']) == step['count'] else None
    return until(ready, step.get('timeout', 40))

def ui_toggle_task(self,step):
    op=step["op"];p=self.page;b=self.backend
    p.locator('article[data-task-id="' + step['task_id'] + '"] button[data-dafeiyu-toggle]').click()
    return self.ui_state()

def ui_close(self,step):
    op=step["op"];p=self.page;b=self.backend
    self.close_panel()
    return None

def ui_reset_prompts(self,step):
    op=step["op"];p=self.page;b=self.backend
    self.open_settings()
    p.get_by_role('button', name='重置为默认提示词', exact=True).click()
    p.get_by_text('已重置为插件当前默认提示词', exact=False).wait_for()
    return self.ui_state()

def ui_snapshot(self,step):
    op=step["op"];p=self.page;b=self.backend
    return self.ui_state()

def ui_wait(self,step):
    op=step["op"];p=self.page;b=self.backend
    def condition():
        state = self.ui_state()
        return state if all((state.get(k) == v for k, v in step['expected'].items())) else None
    return until(condition, step.get('timeout', 15))

def ui_reload(self,step):
    op=step["op"];p=self.page;b=self.backend
    p.reload()
    self.ball.wait_for()
    p.wait_for_function('document.querySelector("aside img")?.naturalWidth>0')
    return self.ui_state()

def ui_drag(self,step):
    op=step["op"];p=self.page;b=self.backend
    box = self.ball.bounding_box()
    p.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
    p.mouse.down()
    p.mouse.move(*step['to'], steps=12)
    p.mouse.up()
    return self.ui_state()

def ui_workspace(self,step):
    op=step["op"];p=self.page;b=self.backend
    self.close_panel()
    p.get_by_role('button', name='Choose workspace', exact=True).click()
    picker=p.get_by_role('dialog')
    add=p.get_by_text('Add workspace…',exact=True)
    picker.or_(add).first.wait_for()
    if add.is_visible():add.click()
    picker.wait_for()
    p.get_by_role('button', name='Edit path', exact=True).click()
    entry = p.get_by_role('textbox', name='Edit path', exact=True)
    entry.fill(self.values['project'])
    entry.press('Enter')
    p.get_by_role('button', name='Open', exact=True).click()
    p.get_by_role('dialog').wait_for(state='hidden')
    p.locator('[contenteditable="true"]').wait_for()
    return None

def session_command(self,step):
    op=step["op"];p=self.page;b=self.backend
    editor = p.locator('[contenteditable="true"]')
    editor.fill(step['command'])
    editor.press('Enter')
    if step.get('expected_text'):
        result=p.get_by_text(re.compile(step['expected_text'])).last
        result.wait_for(timeout=step.get('timeout',60)*1000)
        return {'text':result.inner_text()}
    return None

def session_permissions(self,step):
    op=step["op"];p=self.page;b=self.backend
    def inspect():
        data = p.evaluate("async()=>await(await fetch('/focus/status',{headers:{'x-focus-token':window.__DAFEIYU__.token}})).json()")
        values = data.get('session_permissions', {})
        repairs = max(data.get('permission_repairs', {}).values(), default=0)
        return values if values and all((v == step['expected'] for v in values.values())) and (repairs >= step.get('repairs', 0)) else None
    return until(inspect, 15)

def ui_new_session(self,step):
    op=step["op"];p=self.page;b=self.backend
    self.close_panel()
    p.get_by_role('button', name='New session', exact=True).first.click()
    p.get_by_text('Describe what you want to build, / commands, @ files or sessions', exact=True).wait_for()
    p.locator('[contenteditable="true"]').wait_for()
    return None

def ui_screenshot(self,step):
    op=step["op"];p=self.page;b=self.backend
    p.screenshot(path=str(self.out / (step['name'] + '.png')))
    return step['name'] + '.png'

def ui_assets(self,step):
    op=step["op"];p=self.page;b=self.backend
    import io
    from PIL import Image
    result = {}
    for name in step['names']:
        from urllib.parse import urlsplit
        url = urlsplit(p.url)
        response = p.request.get(url.scheme + '://' + url.netloc + '/focus/mascot/' + name + '.png')
        with Image.open(io.BytesIO(response.body())) as image:
            result[name] = {'status': response.status, 'transparent': image.mode == 'RGBA' and image.getchannel('A').getextrema()[0] == 0}
    return result

def ui_background_page(self,step):
    op=step["op"];p=self.page;b=self.backend
    p.bring_to_front()
    initial_pages=len(p.context.pages)
    target = next((w for w in b.desktop_windows() if 'DeepSeek Harness' in w.get('title', '')))
    Desktop().activate(target)
    if sys.platform == 'win32':
        from pywinauto.keyboard import send_keys
        send_keys('^t')
    else:
        from dsh_test_harness.gnome import call
        call('keys', {'keys': ['Control_L', 't']})
    until(lambda: p.evaluate('document.visibilityState') == 'hidden' and len(p.context.pages)>initial_pages, 10,wait=lambda seconds:p.wait_for_timeout(seconds*1000))
    return {'hidden': True, 'pages': len(p.context.pages)}

def ui_page_count(self,step):
    op=step["op"];p=self.page;b=self.backend
    return {'pages': len(self.page.context.pages)}

def ui_wait_focused_session(self,step):
    op=step["op"];p=self.page;b=self.backend
    expected = self.resolve(step['session_id'])
    try:
        until(lambda: p.evaluate('()=>(globalThis.__DAFEIYU__||{}).focusedSession||null') == expected, step.get('timeout', 20))
    except Exception:
        detail = p.evaluate('()=>({focused:(globalThis.__DAFEIYU__||{}).focusedSession||null,error:(globalThis.__DAFEIYU__||{}).claimError||null})')
        raise AssertionError('页面没有切到监工会话：' + json.dumps(detail, ensure_ascii=False))
    return {'switched': True, 'session_id': expected}

def ui_reminder_link(self,step):
    op=step["op"];p=self.page;b=self.backend
    alert = b.core.store.all('alert')[-1]
    # Observe the preceding real popup click. Navigating here would issue a
    # second request and unload the page while it is completing the first.
    p.get_by_text(step['message'], exact=True).last.wait_for(timeout=30000)
    until(lambda: urlparse(p.url).path == '/' and (not urlparse(p.url).query))
    try:opened = until(lambda: p.evaluate('()=>(globalThis.__DAFEIYU__||{}).focusedSession||null'), 20)
    except Exception:
        (self.out/(step['id']+'-focus.json')).write_text(json.dumps({'state':self.plugin_state(),'page':p.evaluate('()=>({page:globalThis.__DAFEIYU__?.page,focusedSession:globalThis.__DAFEIYU__?.focusedSession,claimError:globalThis.__DAFEIYU__?.claimError})')},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    if opened != alert['session_id']:
        raise AssertionError('提醒链接没有打开监工会话：' + str(opened))
    return {'opened': True, 'session_id': opened, 'url': p.url}

def registry(scenario):return {
    'ui.use_opened_page':lambda step:ui_use_opened_page(scenario,step),
    'ui.use_claimant':lambda step:ui_use_claimant(scenario,step),
    'ui.restart_dsh':lambda step:ui_restart_dsh(scenario,step),
    'ui.wait_focus_result':lambda step:ui_wait_focus_result(scenario,step),
    'ui.settings': lambda step: ui_settings(scenario,step),
    'ui.open': lambda step: ui_open(scenario,step),
    'ui.click': lambda step: ui_click(scenario,step),
    'ui.wait_card': lambda step: ui_wait_card(scenario,step),
    'ui.wait_plugin_state': lambda step: ui_wait_plugin_state(scenario,step),
    'ui.plugin_state': lambda step: ui_plugin_state(scenario,step),
    'ui.wait_tasks': lambda step: ui_wait_tasks(scenario,step),
    'ui.toggle_task': lambda step: ui_toggle_task(scenario,step),
    'ui.close': lambda step: ui_close(scenario,step),
    'ui.reset_prompts': lambda step: ui_reset_prompts(scenario,step),
    'ui.snapshot': lambda step: ui_snapshot(scenario,step),
    'ui.wait': lambda step: ui_wait(scenario,step),
    'ui.reload': lambda step: ui_reload(scenario,step),
    'ui.drag': lambda step: ui_drag(scenario,step),
    'ui.focus_diagnostics':lambda step:ui_focus_diagnostics(scenario,step),
    'ui.use_page':lambda step:ui_use_page(scenario,step),
    'ui.workspace': lambda step: ui_workspace(scenario,step),
    'session.command': lambda step: session_command(scenario,step),
    'session.permissions': lambda step: session_permissions(scenario,step),
    'ui.new_session': lambda step: ui_new_session(scenario,step),
    'ui.screenshot': lambda step: ui_screenshot(scenario,step),
    'ui.assets': lambda step: ui_assets(scenario,step),
    'ui.background_page': lambda step: ui_background_page(scenario,step),
    'ui.page_count': lambda step: ui_page_count(scenario,step),
    'ui.wait_focused_session': lambda step: ui_wait_focused_session(scenario,step),
    'ui.reminder_link': lambda step: ui_reminder_link(scenario,step),
}
