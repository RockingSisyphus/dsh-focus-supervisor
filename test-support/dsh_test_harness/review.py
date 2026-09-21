"""Headed review of the same scenario, then free inspection until the page closes."""
import json,time
from pathlib import Path

def browser_options(cache, human_review, desktop_env):
    from .desktop import Desktop
    return Desktop().browser_options(True,desktop_env)

def inspect_until_closed(page,out):
    record={'status':'inspecting','automated_actions_finished':True,'started_at':time.time(),'interactions':[]}
    path=out/'human-review.json'
    def save():path.write_text(json.dumps(record,ensure_ascii=False,indent=2), encoding='utf-8')
    def interaction(source,value):
        record['interactions'].append({**value,'at':time.time()});save()
    page.screenshot(path=str(out/'human-review-ready.png'))
    page.expose_binding('__monitorReviewEvent',interaction)
    script="""(() => { if(window.__monitorReviewInstalled)return;window.__monitorReviewInstalled=true;
      for(const type of ['click','change'])document.addEventListener(type,e=>{
        window.__monitorReviewEvent({type,tag:e.target.tagName,role:e.target.getAttribute('role')}).catch(()=>{});
      },true); })();"""
    page.add_init_script(script);page.evaluate(script)
    page.on('crash',lambda:record.update(status='interrupted',reason='browser-crash'))
    save();print('HUMAN_REVIEW_READY：自动场景已执行完，可自由检查真实 DSH；关闭测试页面或窗口后结束。',flush=True)
    try:
        while not page.is_closed():
            if record['status']=='interrupted':raise RuntimeError('Review browser crashed')
            try:page.wait_for_timeout(250)
            except Exception:
                if not page.is_closed():raise
        if record['status']=='interrupted':raise RuntimeError('Review browser crashed')
        record.update(status='closed',reason='page-closed')
    except BaseException:
        record.update(status='interrupted');raise
    finally:
        record['ended_at']=time.time();save()
