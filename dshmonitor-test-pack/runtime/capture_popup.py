"""Capture only the notifier PID created by this test, on its actual display."""
import json,sys,time
from pathlib import Path
if sys.platform=='win32':
    import win32gui,win32process
    from PIL import ImageGrab
    pid=int(sys.argv[1]);output=Path(sys.argv[2])
    for _ in range(60):
        windows=[]
        win32gui.EnumWindows(lambda hwnd,_:windows.append(hwnd) if win32gui.IsWindowVisible(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1]==pid else None,None)
        if len(windows)==1:
            hwnd=windows[0]
            ImageGrab.grab(win32gui.GetWindowRect(hwnd)).save(output)
            print(json.dumps({'title':win32gui.GetWindowText(hwnd),'pid':pid,'screenshot':str(output)},ensure_ascii=True));sys.exit(0)
        time.sleep(.1)
    import psutil
    windows=[]
    win32gui.EnumWindows(lambda h,_:windows.append({'hwnd':h,'title':win32gui.GetWindowText(h),'visible':bool(win32gui.IsWindowVisible(h))}) if win32process.GetWindowThreadProcessId(h)[1]==pid else None,None)
    raise RuntimeError('Own notifier window was not captured: '+json.dumps({'pid':pid,'process_alive':psutil.pid_exists(pid),'windows':windows},ensure_ascii=True))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'test-support'))
from dsh_test_harness.gnome import call
from dsh_test_harness.wait import until
pid=int(sys.argv[1]);output=Path(sys.argv[2])
window=until(lambda:next((w for w in call('snapshot')['windows'] if w['pid']==pid),None),6)
# Independent test-side compositor capture, with no product collector involved.
call('screenshot',{'path':str(output)})
until(lambda:output.exists() and output.stat().st_size>0,2)
print(json.dumps({'title':window['title'],'pid':pid,'screenshot':str(output)}))
