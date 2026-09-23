"""公共小工具：JSON、摘要和文件写入，不包含业务判断。"""
import threading

screenshot_files = threading.RLock()

import hashlib  # 导入运行所需模块。
import json  # 导入运行所需模块。
import tempfile  # 使用唯一临时文件，避免并发写入互相覆盖。
import os  # 导入运行所需模块。
from pathlib import Path  # 导入本模块需要的接口。


def dumps(value):  # 生成稳定 JSON，方便哈希校验和对照测试。
    """生成稳定 JSON，方便哈希校验和对照测试。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)  # 返回本步骤的结果。


def digest(value):  # 对原始数据或成果快照生成摘要。
    """对原始数据或成果快照生成摘要。"""
    return hashlib.sha256(dumps(value).encode()).hexdigest()  # 返回本步骤的结果。


def write_json(path, value, *, gid=None):  # 以原子替换方式写入仅当前用户可读写的 JSON。
    """以原子替换方式写入仅当前用户可读写的 JSON。"""
    path = Path(path)  # 保存文件路径。
    path.parent.mkdir(parents=True, exist_ok=True)  # 保存文件路径。
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)  # 先验证全部数据，非法数值不破坏原文件。
    handle, temporary = tempfile.mkstemp(prefix="."+path.name+".", suffix=".tmp", dir=path.parent)  # 每次写入使用私有唯一临时文件。
    try:  # 原子提交完整文件。
        with os.fdopen(handle, "w", encoding="utf-8") as stream:  # mkstemp 默认只允许当前用户读写。
            if gid is not None:
                os.fchown(stream.fileno(),0,gid);os.fchmod(stream.fileno(),0o640)
            stream.write(content)  # 写入经过验证的 JSON。
            stream.flush()  # 将用户态缓冲写出。
            os.fsync(stream.fileno())  # 持久化文件内容。
        os.replace(temporary, path)  # 同目录替换避免半写文件。
    finally:  # 失败或并发替换后清理自己的临时文件。
        if os.path.exists(temporary): os.unlink(temporary)  # 不影响其他线程的临时文件。


def clip(text, size=1000):  # 截断不受信任的长文本，同时保留截断标记。
    """截断不受信任的长文本，同时保留截断标记。"""
    text = str(text or "")  # 保存下一步骤使用的计算结果。
    return text if len(text) <= size else text[:size] + "\n[已截断]"  # 返回本步骤的结果。
