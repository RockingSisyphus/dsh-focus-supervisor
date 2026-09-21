"""Current shared evidence/capture contracts, extracted from the retired demo suite."""
import copy  # 对照冻结记录是否被修改。


import hashlib  # 校验真实图片编码绑定。


import json  # 读取生成提示词。


import time  # 构造可控任务时间。


from pathlib import Path  # 使用临时文件，不修改系统配置。


from types import SimpleNamespace  # 创建最小测试配置。


import pytest  # 参数化断言与临时路径。


from PIL import Image  # 生成明确标记的测试图，不冒充桌面实测。


from focus_demo.prompts import messages_for  # 检验提示词层级。


from focus_demo.reports import EvidenceTools, build_reports, overview  # 使用实际报告算法。


from focus_demo.collectors import associate_window  # 使用实际关联逻辑。


from focus_demo.common import digest  # 比对契约哈希。


def effective(count=26, programs=False, objects=1):  # 功能：明确构造时间轴，用来验证完整统计和分页。
    segments=[];evidence={};position=0  # 不从测试内容反向注入真实采集器。
    for index in range(count):  # 第一段很长，其后短片段很多。
        duration=500 if index==0 else 2  # 复现 v0.1 早期长片段被挤掉的问题。
        group=[]  # 一个片段可有多个并行窗口。
        for number in range(objects):  # 检验对象数量上限是否造成无索引遗漏。
            ref=f'e{index}_{number}';app=f'program_{index if programs else number}'  # 给每个证据清晰身份。
            obj={'ref':ref,'id':f'win:{index}_{number}','kind':'window','app':app,'title':f'真实采集结构的合成测试 {index}/{number}','focused':number==0,'visible':True,'text_preview':'摘要'}  # 模拟数据明确标记为测试。
            group.append(obj);evidence[ref]={**obj,'text':'文'*12000,'ui_text':'界面文字','logs':[{'text':'授权日志'}]}  # 长正文用于分页测试。
        segments.append({'id':f's{index:03d}','duration_seconds':duration,'real_duration_seconds':duration,'relative_start_seconds':position,'relative_end_seconds':position+duration,'objects':group})  # 所有片段保留。
        position+=duration  # 推进合成相对时间。
    return {'segments':segments,'evidence':evidence,'effective_observed_seconds':position,'unobserved_gap_seconds':0,'coverage_notes':['合成测试，不是真实桌面'],'test_time_override':False,'real_start':0,'real_end':position}  # 与真实报告采用同样结构。


def test_full_period_preserves_first_500_seconds():  # 验证早期长活动没有被末尾切换挤掉。
    data=effective();value=overview(data)  # 统计全部 550 秒。
    assert value['effective_observed_seconds']==550  # 全时段分母准确。
    assert value['programs'][0]['observed_seconds']==550  # 同程序覆盖完整区间。
    branch=next(iter(build_reports(data).values()))  # 深入读取完整分支。
    assert branch['events'][0]['seconds']==500 and len(branch['events'])==26  # 最早片段仍能定位。


def test_catalog_can_find_every_program():  # 验证概览以外的程序可分页发现。
    tools=EvidenceTools(effective(40,True));seen=[];offset=0  # 不只测试第一页。
    while offset is not None:  # 沿返回游标继续读取。
        page=tools.call('list_programs',{'offset':offset});seen.extend(p['id'] for p in page['programs']);offset=page['next_offset']  # 与 agent 使用同样接口。
    assert len(set(seen))==40  # 所有程序均可找到。


def test_many_objects_have_discoverable_evidence():  # 同一片段很多对象也不能失去证据目录。
    data=effective(1,False,30)  # 三十个可见程序对象。
    tools=EvidenceTools(data)  # 构建完整目录。
    assert len(tools.programs)==30  # 不在采集时间轴截断到十二个。
    assert sum(len(p['evidence_refs']) for p in tools.programs.values())==30  # 证据全部可索引。


def test_overview_stays_small_for_large_trace():  # 稠密轨迹不把全部正文塞入首轮。
    data=effective(100,True,3)  # 三百条长证据。
    job={'effective':data,'phase':'monitor','test_mode':True}  # 使用真实提示词函数。
    messages=messages_for(job,{'goal':'测试','criteria':[]},[])  # 构建概览而不是全量片段。
    assert len(messages[1]['content'])<15000  # 字符预算不是 token 断言。
    assert json.loads(messages[1]['content'])['overview']['segment_count']==100  # 统计没有省掉早期片段。


def test_same_program_parallel_windows_not_double_counted():  # 同程序两窗口同时展示不能把时长翻倍。
    data=effective(1,False,2)  # 一个五百秒片段。
    for obj in data['segments'][0]['objects']: obj['app']='same'  # 明确同一程序。
    report=overview(data)  # 使用并集统计。
    assert report['programs'][0]['observed_seconds']==500  # 不错误计为一千秒。


def test_text_paging_and_untrusted_paths():  # 工具只访问已保存来源。
    tools=EvidenceTools(effective(1))  # 冻结的历史文本。
    page=tools.call('read_evidence_text',{'reference':'e0_0','offset':4000})  # 自主读第二页。
    assert len(page['text'])==4000 and page['next_offset']==8000  # 有界可继续阅读。
    with pytest.raises(ValueError): tools.call('read_evidence_text',{'reference':'e0_0','source':'/etc/passwd'})  # 不允许任意路径。
    with pytest.raises(ValueError): tools.call('shell',{'command':'anything'})  # 不存在管理员 shell。


def test_ambiguous_native_mapping_refused():  # 相同标题不能任选窗口执行关闭。
    windows=[{'id':'x11:1','app':'Chromium','title':'Same - Chromium','rect':[0,0,800,600],'visible':True,'process':{'exe':'/usr/bin/chromium'}}]  # 两个完全相同的候选。
    windows.append({**windows[0],'id':'x11:2'})  # 明确制造歧义。
    window,note=associate_window({'bounds':{'left':0,'top':0,'width':800,'height':600}},'Same',{'windows':windows})  # 调用实际关联逻辑。
    assert window is None  # 不能据标题强行选择。


def test_screenshot_fingerprint_and_budget(tmp_path):  # 合成图片只检验工具边界，不冒充真实屏幕测试。
    folder=tmp_path/'screenshots';folder.mkdir()  # 限定允许目录。
    image=folder/'test.png';Image.new('RGB',(320,240)).save(image)  # 明确构造测试图。
    fingerprint=hashlib.sha256(image.read_bytes()).hexdigest()  # 校验图片原始字节。
    data=effective(1);data['evidence']['e0_0']['screenshot']={'path':'screenshots/test.png','sha256':fingerprint,'captured_at':100}  # 历史来源元数据。
    tools=EvidenceTools(data,tmp_path)  # 与实际审核相同的图片工具。
    assert tools.call('view_screenshot',{'reference':'e0_0'}).get('_image_base64')  # 支持按需读取图像。
    tools.call('view_screenshot',{'reference':'e0_0'})  # 第二张仍在预算内。
    assert 'error' in tools.call('view_screenshot',{'reference':'e0_0'})  # 第三张不得超预算。
