"""Current shared evidence/capture contracts, extracted from the retired demo suite."""
import copy  # 保护原始测试快照。


import hashlib  # 核验图片内容指纹。


import json  # 读取协议与持久化数据。


import os  # 设置测试文件时刻。


import threading  # 真实并发文件与 HTTP 测试。


import time  # 使用实际本机时钟。


from concurrent.futures import ThreadPoolExecutor  # 并发写入测试。


from types import SimpleNamespace as N  # 有界测试配置。


import pytest  # 明确断言失败，不修改生产证据。


import requests  # 实际本机 HTTP 客户端。


from PIL import Image  # 生成标记为合成的协议图片。


from focus_demo.common import write_json, digest  # 实际持久化与哈希。


from focus_demo.materials import normalise_materials  # 有界资料输入。


from focus_demo.reports import EvidenceTools, overview  # 同一套只读工具。


from focus_demo.prompts import timeline, apply_time_patch  # 真实使用的时间压缩逻辑。


def test_atomic_json_concurrent_and_failed_write(tmp_path):  # 实际文件并发，不用假文件系统。
    path = tmp_path/'record.json'  # 只写测试目录。
    with ThreadPoolExecutor(8) as pool: list(pool.map(lambda i: write_json(path, {'n': i, 'text': '完整中文'*500}), range(64)))  # 多线程不会共用 .tmp 文件。
    value = json.loads(path.read_text()); assert value['text'] == '完整中文'*500  # 不是半写 JSON。
    before = path.read_bytes()  # 保留成功文件。
    with pytest.raises(ValueError): write_json(path, {'nan': float('nan')})  # 非法值不改原文件。
    assert path.read_bytes() == before and len(list(tmp_path.iterdir())) == 1  # 不遗留临时文件。


@pytest.mark.parametrize('items', [None, [{'name': 'x', 'text': 'x', 'path': '/etc/passwd'}], [{'name': 'x', 'text': 'x'*100001}], [{'name': 'x', 'text': 'x'}]*2])  # 非法资料输入。
def test_material_limits(items):  # 不能用工具开放任意磁盘读取。
    with pytest.raises(ValueError): normalise_materials(items)  # 路径、超限、重复均拒绝。


@pytest.mark.parametrize('name,args', [('read_evidence_text', {'reference': [], 'source': 'text'}), ('inspect_evidence', {'references': [{}]}), ('list_programs', {'path': '/etc/passwd'}), ('read_task_material', {}), ('list_programs', {'offset': True})])  # 工具运行时也验证参数。
def test_tool_runtime_schema(name, args):  # 不仅依赖模型遵守 schema。
    tools = EvidenceTools({'segments': [], 'evidence': {}})  # 无外部环境。
    with pytest.raises(ValueError): tools.call(name, args)  # 拒绝非法操作。


def test_current_focus_not_cut_by_background_catalog():  # 大量 GUI 不应挤掉当前焦点。
    current=[{'id':str(i),'focused':False,'visible':False} for i in range(50)]+[{'id':'focus','focused':True,'visible':True}]  # 合成目录。
    result=overview({'current_objects':current,'segments':[]})  # 实际概览构造。
    assert result['current_objects'][0]['id']=='focus' and result['current_objects_omitted']==39  # 保留焦点并明示省略。


def test_sampling_gap_breaks_continuity():  # 断档前后的同一窗口不能合并成持续工作。
    values=[]  # 明确合成四个时刻。
    for n, clock in enumerate([1,2,20,21]):  # 中间十八秒无人观察。
        values.append({'sample_id':n+1,'ts':clock,'mono':clock,'desktop':{'available':True,'windows':[]},'browser':{'available':False,'pages':[]}})  # 不伪造真实环境测试。
    raw=timeline(values,.25)  # 原生产压缩算法。
    assert len(raw['segments'])==2 and raw['unobserved_gap_seconds']==18 and raw['segments'][1]['gap_before_seconds']==18  # 连续性有明确断点。


def test_source_scan_has_no_unbounded_shell_or_process_kill():  # 对新增动作层做最小静态安全门槛，不能代替实机安全认证。
    import inspect  # 读取随包生产源码。
    from focus_demo import actions  # 受限原生窗口执行器。
    source=inspect.getsource(actions)  # 不分析用户其他文件。
    assert 'shell=True' not in source and 'SIGKILL' not in source and 'TerminateProcess' not in source and '_NET_CLOSE_WINDOW' not in source  # 不存在主动升级为强杀的路径。
