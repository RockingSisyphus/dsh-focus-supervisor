"""model scenario actions; expectations are supplied by JSON."""
import json,os,re,time,socket,http.client,shutil,subprocess,sys,tempfile,threading
from pathlib import Path
from urllib.parse import urlparse
from dsh_test_harness.desktop import Desktop
from dsh_test_harness.wait import until
from ui import *
PACK=Path(__file__).resolve().parents[2];ROOT=PACK.parent

def model_call(self,step):
    op=step["op"];p=self.page;b=self.backend
    return self.model_call(step)

def model_paginate(self,step):
    """Follow the tool's real cursor through DSH, keeping every response."""
    pages=[];offset=0;seen=set()
    while offset is not None:
        if offset in seen:raise AssertionError('Tool repeated pagination cursor: '+str(offset))
        seen.add(offset)
        arguments=dict(step['arguments'])
        nested=json.loads(arguments.get('arguments_json','{}'))
        nested['offset']=offset;arguments['arguments_json']=json.dumps(nested)
        result=self.model_call({**step,'arguments':arguments,'user':step['user']+' '+str(offset)})
        page=result['value'];pages.append(page);offset=page['next_offset']
    return {'pages':pages,'text':''.join(p.get('text','') for p in pages),'count':len(pages),
            'items':[item for page in pages for item in page.get(step.get('items_field','changes'),[])],
            'max_page_chars':max((len(p.get('text','')) for p in pages),default=0),'next_offset':offset}

def model_messages(self,step):
    requests=self.model.requests[-1:] if step.get('latest',True) else self.model.requests
    messages=[m for r in requests for m in r['messages']
              if (not step.get('role') or m.get('role')==step['role'])
              and step.get('contains','') in str(m.get('content',''))]
    if step.get('selection')=='last':messages=messages[-1:]
    text='\n'.join(m.get('content','') if isinstance(m.get('content'),str) else json.dumps(m.get('content'),ensure_ascii=False) for m in messages)
    return {'messages':messages,'text':text,'count':len(messages),'chars':len(text),'bytes':len(text.encode('utf-8'))}

def model_system(self,step):
    op=step["op"];p=self.page;b=self.backend
    texts = [str(message.get('content')) for request in self.model.requests for message in request['messages'] if message.get('role') == 'system']
    return {'text': '\n'.join(texts), 'count': len(texts)}

def model_reply(self,step):
    op=step["op"];p=self.page;b=self.backend
    self.model.reply(step['user'], step['text'])
    editor = p.locator('[contenteditable="true"]')
    editor.fill(step['user'])
    editor.press('Enter')
    p.get_by_text(step['text'], exact=True).wait_for()
    return step['text']

def model_notice(self,step):
    op=step["op"];p=self.page;b=self.backend
    return until(lambda: next((m for req in self.model.requests for m in req['messages'] if m['role'] == 'user' and step['text'] in str(m['content'])), None), 30)

def heartbeat_enable(self,step):
    op=step["op"];p=self.page;b=self.backend
    def respond(text, body):
        rid = re.search('报告编号：([^\\s]+)', text).group(1)
        return self.model.tool_reply('focus_observe', {'report_id': rid, 'decision': step.get('decision', 'on_task'), 'reason': step.get('reason', '固定测试判断，仅验证软件流程。')})
    self.model.heartbeat = respond
    return None

def tool_result(self,step):
    def observed():
        messages=[m for request in self.model.requests for m in request['messages']]
        calls=[]
        for message in messages:
            for call in message.get('tool_calls',[]):
                function=call.get('function',{})
                if function.get('name')!=step['tool']:continue
                arguments=json.loads(function.get('arguments','{}'))
                if all(arguments.get(k)==v for k,v in step.get('arguments',{}).items()):calls.append(call['id'])
        return next((m for m in messages if m.get('role')=='tool' and m.get('tool_call_id') in calls),None)
    return until(observed,step.get('timeout',60))

def registry(scenario):return {
    'model.messages':lambda step:model_messages(scenario,step),
    'model.paginate':lambda step:model_paginate(scenario,step),
    'model.tool_result':lambda step:tool_result(scenario,step),
    'model.call': lambda step: model_call(scenario,step),
    'model.system': lambda step: model_system(scenario,step),
    'model.reply': lambda step: model_reply(scenario,step),
    'model.notice': lambda step: model_notice(scenario,step),
    'heartbeat.enable': lambda step: heartbeat_enable(scenario,step),
}
