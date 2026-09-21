"""通用日志：显式目录内或启用自动日志时，从 GUI 进程树发现已打开文本日志及 journal。"""
import json  # 读取系统日志的标准 JSON。
import os  # 只读普通文件。
import stat  # 拒绝管道和设备。
import subprocess  # 执行固定 journalctl，不使用 shell。
import sys  # 判断系统可用接口。
import time  # 限制查询时间范围。
from pathlib import Path  # 校验授权目录边界。
import psutil  # 通过原生进程接口列出已打开文件。


def tail_file(path, roots, limit=8000):  # 功能：通用读取授权目录中的日志尾部，不进行磁盘递归扫描。
    path = Path(path).absolute()  # 不接受相对工作目录歧义。
    if path.is_symlink() or not any(path.resolve().is_relative_to(root) for root in roots):  # 拒绝越界与末级软链接。
        raise ValueError('日志不在授权目录或是符号链接')  # 不借日志读取私有任意文件。
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))  # 不打开设备或等待 FIFO。
    with os.fdopen(fd, 'rb') as stream:  # 保证描述符关闭。
        info = os.fstat(stream.fileno())  # 核验已打开对象。
        if not stat.S_ISREG(info.st_mode):  # 日志必须是普通文件。
            raise ValueError('不是普通日志文件')  # 不读管道或设备。
        if sys.platform.startswith('linux'):  # 校验实际 fd 路径，降低父目录切换风险。
            actual = Path(os.readlink(f'/proc/self/fd/{stream.fileno()}')).resolve()  # 内核报告实际文件路径。
            if not any(actual.is_relative_to(root) for root in roots):  # 防止路径检查与打开之间被替换。
                raise ValueError('实际打开对象越界')  # 不返回越界数据。
        stream.seek(max(0, info.st_size-limit))  # 只读最近部分。
        raw = stream.read(limit)  # 单次读取有界。
    if b'\0' in raw or any(byte < 32 and byte not in (9, 10, 13) for byte in raw):  # 二进制数据不当文本日志处理。
        raise ValueError('不是纯文本日志')  # 不解析应用私有数据库。
    from .details import redact  # 复用有限敏感字段遮蔽。
    return {'label': path.name, 'text': redact(raw.decode('utf-8', 'replace')), 'mtime': info.st_mtime, 'tail_only': info.st_size > limit, 'source': 'open_regular_log_file', 'not_proof_of_current_activity': True}  # 关联进程不代表日志由本次交互产生。


