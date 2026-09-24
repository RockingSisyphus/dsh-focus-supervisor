"""Deterministic window activity facts; no judgement about the user's work."""
from .common import digest
from .time_coverage import split_interval


def activity_changes(samples, evidence, previous=()):
    previous = {row['id']: row for row in previous}
    rows = {}
    last = {}
    streak = {}
    refs = {(record.get('source_sample_id'), record.get('id')): ref for ref,record in evidence.items()}
    for index, sample in enumerate(samples):
        desktop = sample.get('desktop', {})
        if not desktop.get('available'):
            last = {}; streak = {}
            continue
        interval = sample.get('settings', {}).get('sampling', {}).get('interval_seconds', 2)
        following = samples[index+1] if index+1 < len(samples) else None
        seconds, gap = split_interval(sample, following, interval) if following else (0, 0)
        known = following and following.get('desktop', {}).get('available') and seconds > 0
        seconds = seconds if known else 0
        current = {}
        for window in desktop.get('windows', []):
            if window.get('supervisor_owned'):continue
            identity = str(window.get('process', {}).get('identity'))+':'+window['id']
            documents = window.get('browser_documents', [])
            remembered=rows.get(identity,previous.get(identity,{}))
            old=remembered.get('last_state',{})
            body_observed=bool(documents) or bool(window.get('ui_text') and not old.get('urls'))
            body=[d.get('text','') for d in documents] if documents else window.get('ui_text','')
            if window.get('text_scope')=='process_window_group':
                body=sorted(body if isinstance(body,list) else body.splitlines())
            state = {'focused':bool(window.get('focused')), 'visible':window.get('visible'),
                     'body_scope':window.get('text_scope'),
                     'minimized':bool(window.get('minimized')), 'title':window.get('title'),
                     'urls':[d['url'] for d in documents] if documents else old.get('urls',[]),
                     'body':digest(body) if body_observed else old.get('body')}
            current[identity] = state
            row = rows.setdefault(identity, {'id':identity,'window_id':window['id'], 'title':window.get('title'),
                                             'focus_seconds':0,'visible_seconds':0,'longest_focus_seconds':0,
                                             'changes':[], 'evidence_refs':[]})
            prior = last.get(identity)
            if prior is None and index == 0:prior = previous.get(identity,{}).get('last_state')
            if prior is None:
                row['changes'].append({'at':sample['ts'],'type':'observed','state':state})
            else:
                changes={key:state[key] for key in state if state[key]!=prior.get(key)}
                if 'body' in changes:
                    changes.pop('body')
                    if body_observed and prior.get('body') is not None:changes['body_changed']=True
                if changes:row['changes'].append({'at':sample['ts'],'type':'changed','fields':changes})
            row['focus_seconds'] += seconds if state['focused'] else 0
            row['visible_seconds'] += seconds if state['visible'] is True else 0
            streak[identity] = (streak.get(identity,0)+seconds) if state['focused'] else 0
            row['longest_focus_seconds'] = max(row['longest_focus_seconds'],streak[identity])
            row['last_state'] = state
            row['body_scope'] = window.get('text_scope')
            row['last_observed_at'] = sample['ts']
            if body_observed:
                row['last_body_captured_at'] = max([d.get('captured_at',0) for d in documents] or [window.get('text_captured_at',0)]) or None
            ref = refs.get((sample['sample_id'], window['id']))
            if ref and ref not in row['evidence_refs']:row['evidence_refs'].append(ref)
        for identity in last.keys()-current.keys():
            rows[identity]['changes'].append({'at':sample['ts'],'type':'not_in_window_inventory'})
            streak.pop(identity,None)
        last=current
        if not known or gap:streak={};last={}
    for row in rows.values():
        for key in ('focus_seconds','visible_seconds','longest_focus_seconds'):row[key]=round(row[key],3)
    return list(rows.values())
