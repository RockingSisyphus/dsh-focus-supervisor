"""Browser-tab action targets from system accessibility and optional existing connections."""
import json
from contextlib import closing
import sys
import time
from pathlib import Path
import urllib.request
import psutil
import websocket


def endpoint(pid):
    args=psutil.Process(pid).cmdline()
    port=next((a.split('=',1)[1] for a in args if a.startswith('--remote-debugging-port=')),None)
    if port=='0':
        profile=next((a.split('=',1)[1] for a in args if a.startswith('--user-data-dir=')),None)
        port=(Path(profile)/'DevToolsActivePort').read_text().splitlines()[0] if profile else None
    if port and port.isdecimal() and int(port)>0:return 'http://127.0.0.1:'+port
    return None


def get(origin,path):
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(origin+path,timeout=.6) as response:return json.load(response)


def rpc(url,method,params=None):
    with closing(websocket.create_connection(url,timeout=.6,suppress_origin=True,http_proxy_host=None)) as connection:
        connection.send(json.dumps({'id':1,'method':method,'params':params or {}}))
        while True:
            message=json.loads(connection.recv())
            if message.get('id')==1:
                if 'error' in message:raise RuntimeError(str(message['error']))
                return message.get('result',{})


def capture(windows):
    from focus_demo.native_tabs import capture as native_capture
    result=[];errors=[]
    try:
        native=native_capture(windows)
        for tab in native['tabs']:
            window=next((w for w in windows if w['id']==tab.get('window_id')),None)
            owned=[w for w in windows if w.get('pid')==tab['pid']]
            if not owned:continue
            process=(window or owned[0]).get('process',{})
            document=next(iter(window.get('browser_documents',[])),{}) if window else {}
            result.append({'id':'tab:'+tab['tab_id'], 'kind':'browser_tab',
                'tab_id':tab['tab_id'], 'native_tab':tab['native_tab'],
                'browser_instance_id':str(tab['pid'])+':'+process.get('identity',''),
                'native_window_id':tab.get('window_id'),'native_window_ids':tab.get('window_ids'),
                'a11y_root':tab.get('a11y_root'),'selected':tab['selected'],
                'window_title':window.get('title','') if window else '',
                'window_rect':window.get('rect') if window else None,
                'window_buffer_rect':window.get('buffer_rect') if window else None,
                'process':process,'pid':tab['pid'],'title':tab['title'],
                'url':document.get('url',''),'app':(window or owned[0]).get('app','browser'),
                'focused':window.get('focused',False) if window else None,
                'visible':window.get('visible',False) if window else None,
                'connection_kind':'system_accessibility_tab','source':'system-accessibility'})
        errors.extend(native['errors'])
    except Exception as error:errors.append({'stage':'native_tabs','error':str(error)})
    native_pids={target['pid'] for target in result}
    for pid in dict.fromkeys(w.get('pid') for w in windows if w.get('pid')):
        if pid in native_pids:continue
        try:
            origin=endpoint(pid)
            if not origin:continue
            version=get(origin,'/json/version');tabs=get(origin,'/json/list')
            owned=[w for w in windows if w.get('pid')==pid]
            for tab in tabs:
                if tab.get('type')!='page' or not tab.get('webSocketDebuggerUrl'):continue
                try:
                    visible=rpc(tab['webSocketDebuggerUrl'],'Runtime.evaluate',{'expression':'document.visibilityState','returnByValue':True}).get('result',{}).get('value')=='visible'
                    # Visibility describes the page; it does not invalidate its exact identity.
                    try:
                        info=rpc(version['webSocketDebuggerUrl'],'Browser.getWindowForTarget',{'targetId':tab['id']})
                    except (OSError,ValueError,RuntimeError,websocket.WebSocketException) as error:
                        errors.append({'pid':pid,'tab_id':tab['id'],'stage':'browser_window','error':str(error)})
                        info={}
                    bounds=info.get('bounds',{})
                    # A CDP tab is exact even when Wayland does not expose matching bounds.
                    # Same-title windows require an unambiguous bounds match; otherwise
                    # retain the exact tab/process and leave the native association unknown.
                    matches=[w for w in owned if w.get('title','')==tab.get('title') or w.get('title','').startswith(tab.get('title','')+' - ')]
                    if len(matches)!=1:
                        matches=[w for w in owned if w.get('rect')==[bounds.get(k) for k in ('left','top','width','height')]]
                    window=matches[0] if info and len(matches)==1 else None
                    process=owned[0].get('process',{})
                    result.append({'id':'tab:'+str(pid)+':'+tab['id'],'kind':'browser_tab','tab_id':tab['id'],'browser_instance_id':str(pid)+':'+process.get('identity',''), 'browser_window_id':info.get('windowId'),'native_window_id':window['id'] if window else None,'process':process,'pid':pid,'title':tab.get('title',''),'url':tab.get('url',''),'app':owned[0].get('app','browser'),'focused':window.get('focused',False) if window else False,'visible':visible,'connection_kind':'cdp','source':'existing-browser-connection','native_association': 'matched' if window else 'unavailable; process fallback available'})
                except (OSError,ValueError,RuntimeError,websocket.WebSocketException) as error:
                    errors.append({'pid':pid,'tab_id':tab['id'],'error':str(error)})
        except (OSError,ValueError,RuntimeError,psutil.Error,websocket.WebSocketException) as error:errors.append({'pid':pid,'error':str(error)})
    return {'targets':result,'errors':errors}


def observe(expected):
    if expected.get('native_tab'):
        from focus_demo.native_tabs import observe as native_observe
        return native_observe(expected)
    if expected.get('connection_kind')=='cdp':
        origin=endpoint(expected['process']['pid'])
        if not origin:return {'closed':False,'reason':'浏览器连接不可用'}
        return {'closed':not any(t['id']==expected.get('tab_id') for t in get(origin,'/json/list'))}
    if expected.get('browser_session_id'):
        import subprocess,shutil
        command=shutil.which('bsk') or str(Path.home()/'.local/bin/bsk')
        result=subprocess.run([command,'tab','list','--session',expected['browser_session_id'],'--scope','user','--json'],capture_output=True,text=True,timeout=2,
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:raise RuntimeError('BrowserSkill 标签列表不可用')
        return {'closed':not any(str(t['tab_id'])==str(expected['tab_id']) for t in json.loads(result.stdout)['tabs'])}
    return {'closed':False,'reason':'无法独立确认标签是否消失'}


def close(expected):
    if expected.get('native_tab'):
        from focus_demo.native_tabs import close as native_close
        return native_close(expected)
    if expected.get('connection_kind')!='cdp':return {'closed':False,'reason':'没有可直接关闭用户标签的已有连接'}
    origin=endpoint(expected['process']['pid'])
    if not origin:return {'closed':False,'reason':'浏览器连接不可用'}
    identifier=expected.get('tab_id')
    tabs=get(origin,'/json/list')
    if not any(t['id']==identifier for t in tabs):return {'closed':True,'already_closed':True}
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(origin+'/json/close/'+identifier,timeout=.6) as response:response.read()
    deadline=time.monotonic()+2.5
    while time.monotonic()<deadline:
        if not any(t['id']==identifier for t in get(origin,'/json/list')):return {'closed':True,'tab_id':identifier}
        time.sleep(.05)
    return {'closed':False,'requested':True,'reason':'标签仍存在'}

if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    value=json.load(sys.stdin)
    print(json.dumps(close(value) if sys.argv[1]=='close' else observe(value) if sys.argv[1]=='observe' else capture(value)))
