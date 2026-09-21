import ctypes as c
from ctypes import wintypes as w
u=c.WinDLL('user32',use_last_error=True);k=c.WinDLL('kernel32',use_last_error=True)
PROC=c.WINFUNCTYPE(c.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
class WC(c.Structure):
 _fields_=[('style',w.UINT),('proc',PROC),('cbClsExtra',c.c_int),('cbWndExtra',c.c_int),('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),('background',w.HBRUSH),('menu',w.LPCWSTR),('name',w.LPCWSTR)]
u.DefWindowProcW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.DefWindowProcW.restype=c.c_ssize_t
u.CreateWindowExW.argtypes=[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,w.LPVOID];u.CreateWindowExW.restype=w.HWND
for fn in ['ShowWindow','DestroyWindow','SetForegroundWindow','SetFocus','IsWindow']:getattr(u,fn).argtypes=[w.HWND]+([c.c_int] if fn=='ShowWindow' else [])
u.SetWindowTextW.argtypes=[w.HWND,w.LPCWSTR];u.MoveWindow.argtypes=[w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.BOOL]
u.SendMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];u.SendMessageW.restype=c.c_ssize_t
u.GetMessageW.argtypes=[c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT]
u.SetTimer.argtypes=[w.HWND,c.c_size_t,w.UINT,c.c_void_p];u.SetTimer.restype=c.c_size_t
u.TranslateMessage.argtypes=[c.POINTER(w.MSG)]
u.DispatchMessageW.argtypes=[c.POINTER(w.MSG)];u.DispatchMessageW.restype=c.c_ssize_t
u.GetForegroundWindow.restype=w.HWND
k.GetModuleHandleW.restype=w.HMODULE

def focus(h, edit):
 # Only our disposable fixture is activated. Do not modify other applications.
 u.SetForegroundWindow(h);u.SetFocus(edit)
@PROC
def proc(h,m,wp,lp):
 if m==0x10:u.DestroyWindow(h);return 0
 return u.DefWindowProcW(h,m,wp,lp)
