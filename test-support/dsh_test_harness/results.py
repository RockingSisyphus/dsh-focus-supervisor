"""Report observed results without promoting contracts to product acceptance."""
import json
from datetime import datetime
from pathlib import Path

def write_report(out, rows, features=(), previous=None, catalog=()):
    out.mkdir(parents=True,exist_ok=True)
    counts={s:sum(r['status']==s for r in rows) for s in ('passed','failed','skipped','not_run')}
    value={'created_at':datetime.now().astimezone().isoformat(),'status':'failed' if counts['failed'] else 'not_run' if counts['not_run'] or not rows else 'passed' if counts['passed'] else 'skipped',
           'counts':counts,'cases':rows,'automated_passed':counts['passed'],'automated_failed':counts['failed']}
    # Every platform/layer is measured independently; previous runs never fill gaps.
    catalog=list(catalog)
    feature_map={f['id']:dict(f) for f in features}
    for case in catalog+list(rows):
        for name in case.get('features',[]):
            feature_map.setdefault(name,{'id':name,'title':name})
    platforms=sorted({p for c in catalog for p in c.get('platforms',[])} | {r['platform'] for r in rows if r.get('platform')}) or ['unknown']
    layers=('unit','protocol','desktop','dsh','real_ai')
    definitions={c['id']:c for c in catalog}
    def layer(case):
        definition=definitions.get(case['id'],{})
        return case.get('verification_layer') or definition.get('verification_layer') or {'product':'dsh','desktop-contract':'desktop','contract':'protocol'}.get(case.get('verification'),'protocol')
    def status_of(observed,missing):
        if any(r['status']=='failed' for r in observed):return 'failed'
        if missing or not observed or any(r['status']=='not_run' for r in observed):return 'not_run'
        if all(r['status']=='passed' for r in observed):return 'passed'
        return 'skipped'
    matrix=[];coverage=[]
    for f in feature_map.values():
        cells=[]
        for platform in platforms:
            for level in layers:
                expected={c['id'] for c in catalog if f['id'] in c.get('features',[]) and platform in c.get('platforms',[]) and layer(c)==level}
                observed=[r for r in rows if f['id'] in r.get('features',[]) and r.get('platform','unknown')==platform and layer(r)==level]
                missing=expected-{r['id'] for r in observed}
                cell={'feature':f['id'],'platform':platform,'layer':level,'status':status_of(observed,missing),
                      'cases':[{'id':r['id'],'status':r['status'],'run':r.get('run'),'evidence':r.get('evidence'),'failure_stage':r.get('failure_stage')} for r in observed],
                      'not_run':sorted(missing),'mapped':bool(expected or observed)}
                cells.append(cell);matrix.append(cell)
        # Retain the old product-only summary field, now across all expected platforms.
        product=[c for c in cells if c['layer']=='dsh' and c['mapped']]
        observed=[r for r in rows if f['id'] in r.get('features',[]) and r.get('verification')=='product']
        coverage.append({**f,'status':status_of(product,not product),'cases':[r['id'] for r in observed],
                         'not_run':sorted({p+':'+name for c in cells if c['layer']=='dsh' for p in [c['platform']] for name in c['not_run']})})
    value['coverage_matrix']=matrix
    old={(r.get('platform'),r['id']):r for r in (previous or {}).get('cases',[])}
    value['regressions']=[r['id'] for r in rows if r['status']=='failed' and old.get((r.get('platform'),r['id']),{}).get('status')=='passed']
    value['layers']={layer:{status:sum(r.get('verification')==layer and r['status']==status for r in rows) for status in counts} for layer in sorted({r.get('verification','unknown') for r in rows})}
    value['verification_layers']={level:{status:sum(layer(r)==level and r['status']==status for r in rows) for status in counts} for level in layers}
    value['features']=coverage
    value['all_features_verified']=bool(coverage) and all(f['status']=='passed' for f in coverage)
    (out/'summary.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 监工测试结果','', '契约检查与真实产品流程分别计数；未执行不等于通过。','', '| 平台 | 用例 | 验证层 | 结果 | 失败阶段 | 说明 | 轮次与证据 |','|---|---|---|---|---|---|---|']
    for r in rows:
        fields=[r.get('platform',''),r['id'],layer(r),r['status'],r.get('failure_stage',''),r.get('error',r.get('reason',''))]
        links=[]
        if r.get('run'):links.append('[轮次](<'+r['run']+'>)')
        if r.get('evidence'):
            folder=Path(r['evidence'])
            for name,label in (('steps.json','步骤'),('result.json','结果'),('junit.xml','契约')):
                if (folder/name).is_file():links.append('['+label+'](<'+str(folder/name)+'>)')
        lines.append('| '+' | '.join(str(x).replace('|','/').replace('\n',' ')[:500] for x in fields)+' | '+' · '.join(links)+' |')
    lines+=['','## 能力覆盖（本轮）','','真实 AI 判断质量独立统计；固定模型回复只计入完整 DSH。未映射不等于不适用。','',
            '| 能力 | 平台 | 单元 | 协议 | 真实桌面 | 完整 DSH | 真实 AI |','|---|---|---|---|---|---|---|']
    for f in feature_map.values():
        for platform in platforms:
            cells=[c for c in matrix if c['feature']==f['id'] and c['platform']==platform]
            lines.append('| '+' | '.join([f['id'],platform]+[c['status']+('（未映射）' if not c['mapped'] else '') for c in cells])+' |')
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return value
