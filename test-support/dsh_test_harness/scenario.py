"""JSON values, assertions, action dispatch and step artifacts shared by packs."""
import json,time
from datetime import datetime,timezone
MISSING=object()

class ScenarioEngine:
    def __init__(self,case,out,values=None,actions=None,step_delay=0):
        self.case,self.out,self.values,self.actions,self.step_delay=case,out,values or {},actions or {},step_delay
        self.steps=[]
        for key,value in case.get('variables',{}).items():self.values[key]=self.resolve(value)
    def execute(self,step):
        if step['op']=='data.select':
            return [row for row in step['rows'] if all(row.get(key)==value for key,value in step['where'].items())]
        if step['op']=='assert':
            try:actual=self.resolve(step['actual'])
            except (KeyError,IndexError):
                if step['operator']!='exists':raise
                actual=MISSING
            self.compare(actual,step['operator'],self.resolve(step['expected']));return {'passed':True}
        if step['op'] not in self.actions:raise ValueError('Unknown operation '+step['op'])
        return self.actions[step['op']](step)
    def get(self,path):
        value=self.values
        for key in path.split('.'):
            if isinstance(value,list):value=value[int(key)]
            else:value=value[key]
        return value
    def resolve(self,value):
        if isinstance(value,list):return [self.resolve(v) for v in value]
        if isinstance(value,dict):
            if set(value)=={'$concat'}:return ''.join(str(v) for v in self.resolve(value['$concat']))
            if set(value)=={'$ref'}:return self.get(value['$ref'])
            if set(value)=={'$time_after'}:return time.time()+value['$time_after']
            if set(value)=={'$iso_after'}:return datetime.fromtimestamp(time.time()+value['$iso_after'],timezone.utc).isoformat()
            if set(value)=={'$json'}:return json.dumps(self.resolve(value['$json']),ensure_ascii=False)
            if set(value)=={'$merge'}:
                result={}
                for item in self.resolve(value['$merge']):result.update(item)
                return result
            return {k:self.resolve(v) for k,v in value.items()}
        return value
    def compare(self,actual,operator,expected):
        text=lambda v:v if isinstance(v,str) else json.dumps(v,ensure_ascii=False)
        if operator=='equals':ok=actual==expected
        elif operator=='not_equals':ok=actual!=expected
        elif operator=='contains':ok=text(expected) in text(actual)
        elif operator=='not_contains':ok=text(expected) not in text(actual)
        elif operator=='count':ok=len(actual)==expected
        elif operator=='gt':ok=actual>expected
        elif operator=='lt':ok=actual<expected
        elif operator=='exists':ok=(actual is not MISSING)==expected
        else:raise ValueError('Unknown assertion '+operator)
        if not ok:raise AssertionError(f'{operator}: expected {str(expected)[:500]}, actual {str(actual)[:1000]}')
    def run(self):
        for index,raw in enumerate(self.case['steps'],1):
            record={'step':index,'id':raw['id'],'op':raw['op'],'status':'running','started_at':time.time()}
            self.steps.append(record)
            try:
                step=raw if raw['op']=='assert' else self.resolve(raw)
                result=self.execute(step)
                if 'bind' in raw:self.values[raw['bind']]=result
                record.update(status='passed',result=result)
            except Exception as error:
                record.update(status='failed',failure_stage='assertion' if raw['op']=='assert' else 'scenario',error=f'{type(error).__name__}: {error}')
                if not (raw['op']=='assert' and raw.get('continue_on_failure')):
                    self.steps.extend({'step':j,'id':remaining['id'],'op':remaining['op'],'status':'not_run','reason':'An earlier step failed'} for j,remaining in enumerate(self.case['steps'][index:],index+1))
                    raise
            finally:
                record['elapsed_seconds']=round(time.time()-record['started_at'],3)
                (self.out/'steps.json').write_text(json.dumps(self.steps,ensure_ascii=False,indent=2), encoding='utf-8')
            if raw['op']!='assert' and self.step_delay:
                time.sleep(self.step_delay)
        if any(s['status']=='failed' for s in self.steps):raise AssertionError('One or more independent assertions failed; see steps.json')
        return self.steps
