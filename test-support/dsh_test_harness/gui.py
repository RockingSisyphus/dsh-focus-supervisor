"""Render platform-neutral test GUI data through native OS widgets."""
import json,os,sys,time,socket,select
from pathlib import Path

def run(path):
    spec=json.loads(path.read_text(encoding='utf-8'))
    log=None
    if spec.get('log_text') is not None:
        log=(path.parent/'fixture.log').open('w',encoding='utf-8')
        log.write(spec['log_text']);log.flush()
    ready=Path(os.environ['DSH_TEST_GUI_READY'])
    children=[]
    if spec.get('child_processes'):
        import subprocess
        for _ in range(spec['child_processes']):children.append(subprocess.Popen([sys.executable,'-c','import time;time.sleep(600)']))
        (ready.parent/'children.json').write_text(json.dumps([c.pid for c in children]))
    channel=socket.socket();channel.bind(('127.0.0.1',0));channel.listen()
    def commands(set_title):
        if not select.select([channel],[],[],0)[0]:return
        with channel.accept()[0] as connection:
            connection.settimeout(5)
            data=json.loads(connection.makefile('rb').readline())
            for index,opts in data['windows'].items():set_title(int(index),opts['title'])
            connection.sendall(b'{}\n')
    def publish_ready():
        ready.write_text(json.dumps({'pid':os.getpid(),'port':channel.getsockname()[1]}))
    if sys.platform=='win32':
        from .win32 import c,w,u,k,WC,proc,focus
        from .win32 import PROC
        @PROC
        def fixture_proc(h,m,wp,lp):
            if m==0x113:
                commands(lambda index,title:u.SetWindowTextW(windows[index][0],title))
                return 0
            if m in (0x211,0x212,0x231,0x232):
                print(json.dumps({'window':int(h),'message':hex(m),'at':time.time()}),flush=True)
            if m==0x10:
                (ready.parent/'close-events.jsonl').open('a').write(json.dumps({'window':int(h),'event':'close','at':time.time()})+'\n')
                if spec.get('close_behavior')=='hang':time.sleep(120)
                if spec.get('close_behavior')=='save_prompt':
                    u.MessageBoxW(h,'Unsaved fixture text','Save changes?',3)
                    return 0
                if spec.get('refuse_close'):return 0
            return proc(h,m,wp,lp)
        u.MessageBoxW.argtypes=[w.HWND,w.LPCWSTR,w.LPCWSTR,w.UINT]
        instance=k.GetModuleHandleW(None);wc=WC(0,fixture_proc,0,0,instance,None,None,c.c_void_p(6),None,'DshTestFixture')
        u.RegisterClassW(c.byref(wc));windows=[]
        for row in spec['windows']:
            h=u.CreateWindowExW(0,'DshTestFixture',row['title'],0x00CF0000,*row['rect'],None,None,instance,None)
            controls=[]
            for i,control in enumerate(row['controls']):
                kind=control['type'];style=0x40000000|0x10000000
                if kind in ('edit','password'):style|=0x800000|0x10000|(0x20 if kind=='password' else 4)
                child=u.CreateWindowExW(0,'STATIC' if kind=='label' else 'EDIT',control['text'],style,12,12+i*72,row['rect'][2]-40,65,h,None,instance,None);controls.append(child)
            u.ShowWindow(h,5);windows.append((h,controls));focus(h,controls[0])
            u.SetTimer(h,1,100,None)
        publish_ready();msg=w.MSG()
        while any(u.IsWindow(h) for h,_ in windows):
            if not u.GetMessageW(c.byref(msg),None,0,0):break
            u.TranslateMessage(c.byref(msg));u.DispatchMessageW(c.byref(msg))
    else:
        import gi
        gi.require_version('Gtk','3.0')
        from gi.repository import Gtk,GLib
        windows=[]
        for row in spec['windows']:
            win=Gtk.Window(title=row['title']);x,y,width,height=row['rect'];win.set_default_size(width,height);
            box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=8);win.add(box);controls=[]
            for control in row['controls']:
                if control['type']=='label':
                    widget=Gtk.Label(label=control['text']);widget.set_line_wrap(True);widget.set_max_width_chars(45)
                else:
                    widget=Gtk.Entry();widget.set_text(control['text']);widget.set_visibility(control['type']!='password')
                box.pack_start(widget,False,False,0);controls.append(widget)
            def closing(widget,event):
                with (ready.parent/'close-events.jsonl').open('a') as log:log.write(json.dumps({'title':widget.get_title(),'event':'close','at':time.time()})+'\n')
                if spec.get('close_behavior')=='hang':time.sleep(120)
                if spec.get('close_behavior')=='save_prompt':
                    dialog=Gtk.MessageDialog(transient_for=widget,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.YES_NO,text='Save changes?')
                    dialog.show_all();return True
                return bool(spec.get('refuse_close'))
            win.connect('delete-event',closing)
            win.show_all();win.present();windows.append((win,controls))
        import ctypes
        bridge=ctypes.CDLL('libatk-bridge-2.0.so.0');bridge.atk_bridge_adaptor_init(None,None)
        def update():
            commands(lambda index,title:windows[index][0].set_title(title))
            return True
        GLib.timeout_add(100,update);publish_ready();Gtk.main()
