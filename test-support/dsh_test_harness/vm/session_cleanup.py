"""Clean the exact task and profile carried between VM phases, including failed runs."""
import json,sys,shutil,os,socket,http.client
from pathlib import Path

def clean(directory):
    directory=Path(directory);checkpoint=directory/'checkpoint.json'
    browser_record=directory/'browser-profile.json'
    if browser_record.exists():
        shutil.rmtree(Path(json.loads(browser_record.read_text(encoding='utf-8'))))
        browser_record.unlink()
    if not checkpoint.exists():return {'checkpoint':False}
    saved=json.loads(checkpoint.read_text(encoding='utf-8'));task=saved['task']['value']
    config=json.loads((Path(os.environ['PROGRAMDATA'])/'Dafeiyu/config.json').read_text(encoding='utf-8-sig')) if os.name=='nt' else json.loads(Path('/etc/dafeiyu/config.json').read_text())
    def request(route,body):
        if os.name=='nt':conn=http.client.HTTPConnection('127.0.0.1',config['port'],timeout=30)
        else:
            class Unix(http.client.HTTPConnection):
                def connect(self):self.sock=socket.socket(socket.AF_UNIX);self.sock.settimeout(30);self.sock.connect(config['socket'])
            conn=Unix('localhost')
        try:
            conn.request('POST',route,json.dumps(body),{'Content-Type':'application/json','Authorization':'Bearer '+config.get('token','')})
            response=conn.getresponse();value=json.loads(response.read())
            if response.status!=200:raise RuntimeError(value)
            return value
        finally:conn.close()
    status=Path(config['data_dir'])/'status.json'
    live=json.loads(status.read_text(encoding='utf-8')).get('live',[]) if status.exists() else []
    if any(t['id']==task['id'] for t in live):request('/finish',{'task_id':task['id'],'session_id':task['session_id'],'verdict':'cancelled','reason':'跨重启测试资源清理'})
    settings=Path(config['data_dir'])/'settings.json'
    current=json.loads(settings.read_text(encoding='utf-8')) if settings.exists() else {}
    patch={k:v for k,v in saved.get('initial_settings',{}).items() if k in ('instructions','instructions_full','heartbeat_prompt','mascot_size','away_heartbeats','sampling','reporting') and current.get(k)!=v}
    if patch:request('/settings/ui',{'patch':patch})
    def remove_readonly(function,path,error):
        # DSH attachments are intentionally read-only. Only remove this run's
        # disposable profile, after product assertions have already finished.
        import stat
        os.chmod(path,stat.S_IWRITE|stat.S_IREAD);function(path)
    shutil.rmtree(directory,onexc=remove_readonly)
    return {'task_id':task['id'],'profile_removed':True}

if __name__=='__main__':print(json.dumps(clean(sys.argv[1])))
