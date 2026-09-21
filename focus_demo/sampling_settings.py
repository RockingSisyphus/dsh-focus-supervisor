"""Shared sampling defaults and simple partial-update validation."""
import copy
import json
import math
import sys
from pathlib import Path

SCHEMA=json.loads(Path(__file__).with_name('sampling-settings.json').read_text(encoding='utf-8'))
DEFAULTS={group:{key:spec.get('platform_defaults',{}).get('linux' if sys.platform.startswith('linux') else 'windows',spec['default']) for key,spec in fields.items()} for group,fields in SCHEMA.items()}

def merge(current=None, patch=None):
    result=copy.deepcopy(DEFAULTS)
    for group in DEFAULTS:
        result[group].update((current or {}).get(group,{ }))
    for group,fields in (patch or {}).items():
        if group not in SCHEMA:raise ValueError('未知设置分组：'+group)
        if not isinstance(fields,dict):raise ValueError(group+' 必须是对象')
        for key,value in fields.items():
            spec=SCHEMA[group].get(key)
            if spec is None:raise ValueError('未知设置：'+group+'.'+key)
            if value is None and spec.get('nullable'):pass
            elif (type(value) not in (int,float) or not math.isfinite(value) or value<=0
                  or (spec['integer'] and type(value) is not int)):
                raise ValueError(spec['label']+' 必须是正'+('整数' if spec['integer'] else '数'))
            result[group][key]=value
    return result
