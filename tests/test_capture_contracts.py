"""Current shared evidence/capture contracts, extracted from the retired demo suite."""
import base64  # 核验多模态字节而非文字占位。


import copy  # 确认读取不改原始证据。


import hashlib  # 核验冻结图像。


import json  # 解析实际请求结构。


import os  # 创建真实本进程日志。


import sys  # 注入仅用于测试的系统接口替身。


import time  # 测试时间绑定。


from pathlib import Path  # 全部写入 pytest 临时目录。


from types import SimpleNamespace as N  # 构建有限配置与接口替身。


import pytest  # 测试断言。


from PIL import Image  # 生成明确标记的测试像素。


from focus_demo.reports import EvidenceTools, build_reports, overview  # 分层报告接口。


from focus_demo.details import DetailCollector  # 系统级取证器。


from focus_demo.platforms import process_info  # 实际进程身份。


from focus_demo.generic_logs import GenericLogs, tail_file  # 通用日志读取。


from focus_demo.collectors import Collector  # 默认不依赖 CDP。


from focus_demo.ui_probe import linux_batch  # Linux 通用无障碍遍历。


def evidence(tmp_path):  # 功能：仅为协议测试创建可区分的整屏图与窗口图。
    shots=[]  # 各图片有不同字节，避免误判为相同对象。
    for i, size in enumerate([(400,200),(90,90)]):  # 完整宽屏与小窗口。
        image=Image.new('RGB',size,(30+i*100,60,90))  # 这是合成图，不宣称实际桌面。
        path=tmp_path/'screenshots'/f'{i}.png';path.parent.mkdir(exist_ok=True);image.save(path)  # 保存测试图片。
        shots.append({'path':str(path.relative_to(tmp_path)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'captured_at':100+i,'width':size[0],'height':size[1],'scope':'full_desktop' if i==0 else 'native_window_surface'})  # 绑定来源。
    return {'segments':[],'evidence':{'e1':{'id':'x11:1','app':'demo','kind':'window','screenshot':shots[1]}},'desktop_screenshot':shots[0],'window_inventory':[],'effective_observed_seconds':600,'unobserved_gap_seconds':0,'real_end':105,'coverage_notes':[]}  # 模拟时长不修改真实截图时刻。


def configure_api(monkeypatch):  # 功能：协议测试不访问外部网络。
    for key,value in {'AI_BASE_URL':'http://127.0.0.1:12345','AI_MODEL':'protocol-test','AI_API_KEY':'fake-test-key','AI_VISION':'1'}.items(): monkeypatch.setenv(key,value)  # 仅测试模型配置。


def test_image_time_not_replaced_by_simulation(tmp_path):  # 历史图时间不等于模拟时长。
    data=evidence(tmp_path);before=copy.deepcopy(data)  # 保留原始记录。
    result=EvidenceTools(data,tmp_path).initial_desktop()  # 读取整屏。
    assert result['captured_at']==100 and result['age_at_check_seconds']==5  # 五秒前真实图，不是六百秒前。
    assert data==before  # 冻结证据没有被读取修改。


def test_no_screenshot_is_explicit(tmp_path):  # 缺图不能用历史其他任务图补充。
    data=evidence(tmp_path);data['desktop_screenshot']=None  # 模拟授权失败。
    result=EvidenceTools(data,tmp_path).initial_desktop()  # 能报告而非崩溃。
    assert 'error' in result and '_image_base64' not in result  # 不假装看到了画面。


def test_hidden_gui_keeps_action_identity_without_activity_time(tmp_path):
    data=evidence(tmp_path)
    data['window_inventory']=[{'id':'gnome:1','app':'hidden-app','kind':'window','ref':'e1','title':'最小化窗口','focused':False,'visible':False,'mapped':False}]
    branch=next(iter(build_reports(data).values()))
    assert branch['events']==[] and branch['focus_seconds']==0
    assert branch['evidence_refs']==['e1']
    assert branch['targets']['gnome:1']['visible'] is False




def test_fullscreen_saved_without_cropping(tmp_path):  # 测试多屏联合画面的边缘完整性，不宣称真实多屏已实测。
    details=DetailCollector(N(data_dir=str(tmp_path),screenshots=True,ui_text=False))  # 使用实际编码器。
    image=Image.new('RGB',(4000,1000),'white');image.putpixel((0,0),(0,0,0))  # 合成超宽图。
    meta=details.save_image(image,{'scope':'full_desktop','captured_at':1},(2560,1600))  # 缩放不裁剪。
    assert meta['original_size']==[4000,1000] and meta['width']==2560 and meta['height']==640  # 保留完整长宽比。


def test_minimized_native_capture_not_activated(tmp_path):  # 不让取证改变用户桌面。
    details=DetailCollector(N(data_dir=str(tmp_path)))  # 默认无侵入配置。
    with pytest.raises(ValueError,match='不激活'): details.native_shot({'backend':'x11'},{'mapped':False},time.monotonic()+1)  # 在调用任何系统抓图前拒绝。


def test_generic_open_logs_without_app_mapping(tmp_path):  # 真实本进程持有日志，无应用名映射。
    path=tmp_path/'anything.log'  # 名称不限于某个程序。
    with path.open('w+') as stream:  # 日志在采集时确实被进程打开。
        stream.write('actual test activity\nAPI_KEY=secret\n');stream.flush()  # 模拟真实日志写入。
        rows=GenericLogs([tmp_path]).read({'pid':os.getpid(),'process':process_info(os.getpid())})  # 通过操作系统发现。
    assert any('actual test activity' in row.get('text','') for row in rows)  # 自动找到文件。
    assert all('=secret' not in row.get('text','') for row in rows)  # 常见凭据有限遮蔽。


@pytest.mark.parametrize('kind',['outside','symlink','binary','fifo'])  # 不允许日志入口扩成任意读取器。
def test_generic_log_rejects_unsafe_sources(tmp_path,kind):  # 四种真实文件对象边界。
    root=tmp_path/'allowed';root.mkdir();path=root/'file.log'  # 授权根。
    if kind=='outside': path=tmp_path/'outside.log';path.write_text('no')  # 未授权路径。
    elif kind=='symlink': (tmp_path/'secret').write_text('no');path.symlink_to(tmp_path/'secret')  # 软链接越界。
    elif kind=='binary': path.write_bytes(b'\x00binary')  # 不解析二进制数据库。
    else: os.mkfifo(path)  # 不在管道上无穷等待。
    with pytest.raises(ValueError): tail_file(path,[root])  # 同一通用拒绝路径。


def test_log_pid_reuse_is_rejected(tmp_path):  # 身份改变后不能读取新程序日志。
    identity=process_info(os.getpid());identity['created_at']-=10  # 合成旧生命周期。
    rows=GenericLogs([tmp_path]).read({'pid':os.getpid(),'process':identity})  # 检查实际 PID。
    assert 'error' in rows[0]  # 不能作为正常空日志。


def test_missing_window_screenshot_is_not_an_exception(tmp_path):  # 原生窗口抓取失败时仍能正常提供文本证据。
    data=evidence(tmp_path);data['evidence']['e1']['screenshot']=None  # 模拟明确的缺图状态。
    assert EvidenceTools(data,tmp_path).short_evidence('e1')['screenshot'] is False  # 不因 None 崩溃整个模型请求。


def test_latest_snapshot_not_penultimate_segment():  # 当前显示内容和过去一段时间的内容不能混淆。
    from focus_demo.prompts import timeline,apply_time_patch  # 实际时序转换。
    def sample(i,title):  # 合成样本只用于边界验证。
        return {'sample_id':i,'ts':i,'mono':i,'desktop':{'available':True,'windows':[{'id':'w','app':'editor','title':title,'focused':True,'visible':True}]},'browser':{'available':False,'pages':[]}}  # 同一窗口在最后一次采样改内容。
    result=apply_time_patch(timeline([sample(1,'旧内容'),sample(2,'新内容')],1),{},True)  # 最后一帧没有持续时间，但有当前意义。
    assert result['segments'][0]['objects'][0]['title']=='旧内容'  # 历史不能被覆盖。
    assert overview(result)['current_objects'][0]['title']=='新内容'  # 当前不能落后一帧。
