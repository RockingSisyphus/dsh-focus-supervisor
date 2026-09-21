"""Host fixture driver using already-loaded independent desktop extensions.

Unique fixture markers bind stable GNOME IDs to Codex native IDs before titles
change. Only test setup uses this driver; product actions use the installed service.
"""
import ast,json,subprocess,time,uuid
from pathlib import Path

_ids={}
SERVICE='com.openai.Codex.WindowControl'

def native(method,*arguments):
    text=subprocess.check_output(['gdbus','call','--session','--dest',SERVICE,'--object-path','/com/openai/Codex/WindowControl','--method',SERVICE+'.'+method,*map(str,arguments)],text=True,timeout=5).strip()
    if text.startswith('(true,'):text='(True,'+text[6:]
    elif text.startswith('(false,'):text='(False,'+text[7:]
    result=ast.literal_eval(text)
    if method in ('ListWindows','GetMonitorLayout'):return json.loads(result[0])
    if not result[0]:raise RuntimeError(result[1])
    return result

def snapshot():
    data=json.loads((Path.home()/'.cache/tabfocus-demo/gnome-snapshot.json').read_text())
    if time.time()-data['ts']>3:raise RuntimeError('Independent host desktop observer is not updating')
    live=native('ListWindows');byid={w['window_id']:w for w in live}
    rows=[]
    for w in data['windows']:
        if w['id'] not in _ids:
            matches=[n for n in live if n['pid']==w['pid'] and n['title']==w['title']]
            if len(matches)==1:_ids[w['id']]=matches[0]['window_id']
        n=byid.get(_ids.get(w['id']))
        if n:
            r=n['bounds'];rows.append({**w,'focused':n['focused'],'minimized':n['hidden'],'rect':[r[k] for k in ('x','y','width','height')],'workspace':n['workspace'],'client_type':n['client_type']})
    layout=native('GetMonitorLayout')
    monitors=layout['monitors'] if isinstance(layout,dict) else layout
    return {'backend':'gnome-wayland','test_driver':'host-existing-extensions','active_workspace':next((w['workspace'] for w in rows if w['focused']),None),'at':data['ts'],'screen':[max(m['x']+m['width'] for m in monitors),max(m['y']+m['height'] for m in monitors)],'windows':rows}

def call(operation,arguments=None):
    arguments=arguments or {}
    if operation=='snapshot':return snapshot()
    if operation=='keys':
        keys=arguments['keys']
        if len(keys)==1 and (isinstance(keys[0],int) or len(keys[0])==1):
            text=chr(keys[0]) if isinstance(keys[0],int) else keys[0]
            subprocess.run(['ydotool','type','--',text],check=True,capture_output=True,timeout=5)
        else:
            aliases={'Control_L':'LEFTCTRL','Shift_L':'LEFTSHIFT','Alt_L':'LEFTALT','Super_L':'LEFTMETA','Return':'ENTER','Escape':'ESC','space':'SPACE'}
            names=['KEY_'+aliases.get(key,key.upper()) for key in keys]
            codes=json.loads(subprocess.check_output(['/usr/bin/python3','-c','import json,sys;from evdev import ecodes;print(json.dumps([ecodes.ecodes[n] for n in json.loads(sys.argv[1])]))',json.dumps(names)],text=True,timeout=5))
            subprocess.run(['ydotool','key',*[str(code)+':1' for code in codes],*[str(code)+':0' for code in reversed(codes)]],check=True,capture_output=True,timeout=5)
        return {'keys':keys}
    if operation=='screenshot':
        import tempfile,shutil
        with tempfile.NamedTemporaryFile(prefix='computer-use-linux-gnome-extension-',suffix='.png') as capture:
            native('CaptureScreenshot',capture.name)
            shutil.copyfile(capture.name,arguments['path'])
        return {'path':arguments['path']}
    identifier=arguments['window_id'];snapshot()
    native_id=_ids[identifier]
    if operation=='activate':native('ActivateWindow',native_id)
    elif operation=='layout':
        x,y,width,height=arguments['rect'];native('MoveWindow',native_id,x,y);native('ResizeWindow',native_id,width,height)
    elif operation in ('minimize','restore'):
        row=next(w for w in snapshot()['windows'] if w['id']==identifier)
        request={'id':uuid.uuid4().hex,'window_id':identifier,'title':row['title'],'action':'minimize' if operation=='minimize' else 'unminimize','expires_at':time.time()+2}
        from focus_demo.common import write_json
        write_json(Path.home()/'.cache/tabfocus-demo/window-action.json',request)
    else:raise ValueError('Host fixture driver does not support '+operation)
    return snapshot()


from contextlib import contextmanager

@contextmanager
def input_session(out):
    """Own a temporary hardware-input device for explicitly requested host tests."""
    import os,tempfile,shutil
    from .wait import until
    with tempfile.TemporaryDirectory(prefix='dsh-host-input-') as directory, (Path(out)/'host-input.log').open('w') as log:
        socket=Path(directory)/'input.sock'
        process=subprocess.Popen(['ydotoold','--mouse-off','--socket-path='+str(socket)],stdout=log,stderr=subprocess.STDOUT)
        previous=os.environ.get('YDOTOOL_SOCKET')
        ibus=shutil.which('ibus')
        engine=subprocess.check_output([ibus,'engine'],text=True,timeout=5).strip() if ibus else None
        def select_engine(target):
            result=subprocess.run([ibus,'engine',target],capture_output=True,text=True,timeout=5)
            actual=subprocess.check_output([ibus,'engine'],text=True,timeout=5).strip()
            log.write(json.dumps({'requested_engine':target,'actual_engine':actual,'exit_code':result.returncode,'stderr':result.stderr})+'\n');log.flush()
            if actual!=target:raise RuntimeError('Input engine did not switch to '+target)
        try:
            def ready():
                if process.poll() is not None:raise RuntimeError('Host input device failed; see host-input.log')
                return socket.exists()
            until(ready,5)
            os.environ['YDOTOOL_SOCKET']=str(socket)
            if engine:select_engine('xkb:us::eng')
            yield
        finally:
            try:
                if engine:select_engine(engine)
            finally:
                if previous is None:os.environ.pop('YDOTOOL_SOCKET',None)
                else:os.environ['YDOTOOL_SOCKET']=previous
                process.kill();process.wait()
