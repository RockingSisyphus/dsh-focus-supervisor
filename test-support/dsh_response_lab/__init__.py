"""Loopback-only fixed replies at the real Chat Completions transport boundary."""
import json,threading,time,uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

class FixedModel:
    def __init__(self,directory):
        self.directory=Path(directory);self.directory.mkdir(parents=True)
        self.requests=[];self.responses=[];self.rules=[];self.lock=threading.Lock();self.heartbeat=None;self.files={}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def json_response(self,value,status=200):
                self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(value).encode())
            def do_GET(self):
                file_id=self.path.split('/')[-1]
                if file_id in owner.files:return self.json_response(owner.files[file_id])
                return self.json_response({'error':'unknown test file'},404)
            def do_DELETE(self):
                file_id=self.path.split('/')[-1];owner.files.pop(file_id,None)
                self.json_response({'id':file_id,'object':'file','deleted':True})
            def do_POST(self):
                raw=self.rfile.read(int(self.headers['Content-Length']))
                if self.path=='/v1/files':
                    from email.parser import BytesParser
                    from email.policy import default
                    parts=BytesParser(policy=default).parsebytes(('Content-Type: '+self.headers['Content-Type']+'\r\n\r\n').encode()+raw)
                    part=next(p for p in parts.iter_parts() if p.get_filename())
                    data=part.get_payload(decode=True);file_id='file-test-'+uuid.uuid4().hex
                    (owner.directory/(file_id+'.bin')).write_bytes(data)
                    metadata={'id':file_id,'object':'file','bytes':len(data),'created_at':int(time.time()),'expires_at':int(time.time())+86400,'filename':part.get_filename(),'purpose':'user_data'}
                    owner.files[file_id]=metadata
                    (owner.directory/(file_id+'.json')).write_text(json.dumps(metadata), encoding='utf-8')
                    return self.json_response(metadata)
                if self.path!='/v1/chat/completions':return self.json_response({'error':'unsupported test route'},404)
                body=json.loads(raw)
                with owner.lock:
                    number=len(owner.requests)+1;owner.requests.append(body)
                    # Headers are deliberately never recorded. These are isolated synthetic chats.
                    (owner.directory/f'request-{number:03}.json').write_text(json.dumps(body,ensure_ascii=False,indent=2), encoding='utf-8')
                    conversation=[m for m in body['messages'] if not (m['role']=='user' and isinstance(m.get('content'),str) and m['content'].startswith(('Current runtime context.','<system-reminder>\nA skill is a reusable set of task-specific instructions.')))]
                    last=next((m for m in reversed(conversation) if m['role']=='user'),{})
                    text=last.get('content','')
                    if not isinstance(text,str):text='\n'.join(p.get('text','') for p in text if p.get('type')=='text')
                    message={'role':'assistant','content':'测试回复：本轮操作已处理。','reasoning_content':'这是固定测试回复，不是模型自主判断。'}
                    if conversation[-1]['role']!='tool':
                        for i,(match,response) in enumerate(owner.rules):
                            if match in text:
                                message.update(response);owner.rules.pop(i);break
                        else:
                            if '[大肥鱼心跳：' in text and owner.heartbeat:message.update(owner.heartbeat(text,body))
                    owner.responses.append(message)
                    (owner.directory/f'response-{number:03}.json').write_text(json.dumps(message,ensure_ascii=False,indent=2), encoding='utf-8')
                finish='tool_calls' if message.get('tool_calls') else 'stop'
                self.send_response(200);self.send_header('Content-Type','text/event-stream' if body.get('stream') else 'application/json');self.end_headers()
                try:
                    if body.get('stream'):
                        base={'id':'test-'+str(number),'object':'chat.completion.chunk','created':int(time.time()),'model':body['model']}
                        delta=dict(message)
                        if delta.get('tool_calls'):delta['tool_calls']=[{'index':i,**call} for i,call in enumerate(delta['tool_calls'])]
                        for change,reason in [(delta,None),({},finish)]:
                            chunk={**base,'choices':[{'index':0,'delta':change,'finish_reason':reason}]}
                            self.wfile.write(('data: '+json.dumps(chunk,ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
                        self.wfile.write(b'data: [DONE]\n\n')
                    else:self.wfile.write(json.dumps({'id':'test-'+str(number),'object':'chat.completion','created':int(time.time()),'model':body['model'],'choices':[{'index':0,'message':message,'finish_reason':finish}]}).encode())
                except BrokenPipeError:pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    @property
    def url(self):return f'http://127.0.0.1:{self.server.server_port}/v1'
    def reply(self,match,content,reasoning_content='固定测试思考文本。'):
        with self.lock:self.rules.append((match,{'content':content,'reasoning_content':reasoning_content}))
    def tool(self,match,name,args):
        with self.lock:
            reply=self.tool_reply(name,args);self.rules.append((match,reply));return reply['tool_calls'][0]['id']
    @staticmethod
    def tool_reply(name,args):
        return {'content':None,'tool_calls':[{'id':'call_'+uuid.uuid4().hex[:12],'type':'function','function':{'name':name,'arguments':json.dumps(args,ensure_ascii=False)}}]}
    def close(self):self.server.shutdown();self.server.server_close()
