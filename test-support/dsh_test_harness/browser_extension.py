"""Load an actual extension through Chromium's extension manager and native picker."""
import os,time,json,subprocess
from pathlib import Path

def load(context,directory,out,name='BrowserSkill'):
    page=context.new_page();page.goto('chrome://extensions')
    from .entities import Entities
    from .desktop import Desktop
    from types import SimpleNamespace
    from .wait import until
    entities=Entities(SimpleNamespace(page=page))
    bound=entities.current_page({'entity':'extension-manager'})
    Desktop().activate(bound['window'])
    before={w['id'] for w in entities.snapshot()['windows']}
    page.screenshot(path=str(Path(out)/'extension-manager.png'))
    (Path(out)/'extension-manager.txt').write_text(page.locator('body').aria_snapshot(),encoding='utf-8')
    if os.name=='nt':
        mode=page.get_by_text('Developer mode',exact=True).filter(visible=True)
        if not mode.count():page.locator('[aria-label="Extensions menu"]').filter(visible=True).click()
        toggle=page.locator('#dev-switch').filter(visible=True)
        if not toggle.evaluate('(element)=>Boolean(element.checked)'):toggle.click()
        page.mouse.click(500,400)  # Dismiss the responsive sidebar by clicking its backdrop.
        mode.wait_for(state='hidden',timeout=10000)
        (Path(out)/'extension-buttons.json').write_text(json.dumps(page.locator('fluent-button,button,[role=button]').evaluate_all('(elements)=>elements.map(e=>e.outerHTML)'),ensure_ascii=False,indent=2),encoding='utf-8')
        page.screenshot(path=str(Path(out)/'extension-developer-mode.png'))
    else:
        toggle=page.locator('extensions-manager extensions-toolbar #devMode')
        if toggle.get_attribute('aria-pressed')!='true':toggle.click()
    if os.name=='nt':
        from pywinauto import Desktop as NativeDesktop
        native=NativeDesktop(backend='uia').window(handle=int(bound['window']['id'].split(':')[1]))
        (Path(out)/'extension-native-controls.json').write_text(json.dumps([{'name':c.window_text(),'type':c.element_info.control_type} for c in native.descendants()],ensure_ascii=False,indent=2),encoding='utf-8')
        from .vm.input import request
        def click_native(control):
            rect=control.rectangle()
            request('click',point=[(rect.left+rect.right)//2,(rect.top+rect.bottom)//2])
        consent=native.child_window(title='Got it',control_type='Button')
        if consent.exists(timeout=1) and consent.is_visible():
            click_native(consent);consent.wait_not('visible',timeout=10)
        click_native(native.child_window(title='Load unpacked',control_type='Button'))
    else:page.get_by_text('Load unpacked',exact=True).filter(visible=True).click()
    if os.name=='nt':
        from pywinauto import Desktop
        from pywinauto.keyboard import send_keys
        desktop=Desktop(backend='uia')
        time.sleep(1)
        native.capture_as_image().save(str(Path(out)/'extension-native-after-load.png'))
        page.screenshot(path=str(Path(out)/'extension-after-load.png'))
        (Path(out)/'extension-native-windows.json').write_text(json.dumps([{'name':w.window_text(),'class':w.class_name(),'handle':w.handle} for w in desktop.windows()],ensure_ascii=False,indent=2),encoding='utf-8')
        dialog=native.child_window(title_re='(?i).*select.*extension.*',control_type='Window')
        dialog.wait('visible',timeout=10)
        (Path(out)/'extension-picker-windows.json').write_text(json.dumps([{'name':c.window_text(),'type':c.element_info.control_type,'id':c.element_info.automation_id} for c in dialog.descendants()],ensure_ascii=False,indent=2),encoding='utf-8')
        edit=dialog.child_window(auto_id='1152',control_type='Edit')
        click_native(edit);send_keys('^a');send_keys(str(directory),with_spaces=True,pause=.03)
        request('keys',keys='ret');time.sleep(1)
        if dialog.exists() and dialog.is_visible():click_native(dialog.child_window(auto_id='1',control_type='Button'))
    else:
        from .gnome import call
        dialog=until(lambda:next((w for w in entities.snapshot()['windows'] if w['id'] not in before and w['rect'][2]>0),None),10)
        (Path(out)/'extension-dialog.json').write_text(json.dumps(dialog),encoding='utf-8')
        Desktop().activate(dialog)
        call('keys',{'keys':['Control_L','l']})
        time.sleep(.3)
        for char in str(directory):
            call('keys',{'keys':[ord(char)]});time.sleep(.04)
        time.sleep(.3)
        call('keys',{'keys':['Return']});time.sleep(1)
        if any(w['id']==dialog['id'] for w in entities.snapshot()['windows']):
            # Return navigates to the folder; the picker button confirms it.
            action={'pid':dialog['pid'],'active_window':True,'role':'button',
                    'name_pattern':r'^(Select|选择)','op':'click'}
            result=subprocess.run(['/usr/bin/python3',str(Path(__file__).with_name('native_control.py'))],
                                  input=json.dumps(action),text=True,capture_output=True,timeout=12)
            if result.returncode:raise RuntimeError('Extension directory confirmation failed: '+result.stderr[-1000:])
            (Path(out)/'extension-directory-confirmed.json').write_text(result.stdout,encoding='utf-8')
    try:page.get_by_text(name,exact=True).wait_for(timeout=20000)
    except Exception:
        if os.name!='nt':
            call('screenshot',{'path':str(Path(out)/'extension-desktop-failure.png')})
        page.screenshot(path=str(Path(out)/'extension-failure.png'))
        (Path(out)/'extension-failure.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
        raise
    page.screenshot(path=str(Path(out)/'extension-installed.png'))
    page.close()
