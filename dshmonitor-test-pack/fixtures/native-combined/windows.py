"""Real Win32 test windows controlled through a private fixture command file."""
import ctypes as c,json,os,sys,time
from ctypes import wintypes as w
from pathlib import Path
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
config=json.loads(Path(__file__).with_name('window-data.json').read_text(encoding='utf-8'))
u=c.WinDLL('user32',use_last_error=True);k=c.WinDLL('kernel32',use_last_error=True)
PROC=c.WINFUNCTYPE(c.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
class WC(c.Structure):
 _fields_=[('style',w.UINT),('proc',PROC),('cbClsExtra',c.c_int),('cbWndExtra',c.c_int),('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),('background',w.HBRUSH),('menu',w.LPCWSTR),('name',w.LPCWSTR)]
u.DefWindowProcW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.DefWindowProcW.restype=c.c_ssize_t
u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,w.LPVOID];u.CreateWindowExW.restype=w.HWND
for fn in ['ShowWindow','DestroyWindow','IsWindow']:getattr(u,fn).argtypes=[w.HWND]+([c.c_int] if fn=='ShowWindow' else [])
u.SetWindowTextW.argtypes=[w.HWND,w.LPCWSTR];u.MoveWindow.argtypes=[w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.BOOL]
u.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.SendMessageW.restype=c.c_ssize_t
u.GetMessageW.argtypes=[c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT]
u.TranslateMessage.argtypes=[c.POINTER(w.MSG)]
u.DispatchMessageW.argtypes=[c.POINTER(w.MSG)];u.DispatchMessageW.restype=c.c_ssize_t
u.SetTimer.argtypes=[w.HWND,c.c_size_t,w.UINT,c.c_void_p];u.SetTimer.restype=c.c_size_t
k.GetModuleHandleW.restype=w.HMODULE

@PROC
def proc(h,m,wp,lp):
 if m==0x113:apply_command();return 0
 if m==0x10:u.DestroyWindow(h);return 0
 return u.DefWindowProcW(h,m,wp,lp)
instance=k.GetModuleHandleW(None);wc=WC(0,proc,0,0,instance,None,None,c.c_void_p(6),None,'DafeiyuFixture')
u.RegisterClassW(c.byref(wc));windows={};edits={}
log=(root/'fixture.log').open('w',encoding='utf-8');log.write(config['log_marker']+'\n');log.flush()
for key in config['keys']:
 h=u.CreateWindowExW(0,'DafeiyuFixture',config['title'],0x00CF0000,40,40,380,340,None,None,instance,None)
 windows[key]=h
 def child(cls,text,style,x,y,width,height):return u.CreateWindowExW(0,cls,text,0x40000000|style,x,y,width,height,h,None,instance,None)
 child('STATIC',config['group_prefix']+key,0x10000000,12,10,300,25)
 edits[key]=child('EDIT',key+config['edit_suffix'],0x10000000|0x800000|0x10000,12,45,320,45)
 check=child('BUTTON',config['checkbox'],0x10000000|3,12,100,150,26);u.SendMessageW(check,0xF1,1,0)
 child('EDIT',config['password'],0x10000000|0x20,12,140,220,26)
 child('STATIC',config['hidden'],0,12,180,220,26)
 u.SetTimer(h,1,100,None)
(root/'ready.json').write_text(json.dumps({'pid':os.getpid(),'windows':windows}),encoding='utf-8')
last=None;msg=w.MSG()
def apply_command():
 global last
 try:
  data=json.loads((root/'command.json').read_text(encoding='utf-8'))
  if data['id']!=last:
   for key,opts in data['windows'].items():
    h=windows[key]
    if not u.IsWindow(h):continue
    if 'text' in opts:u.SetWindowTextW(edits[key],opts['text'])
    if 'rect' in opts:u.MoveWindow(h,*opts['rect'],True)
    u.ShowWindow(h,6 if opts.get('minimized') else 5 if opts.get('visible',True) else 0)
   log.write('PHASE '+data['id']+'\n');log.flush();last=data['id']
   (root/'applied.json').write_text(json.dumps({'id':last}),encoding='utf-8')
 except (OSError,ValueError):pass
while u.GetMessageW(c.byref(msg),None,0,0):
 u.TranslateMessage(c.byref(msg));u.DispatchMessageW(c.byref(msg))