class GenericLogs:  # 功能：按进程生命周期缓存通用采集，没有应用名分支。
    def __init__(self, roots=(), system=False):  # 目录与系统日志在开始前明确授权。
        self.roots = [Path(root).expanduser().resolve() for root in roots]  # 只保存授权目录，不预先扫描。
        self.system = bool(system)  # 默认不开启系统日志读取。
        self.interval=10
        self.limit=8000
        self.cache = {}  # 相同程序多窗口复用一次查询。

    def read(self, window):  # 功能：发现已打开的 .log/.jsonl；找不到就返回真实缺口。
        identity = window.get('process', {})  # 使用采集器核验过的进程身份。
        key = identity.get('identity')  # PID 复用不会误命中缓存。
        cached = self.cache.get(key) if key else None  # 未验证身份不复用。
        if cached and time.monotonic()-cached[0] < self.interval:  # 有限频率读日志。
            return cached[1]  # 保留原始日志时间戳。
        result = []  # 没日志不是偷懒证据。
        if not self.roots and not self.system:  # 未授权时不触及日志系统。
            return result  # 默认只采集截图和界面文字。
        try:  # 进程可能已结束或不允许列举文件。
            process = psutil.Process(int(window['pid']))  # 不遍历其他无关进程。
            if abs(process.create_time()-identity.get('created_at', -1)) > .01:  # 核验进程创建时间。
                raise ValueError('日志关联进程已变化')  # 拒绝旧 PID。
            # 自动发现只检查该 GUI 进程及其子进程实际打开的文本日志，不扫描磁盘。
            processes = self.application_processes(process)
            seen = set()
            for member in processes:
                try:
                    opened_files = member.open_files()
                except psutil.Error:
                    continue
                for opened in opened_files[:256]:
                    path = Path(opened.path)
                    if path in seen or path.suffix.lower() not in ('.log', '.jsonl'):
                        continue
                    seen.add(path)
                    # 数字日志是数据库 WAL 常见格式，不作为自然语言运行日志。
                    if path.stem.isdecimal():
                        continue
                    roots = self.roots or ([path.parent.resolve()] if self.system else [])
                    if not any(path.resolve().is_relative_to(root) for root in roots):
                        continue
                    try:
                        row = tail_file(path, roots, self.limit)
                        row['query_pid'] = member.pid
                        row['process_created_at'] = member.create_time()
                        if row['text'].strip(): result.append(row)
                    except (OSError, ValueError):
                        continue  # 非文本文件不是可用的运行日志。
                    if len(result) >= 3: break
                if len(result) >= 3: break
            if self.system:  # 可选通用系统日志通道。
                result.append(self.journal(process.pid, process.create_time()))  # 按 PID 和启动时间缩小范围。
            if abs(process.create_time()-identity.get('created_at', -1)) > .01 or not process.is_running():  # 读取后校验生命周期。
                raise ValueError('日志采集期间进程退出或被复用')  # 不关联不确定记录。
        except (psutil.Error, ValueError, OSError) as error:  # 不可访问的情况不可伪装成没有日志。
            result = [{'source': 'generic_logs', 'error': type(error).__name__+': '+str(error)[:120]}]  # 明确覆盖缺口。
        if not result:  # 当前没有符合规则的日志。
            result = [{'source': 'generic_logs', 'status': 'no_readable_open_logs', 'text': '', 'note': '未发现采集范围内仍打开的可读文本日志；不表示程序没有日志，也不表示没有活动。'}]  # 不作过度推断。
        if key: self.cache[key] = (time.monotonic(), result)  # 按生命周期保存短期缓存。
        if len(self.cache) > 256: self.cache = {key: self.cache[key]} if key else {}  # 限定缓存规模。
        return result  # 日志保留在程序分支，不默认发完整内容。

    @staticmethod
    def application_processes(process):
        """Only follow same-executable helpers; a launcher is not its launched apps.

        Different executables have no generic ownership proof. Their logs remain
        available when that process itself owns a monitored window.
        """
        executable = os.path.normcase(process.exe())
        members = [process]
        for parent in members:
            try:
                children = parent.children()
            except psutil.Error:
                continue
            for child in children:
                try:
                    if os.path.normcase(child.exe()) == executable:
                        members.append(child)
                        if len(members) >= 64:
                            return members
                except psutil.Error:
                    continue
        return members

    def journal(self, pid, created):  # 功能：系统级日志接口不需要应用专用解析规则。
        if not sys.platform.startswith('linux'):  # 当前只接入 Linux 标准 journal。
            return {'source': 'system_log', 'error': '本系统尚未实现系统日志接口；授权文件日志仍可用'}  # 不夸大跨系统覆盖。
        try:  # 系统可能没有 journal 或权限不足。
            command = ['journalctl', '-b', '--no-pager', '-q', '-n', '20', '--output=json', '--output-fields=MESSAGE,__REALTIME_TIMESTAMP,_PID,_EXE', '--since=@'+str(max(created, time.time()-600)), '_PID='+str(int(pid))]  # 固定参数，无通用命令执行接口。
            reply = subprocess.run(command, capture_output=True, text=True, timeout=.8, check=True)  # 防止日志查询阻塞采集。
            records = [{key: value for key, value in json.loads(line).items() if key in ('MESSAGE', '__REALTIME_TIMESTAMP', '_PID', '_EXE')} for line in reply.stdout.splitlines()[:20] if line]  # 使用标准 JSON，不写应用解析器。
            from .details import redact  # 使用相同有限脱敏逻辑。
            return {'source': 'system_journal', 'text': redact(json.dumps(records, ensure_ascii=False))[:self.limit], 'status': 'available' if records else 'empty', 'captured_at': time.time(), 'query_pid': pid, 'tail_only': True, 'note': '仅当前启动及该进程创建之后；空结果不代表无活动。'}  # 不收集系统所有日志。
        except Exception as error:  # 缺少命令或权限时不尝试提权绕过。
            return {'source': 'system_journal', 'error': type(error).__name__+': '+str(error)[:120]}  # 保留实际错误。
