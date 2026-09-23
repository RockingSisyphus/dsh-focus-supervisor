"""Independent test compositor driver; never used by the production plugin."""
import json,time,os
from .wait import until

def call(operation,arguments=None):
    from focus_demo.native_dbus import NativeBus
    bus=NativeBus()
    try:result=bus.call('org.dsh.TestDesktop','/org/dsh/TestDesktop','org.dsh.TestDesktop','Call','s',[json.dumps({'op':operation,**(arguments or {})})],5000)
    finally:bus.close()
    value=json.loads(result)
    if 'error' in value:raise RuntimeError(value['error'])
    return value

def window(identifier):return next((w for w in call('snapshot')['windows'] if w['id']==identifier),None)

def action(operation,record,**args):
    identifier=record['id'];call(operation,{'window_id':identifier,**args})
    if operation=='activate':return until(lambda:(w if (w:=window(identifier)) and w['focused'] and not w['minimized'] else None))
    if operation=='minimize':return until(lambda:(w if (w:=window(identifier)) and w['minimized'] else None))
    if operation=='restore':return until(lambda:(w if (w:=window(identifier)) and not w['minimized'] else None))
    if operation=='layout':
        # Navigation may finish an earlier Wayland configure after our request.
        # Establish a stable fixture geometry; this never activates the window.
        stable_since=None
        def settled():
            nonlocal stable_since
            w=window(identifier)
            if w and all(abs(a-b)<=2 for a,b in zip(w['rect'],args['rect'])):
                stable_since=stable_since or time.monotonic()
                return w if time.monotonic()-stable_since>=.3 else None
            stable_since=None
            call('layout',{'window_id':identifier,**args})
            return None
        try:return until(settled,10)
        except TimeoutError as error:raise RuntimeError('Compositor layout did not reach '+str(args['rect'])+'; observed '+str(window(identifier))) from error
    return window(identifier)
