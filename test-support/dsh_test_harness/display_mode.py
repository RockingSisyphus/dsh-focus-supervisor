"""Set and restore a real Wayland test display through Mutter's display API."""
import json,sys
from gi.repository import Gio,GLib

request=json.load(sys.stdin)
proxy=Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SESSION,0,None,'org.gnome.Mutter.DisplayConfig','/org/gnome/Mutter/DisplayConfig','org.gnome.Mutter.DisplayConfig',None)
def state():return proxy.call_sync('GetCurrentState',None,0,5000,None).unpack()
s=state();current={m[0][0]:next(mode[0] for mode in m[1] if mode[-1].get('is-current')) for m in s[1] if any(mode[-1].get('is-current') for mode in m[1])}
previous=[[*logical[:5],[(spec[0],current[spec[0]],{}) for spec in logical[5]]] for logical in s[2]]
configuration=request.get('restore')
if configuration is None:
    configuration=json.loads(json.dumps(previous))
    connector=configuration[0][5][0][0]
    monitor=next(m for m in s[1] if m[0][0]==connector)
    mode=next((mode[0] for mode in monitor[1] if list(mode[1:3])==request['size']),None)
    if mode is None:raise ValueError('Requested display size is not supported: '+str(request['size']))
    configuration[0][5][0][1]=mode
    configuration[0][2]=1.0
proxy.call_sync('ApplyMonitorsConfig',GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})',(s[0],1,configuration,{})),0,10000,None)
actual=state()
print(json.dumps({'previous':previous,'logical':actual[2]},default=str))
