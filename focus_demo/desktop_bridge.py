"""On-demand GNOME desktop protocol. No snapshot files or polling fallback."""
import json,os,uuid,threading
from pathlib import Path
from .native_dbus import NativeBus
VERSION='dafeiyu-13'
NAME='org.dafeiyu.Desktop'
PATH='/org/dafeiyu/Desktop'
_capture=threading.local()

def runtime_directory():
    runtime=os.environ.get('XDG_RUNTIME_DIR')
    if not runtime:raise RuntimeError('未连接用户桌面运行时目录')
    return Path(runtime)/'dafeiyu-desktop'

def call(operation,arguments=None,timeout=3000):
    request={'op':operation,'id':uuid.uuid4().hex,**(arguments or {})}
    # Keep the pixel consumer's connection alive until it has read and released
    # the files. Dropping the final GIO reference signals owner disappearance.
    bus=getattr(_capture,'bus',None) if operation=='release' else None
    bus=bus or NativeBus()
    keep=False
    try:
        result=json.loads(bus.call(NAME,PATH,NAME,'Call','s',[json.dumps(request)],timeout))
        if result.get('request_id')!=request['id']:raise RuntimeError('桌面响应请求编号不匹配')
        if result.get('error'):raise RuntimeError(result['error'])
        if result.get('code_version')!=VERSION:raise RuntimeError('GNOME 扩展尚未加载当前版本，请重新登录')
        if operation=='capture':
            _capture.bus=bus;keep=True
        return result
    finally:
        if not keep:bus.close()
        if operation=='release':_capture.bus=None
