"""Operate real AT-SPI controls, scoped to the requested application's own bus."""
import json,sys,time,re
from collections import deque
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from focus_demo.atspi_dbus import Bus,ROOT,ACCESSIBLE

ALIASES={'button':'push button','entry':'text'}

def main():
    request=json.load(sys.stdin);bus=Bus(8)
    def call(node,interface,method,signature='',*args):return bus.call(*node,interface,method,signature,*args)
    def label(node):
        value=call(node,'org.freedesktop.DBus.Properties','GetAll','s',ACCESSIBLE).get('Name','')
        return value.get('data','') if isinstance(value,dict) else value
    def state(node,bit):
        bits=call(node,ACCESSIBLE,'GetState')
        return bool(bits and bits[bit//32] & (1<<(bit%32)))
    try:
        owners=[]
        for name in bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames'):
            if not name.startswith(':'):continue
            try:pid=bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID','s',name)
            except RuntimeError:continue
            if request.get('pid') is None or pid==request['pid']:owners.append((name,ROOT))
        queue=deque()
        while not queue and time.monotonic()<bus.deadline:
            for app in owners:
                try:
                    if request.get('active_window') or request.get('window_name'):
                        frames=call(app,ACCESSIBLE,'GetChildren')
                        queue.extend(f for f in frames if (not request.get('active_window') or state(f,1)) and (not request.get('window_name') or label(f)==request['window_name']))
                    else:queue.append(app)
                except RuntimeError:continue
            if not queue:time.sleep(.1)
        while queue and time.monotonic()<bus.deadline:
            node=queue.popleft()
            try:role=call(node,ACCESSIBLE,'GetRoleName');name=label(node)
            except RuntimeError:continue
            match=(not request.get('focused') or state(node,12)) and (not request.get('name') or request['name']==name) and (not request.get('name_pattern') or re.search(request['name_pattern'],name)) and (not request.get('role') or ALIASES.get(request['role'],request['role'])==ALIASES.get(role,role))
            if match:
                op=request['op'];result={'name':name,'role':role}
                if op=='focus':
                    if not call(node,'org.a11y.atspi.Component','GrabFocus'):raise RuntimeError('Native control rejected focus')
                    result['focused']=True
                elif op=='probe':result.update(found=True,rect=call(node,'org.a11y.atspi.Component','GetExtents','u',0))
                elif op=='click':
                    if not call(node,'org.a11y.atspi.Action','DoAction','i',0):raise RuntimeError('Native action rejected')
                    result['clicked']=True
                elif op in ('fill','read'):
                    if op=='fill':
                        if not call(node,'org.a11y.atspi.EditableText','SetTextContents','s',request['text']):raise RuntimeError('Native text input rejected')
                        result['filled']=True
                    result['input_text']=call(node,'org.a11y.atspi.Text','GetText','ii',0,-1)
                else:raise ValueError('Unknown native action '+op)
                print(json.dumps(result));return
            if role not in ('document web','document frame'):
                try:queue.extend(call(node,ACCESSIBLE,'GetChildren'))
                except RuntimeError:pass
        raise RuntimeError('Accessible control not found in target process')
    finally:bus.close()

if __name__=='__main__':main()
