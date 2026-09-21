"""任务材料快照：只接收明确提交的文字，不开放模型读取任意本机文件。"""
from .common import digest  # 为资料内容建立稳定指纹。


def normalise_materials(items):  # 功能：限制数量和总量并冻结资料，不执行其中的代码。
    if not isinstance(items, list) or len(items) > 8:  # 资料必须是有界列表。
        raise ValueError('最多提交八份文字资料')  # 拒绝异常结构。
    result = []; total = 0  # 保存规范化资料与累计字符数。
    for item in items:  # 所有类型任务使用同一种资料格式。
        if not isinstance(item, dict) or set(item)-{'name', 'text'}:  # 不允许携带本机读取路径。
            raise ValueError('资料仅接受 name 和 text 字段')  # 不把路径当读取命令。
        name, text = item.get('name'), item.get('text')  # 获取明确提交的原文。
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 120:  # 名称只用于展示。
            raise ValueError('资料名需为 1 到 120 字符')  # 不猜测名称。
        if not isinstance(text, str) or not 1 <= len(text) <= 100000:  # 单文件读取上限。
            raise ValueError('每份资料需为 1 到 100000 字符的文本')  # 不静默截断。
        total += len(text)  # 计入整个请求的预算。
        if total > 200000:  # 全部资料共用有限预算。
            raise ValueError('资料总量超过 200000 字符；请明确缩小任务范围')  # 不悄悄丢掉论文后半部分。
        fingerprint = digest({'name': name, 'text': text})  # 冻结名称和实际内容。
        result.append({'id': 'material_'+fingerprint[:16], 'name': name, 'text': text, 'sha256': fingerprint})  # 用编号给工具读取。
    if len({item['id'] for item in result}) != len(result):  # 拒绝重复资料造成目录歧义。
        raise ValueError('同一资料重复提交')  # 保持一个编号一份快照。
    return result  # 不使用当前磁盘文件替代原始快照。


def material_catalog(materials):  # 功能：首轮只发送目录，不重复发送论文或项目全文。
    return [{'id': item['id'], 'name': item['name'], 'chars': len(item['text']), 'sha256': item['sha256']} for item in materials]  # 所有内容可用编号分页获取。
