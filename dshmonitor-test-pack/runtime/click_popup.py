"""Click the real native reminder button; no X11 and no handler injection."""
import json,os,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'test-support'))
pid=int(sys.argv[1]);mode=sys.argv[2] if len(sys.argv)>2 else 'click'
if sys.platform=='win32':
    if mode=='keys':
        from pywinauto.keyboard import send_keys
        send_keys('{SPACE}{ENTER}')
    else:
        # The production Windows popup draws its button on a Tk canvas.
        # Locate the rendered blue button in a real window capture.
        import win32gui
        from PIL import ImageGrab
        import win32process
        matches=[]
        win32gui.EnumWindows(lambda hwnd,_:matches.append(hwnd) if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1]==pid else None,None)
        if len(matches)!=1:raise RuntimeError('Reminder process has no unique visible native window')
        hwnd=matches[0]
        left,top,right,bottom=win32gui.GetWindowRect(hwnd)
        bitmap=ImageGrab.grab((left,top,right,bottom)).convert('RGB')
        rows=[]
        for y in range(bitmap.height//2,bitmap.height):
            xs=[x for x in range(bitmap.width) if sum(abs(a-b) for a,b in zip(bitmap.getpixel((x,y)),(169,206,255)))<15]
            if len(xs)>100:rows.append((y,min(xs),max(xs)))
        if not rows:raise RuntimeError('Rendered reminder button not found')
        y,x1,x2=rows[len(rows)//2]
        from dsh_test_harness.vm.input import request
        point=[left+(x1+x2)//2,top+y]
        hit=win32gui.GetAncestor(win32gui.WindowFromPoint(tuple(point)),2)
        print(json.dumps({'pid':pid,'hwnd':hwnd,'rect':[left,top,right,bottom],'point':point,'hit_window':hit,'hit_title':win32gui.GetWindowText(hit),'hit_class':win32gui.GetClassName(hit),'hit_pid':win32process.GetWindowThreadProcessId(hit)[1]}),flush=True)
        request('click',point=point)
        print(json.dumps({'after_click_cursor':win32gui.GetCursorPos(),'foreground':win32gui.GetForegroundWindow(),'popup_present':win32gui.IsWindow(hwnd)}),flush=True)
else:
    if mode=='keys':
        from dsh_test_harness.gnome import call
        call('keys',{'keys':['space']});call('keys',{'keys':['Return']})
    else:
        from dsh_test_harness.gnome import call
        window=next(w for w in call('snapshot')['windows'] if w['pid']==pid)
        call('activate',{'window_id':window['id']})
        host=os.environ.get('DSH_TEST_DESKTOP_DRIVER')=='host'
        result=subprocess.run(['/usr/bin/python3',str(Path(__file__).resolve().parents[2]/'test-support/dsh_test_harness/native_control.py')],input=json.dumps({'pid':pid,'op':'click' if host else 'probe','role':'push button','name':'知道了，我去监工聊天里解释 / 继续任务'}),text=True,capture_output=True,check=True,timeout=12)
        control=json.loads(result.stdout)
        if not host:
            x,y,width,height=control['rect']
            call('click',{'x':x+width//2,'y':y+height//2})
        print(json.dumps({'clicked':True,'control':control},ensure_ascii=False))
