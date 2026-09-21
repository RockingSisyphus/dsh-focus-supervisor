"""Guest desktop input and live progress over one HTTP request/response channel."""
import json,os,time,threading
from contextlib import contextmanager


def _send(operation,timeout,arguments):
    import urllib.request
    body=json.dumps({'operation':operation,**arguments}).encode()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request=urllib.request.Request(os.environ['DSH_TEST_VM_INPUT_URL'],data=body,headers={'Content-Type':'application/json'})
    with opener.open(request,timeout=timeout) as response:value=json.load(response)
    if value.get('error'):raise RuntimeError(value['error'])
    return value


def request(operation,timeout=30,**arguments):
    return _send(operation,timeout,arguments)


def execute(vm,value,out=None):
    response={}
    try:
        if value['operation']=='progress':
            pending=out/'progress.tmp'
            pending.write_text(json.dumps(value['summary'],ensure_ascii=False,indent=2),encoding='utf-8')
            pending.replace(out/'progress.json')
            print('VM:',value['summary']['counts'],flush=True)
        elif value['operation']=='authorize':
            from .authorization import accept_windows
            response['authorization']=accept_windows(vm,out or vm.directory,accept=value.get("accept",True))
        elif value['operation'] in ('click','drag'):
            mouse=vm.mouse
            mouse.mouseMove(*value['point']);mouse.pause(.1);mouse.mouseDown(1);mouse.pause(.1)
            if value['operation']=='drag':
                mouse.mouseMove(*value['destination']);mouse.pause(.1)
            mouse.mouseUp(1)
            response['transport_connected']=bool(mouse.protocol.transport.connected)
        elif value['operation']=='cleanup_processes':
            source='import psutil,json\nrows='+repr(value['processes'])+'\nfor row in rows:\n try:\n  p=psutil.Process(row["pid"])\n  if p.create_time()==row["created_at"]:p.terminate()\n except psutil.NoSuchProcess:pass\n'
            vm.python(source)
        elif value['operation']=='file_acl':
            # Diagnostic metadata only; never read evidence contents on behalf of DSH.
            source="import json,win32security\npaths="+repr(value['paths'])+"\n"+"""
rows=[]
for path in paths:
    try:
        sd=win32security.GetFileSecurity(path,7)
        rows.append({'path':path,'sddl':win32security.ConvertSecurityDescriptorToStringSecurityDescriptor(sd,1,7)})
    except Exception as error:
        rows.append({'path':path,'error':str(error)})
print(json.dumps(rows))
"""
            response['acl']=json.loads(vm.python(source))
        elif value['operation']=='task_pause':
            port=int(value['port']);seconds=float(value['seconds'])
            source=f"""import psutil,time,json
processes=[psutil.Process(c.pid) for c in psutil.net_connections(kind='tcp') if c.status=='LISTEN' and c.laddr.port=={port}]
suspended=[]
try:
    for process in processes:process.suspend();suspended.append(process)
    time.sleep({seconds})
finally:
    for process in suspended:process.resume()
print(json.dumps([p.pid for p in suspended]))
"""
            response['paused_pids']=json.loads(vm.python(source,timeout=seconds+20))
        elif value['operation']=='task_restart':
            name=value['name'].replace("'","''")
            port=int(value['port'])
            script=f"""$ErrorActionPreference='Stop'
$owners=@(Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object -ExpandProperty OwningProcess -Unique)
$old=@($owners | ForEach-Object {{Get-Process -Id $_}})
Stop-ScheduledTask -TaskName '{name}'
foreach($process in $old) {{if(!$process.WaitForExit(10000)){{throw 'Previous service listener did not exit'}}}}
Start-ScheduledTask -TaskName '{name}'
$owners | ConvertTo-Json -Compress
"""
            response['previous_listener_pids']=json.loads(vm.powershell(script,25))
        elif value['operation']=='move_file':
            source=value['source'].replace("'","''");destination=value['destination'].replace("'","''")
            vm.powershell("$ErrorActionPreference='Stop'; Move-Item -LiteralPath '"+source+"' -Destination '"+destination+"'")
        elif value['operation']=='keys':vm.hmp('sendkey '+value['keys'])
        elif value['operation']=='screenshot':
            from PIL import Image
            import tempfile
            from pathlib import Path
            with tempfile.TemporaryDirectory(prefix='dsh-display-') as directory:
                path=Path(directory)/'frame.ppm'
                vm.hmp('screendump '+str(path))
                with Image.open(path) as frame:frame.save(out/(value['name']+'-failure-display.png'))
        else:raise ValueError('Unknown VM input operation')
        response['sent']=True
    except Exception as error:response['error']=str(error)
    return response


@contextmanager
def desktop_input(vm,out=None):
    """Use HTTP correlation, not shared files that Windows can hold open."""
    from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            result=execute(vm,value,out)
            if out is not None and value['operation'] in ('click','drag'):
                with (out/'physical-input.jsonl').open('a') as log:log.write(json.dumps({'at':time.time(),'vm':str(vm.directory),'request':value,'result':result})+'\n')
            self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
            self.wfile.write(json.dumps(result).encode())
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:yield 'http://10.0.2.2:'+str(server.server_port)
    finally:
        server.shutdown();server.server_close();worker.join()
        mouse=vars(vm).pop('mouse',None)
        if mouse is not None:mouse.disconnect()
