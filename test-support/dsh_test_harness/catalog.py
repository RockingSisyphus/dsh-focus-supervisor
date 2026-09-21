"""One catalog for local, guest and multi-platform execution."""
import json

def discover(pack):
    cases=[]; ids=set()
    for path in sorted((pack/'cases').glob('*.json')):
        case=json.loads(path.read_text(encoding='utf-8'))
        if case['id'] in ids:raise ValueError('Duplicate case '+case['id'])
        ids.add(case['id'])
        if case['engine'] not in ('dsh','command'):raise ValueError('Unknown engine '+case['engine'])
        steps=[s['id'] for s in case.get('steps',[])]
        if len(steps)!=len(set(steps)):raise ValueError('Duplicate step ID in '+case['id'])
        case['features']=list(dict.fromkeys(case.get('features',[])+inferred_features(case)))
        cases.append((path,case))
    return cases

def select(cases, ids=None, extended=False, manual=False):
    if ids:
        unknown=set(ids)-{c['id'] for _,c in cases}
        if unknown:raise ValueError('Unknown case: '+', '.join(sorted(unknown)))
        return [(p,c) for p,c in cases if c['id'] in ids]
    groups={'regular'} | ({'extended'} if extended else set()) | ({'manual'} if manual else set())
    return [(p,c) for p,c in cases if c['group'] in groups]


def capability_features(root):
    """Inventory public tools/settings from their definitions, without a second case list."""
    import re
    features=[]
    source=root/'dsh-plugin/chat-host.mjs'
    if source.exists():
        text=source.read_text(encoding='utf-8')
        tools=sorted(set(re.findall(r"tool\(['\"](focus_[a-z_]+)['\"]",text)))
        features.extend({'id':'tool.'+name,'title':name} for name in tools)
        for name,body in re.findall(r"tool\('(focus_[a-z_]+)'(.*?)(?=\n  tool\(|\Z)",text,re.S):
            operations=re.search(r"operation:\{[^}]*enum:\[([^]]+)\]",body)
            if operations:
                features.extend({'id':'tool.'+name+'.'+op,'title':name+' '+op} for op in re.findall(r"'([^']+)'",operations[1]))
        if 'focus_act' in tools:
            features.extend({'id':'tool.focus_act.'+name,'title':'focus_act '+name} for name in ('remind','minimize_window','force_close.process','force_close.window','force_close.browser_tab'))
    source=root/'dsh-plugin/default-prompts.json'
    if source.exists():
        features.extend({'id':'setting.'+key,'title':'设置 '+key} for key in json.loads(source.read_text(encoding='utf-8')))
    return features


def inferred_features(case):
    result=[]
    for step in case.get('steps',[]):
        if step.get('op')=='heartbeat.enable':result.append('tool.focus_observe')
        if step.get('op')=='model.call' and str(step.get('tool','')).startswith('focus_'):
            name='tool.'+step['tool'];result.append(name)
            arguments=step.get('arguments',{})
            if isinstance(arguments,dict) and isinstance(arguments.get('operation'),str):
                result.append(name+'.'+arguments['operation'])
            if step['tool']=='focus_act' and isinstance(arguments,dict):
                action=arguments.get('action')
                if action in ('remind','minimize_window'):result.append(name+'.'+action)
                elif action=='force_close':
                    kind=arguments.get('target_kind','process')
                    if kind in ('process','window','browser_tab'):result.append(name+'.force_close.'+kind)
        if step.get('op')=='ui.settings':
            values=step.get('values',{})
            if isinstance(values,dict) and set(values)=={'$ref'}:values=case.get('variables',{}).get(values['$ref'],{})
            result.extend('setting.'+key for key in values if not key.startswith('$'))
    return result
