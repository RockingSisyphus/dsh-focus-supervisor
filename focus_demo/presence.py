"""OS idle counters only: no keystrokes, pointer coordinates, audio or video."""
import ctypes
import ctypes.util
import os
import sys
import time


def read_presence():
    try:
        if sys.platform == 'win32':
            from ctypes import wintypes
            class LastInput(ctypes.Structure):
                _fields_ = [('cbSize', wintypes.UINT), ('dwTime', wintypes.DWORD)]
            value = LastInput();value.cbSize = ctypes.sizeof(value)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(value)):
                raise OSError('GetLastInputInfo failed')
            idle = ((ctypes.windll.kernel32.GetTickCount() - value.dwTime) & 0xffffffff) / 1000
        elif os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            from .native_dbus import NativeBus
            bus = NativeBus()
            try:
                idle = bus.call('org.gnome.Mutter.IdleMonitor', '/org/gnome/Mutter/IdleMonitor/Core',
                                'org.gnome.Mutter.IdleMonitor', 'GetIdletime', '', (), 1000) / 1000
            finally:bus.close()
        else:
            x = ctypes.CDLL(ctypes.util.find_library('X11'))
            ss = ctypes.CDLL(ctypes.util.find_library('Xss'))
            class Info(ctypes.Structure):
                _fields_ = [('window', ctypes.c_ulong), ('state', ctypes.c_int), ('kind', ctypes.c_int),
                            ('since', ctypes.c_ulong), ('idle', ctypes.c_ulong), ('mask', ctypes.c_ulong)]
            x.XOpenDisplay.argtypes=[ctypes.c_char_p];x.XOpenDisplay.restype=ctypes.c_void_p
            x.XDefaultRootWindow.argtypes=[ctypes.c_void_p];x.XDefaultRootWindow.restype=ctypes.c_ulong
            x.XCloseDisplay.argtypes=[ctypes.c_void_p]
            ss.XScreenSaverQueryInfo.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(Info)]
            display=x.XOpenDisplay(None)
            if not display:raise OSError('No X11 display')
            try:
                value=Info()
                if not ss.XScreenSaverQueryInfo(display,x.XDefaultRootWindow(display),ctypes.byref(value)):
                    raise OSError('XScreenSaverQueryInfo failed')
                idle=value.idle/1000
            finally:x.XCloseDisplay(display)
        now=time.time()
        return {'available':True,'observed_at':now,'idle_seconds':idle,'last_input_at':now-idle}
    except Exception as error:
        return {'available':False,'observed_at':time.time(),'error':str(error)}
