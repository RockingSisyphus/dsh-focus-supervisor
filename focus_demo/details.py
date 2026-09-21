"""截图、可见文字和显式授权日志的采集；不录音、不录像、不记录按键。"""
from .desktop_setup import snapshot_path
import copy
import threading
from concurrent.futures import ThreadPoolExecutor
import base64  # 解码有界原生窗口图片。
import hashlib  # 标记图片内容。
import io  # 处理图像缓冲。
import json  # 读取日志配置与辅助进程输出。
import os  # 以只读方式打开日志。
import re  # 脱敏常见凭据形式。
import stat  # 拒绝设备、管道等非普通文件。
from .process_worker import run_worker
import subprocess  # 隔离可能卡死的无障碍读取。
import sys  # 使用当前 Python 启动辅助读取器。
import time  # 标记真实采集时刻。
from pathlib import Path  # 限定日志与截图路径。
from PIL import Image, ImageGrab  # 截取真实桌面像素，不进行 OCR。
from .platforms import process_info  # 获取进程生命周期身份。
from .common import write_json, digest  # 保存审计元数据。


def probe_results(output):
    """Keep complete per-window replies when another native provider times out."""
    if isinstance(output,bytes):output=output.decode('utf-8',errors='replace')
    results={}
    for line in output.splitlines():
        try:value=json.loads(line)
        except json.JSONDecodeError:continue
        if isinstance(value,dict):results.update(value)
    return results


def redact(text):  # 功能：对常见令牌字段做有限脱敏，不宣称能去除所有隐私。
    return re.sub(r'(?i)(authorization|api[_-]?key|access[_-]?token|password)(\s*[=:]\s*)([^\s,;]+)', r'\1\2[已遮蔽]', text)  # 遮蔽常见凭据键值。


def read_logs(configuration, window, limit=8000):  # 功能：只读取启动前明确指定的程序日志，不扫描整块磁盘。
    result = []  # 保存已授权日志片段。
    exe = window.get("process", {}).get("exe", "")  # 优先使用实际可执行文件路径。
    for entry in configuration:  # 日志路径来自固定本地配置，不来自模型。
        if entry.get("exe") != exe:  # 必须精确绑定程序，不能只按网页标题匹配。
            continue  # 跳过不相关日志。
        path = Path(entry["path"]).expanduser().absolute()  # 展开显式配置的文件。
        try:  # 文件可能被轮转或暂时不可读。
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))  # 不跟随末级符号链接，不执行文件。
            with os.fdopen(fd, "rb") as file:  # 及时关闭描述符。
                info = os.fstat(file.fileno())  # 查询已打开对象而不是另一条路径。
                if not stat.S_ISREG(info.st_mode):  # 管道和设备不能当日志。
                    raise ValueError("日志不是普通文件")  # 防止无限等待或设备读取。
                start = max(0, info.st_size-limit)  # 每份日志最多八千字节。
                file.seek(start)  # 只读取最近部分。
                text = file.read(limit).decode("utf-8", "replace")  # 保留可解码文本。
            result.append({"label": entry.get("label", path.name), "text": redact(text), "mtime": info.st_mtime, "tail_only": start > 0, "not_proof_of_current_activity": True})  # 日志不是当前窗口活动的独立证明。
        except (OSError, ValueError) as error:  # 记录失败而不猜测内容。
            result.append({"label": entry.get("label", path.name), "error": str(error)[:200]})  # 向模型报告日志缺失。
    return result[:6]  # 限制每程序的日志份数。


class DetailCollector:  # 功能：按低频节奏采集细节，日常采样不上传大文件。
    def __init__(self, config, desktop_provider=None):
        self.desktop_provider = desktop_provider
        self.worker = None
        self.wake = threading.Event()
        self.stop_event = threading.Event()
        self.pending = None
        self.published = {}
        self.started_at = 0
        self.last_details_at = 0
        self.owned_processes = set()  # 仅豁免监督器明确登记的弹窗进程。
        self.directory = Path(config.data_dir).resolve()  # 截图只写入受控目录。
        self.enabled = bool(getattr(config, "screenshots", False))  # 必须明确启用截图。
        self.ui_enabled = bool(getattr(config, "ui_text", False))  # 必须明确启用无障碍文本读取。
        self.interval = float(getattr(config, "detail_interval", 10))  # 不每个原始采样都截图。
        from .sampling_settings import DEFAULTS
        self.options = dict(DEFAULTS["sampling"])
        self.last_channels = {}
        self.last = 0.0  # 记录上次细节采集时刻。
        self.cache = {}  # 同一内容状态可复用带时间戳的旧快照。
        self.desktop_shot = None  # 保存带真实时间的整屏图片。
        self.cursor = 0  # 窗口过多时轮换，避免一直只采前八个。
        self.browser_cursor = 0
        from .generic_logs import GenericLogs  # 各应用共用的有界日志接口。
        self.generic_logs = GenericLogs(getattr(config, "log_root", []), getattr(config, "system_logs", False))  # 使用启动前配置的目录或自动日志采集。
        self.log_configuration = []  # 默认不读取任何日志文件。
        config_path = getattr(config, "log_config", None)  # 显式授权的日志映射。
        if config_path:  # 没配置则不遍历文件系统。
            value = json.loads(Path(config_path).read_text())  # 读取管理员或用户预先指定的配置。
            if not isinstance(value, list) or len(value) > 24 or any(not isinstance(e, dict) or not e.get("exe") or not e.get("path") for e in value):  # 校验配置规模和类型。
                raise ValueError("日志配置需为最多 24 个含 exe/path 的对象")  # 避免动态任意路径读取。
            self.log_configuration = value  # 保存固定授权。

    def configure(self, options):
        if self.options==options:return
        self.suspend()
        self.options=dict(options)
        self.interval=min(options[k] for k in ('screenshot_interval_seconds','text_interval_seconds','browser_interval_seconds','log_interval_seconds'))
        self.generic_logs.interval=options['log_interval_seconds']
        self.generic_logs.limit=options['log_bytes']
        self.generic_logs.cache.clear()
        self.last_channels={}
        self.browser_cursor=0

    def channel_due(self, name, desktop):
        interval=self.options[{'image':'screenshot_interval_seconds','text':'text_interval_seconds','browser':'browser_interval_seconds','logs':'log_interval_seconds'}[name]]
        if time.monotonic()-self.last_channels.get(name,0)>=interval:return True
        return any(self.key(w) not in self.cache for w in desktop.get('windows',[]) if not w.get('supervisor_owned'))

    def capture(self, desktop):
        """Return current metadata immediately; attach only matching completed details."""
        self.prepare_windows(desktop)
        self.pending = copy.deepcopy(desktop)
        if self.worker is None or not self.worker.is_alive():
            self.stop_event.clear()
            self.started_at = time.time()
            self.worker = threading.Thread(target=self._run,daemon=True,name='desktop-details')
            self.worker.start()
        self.wake.set()
        published = self.published
        for window in desktop.get('windows',[]):
            if window.get('visible') is False or window.get('mapped') is False or window.get('minimized'):
                continue  # Earlier content stays in earlier samples, not in this hidden-window sample.
            details = published.get('windows',{}).get(self.key(window))
            if details is not None:window.update(copy.deepcopy(details))
            elif not window.get('supervisor_owned'):
                window.update(screenshot_status='pending' if self.enabled else 'disabled',detail_notes=['窗口细节采集中'])
        desktop['desktop_screenshot'] = copy.deepcopy(published.get('screen'))
        desktop['detail_capture_timings'] = published.get('timings',{})
        desktop.setdefault('limitations',[]).extend(published.get('limitations',[]))
        return desktop

    def _run(self):
        while not self.stop_event.is_set():
            self.wake.wait()
            self.wake.clear()
            if self.stop_event.is_set():break
            pending = self.pending
            if pending is None or not self.refresh_due(pending):continue
            started = time.monotonic()
            try:
                desktop = self.desktop_provider() if self.desktop_provider else copy.deepcopy(pending)
                if not desktop.get('available',True):raise RuntimeError('; '.join(desktop.get('limitations',[])))
                desktop['windows'] = [w for w in desktop.get('windows',[]) if w.get('visible') is not False and w.get('mapped') is not False and not w.get('minimized')]
                waited = time.monotonic()-started
                if self.stop_event.is_set():break
                result = self.enrich(desktop)
                published = {'windows':copy.deepcopy(self.cache),'screen':copy.deepcopy(self.desktop_shot),
                             'limitations':list(result.get('limitations',[])),
                             'timings':{'desktop_wait':waited,'processing':time.monotonic()-started-waited}}
            except Exception as error:
                published = {'windows':{},'screen':None,'limitations':['窗口细节采集失败：'+str(error)]}
            if not self.stop_event.is_set():self.published = published

    def publish_details(self, desktop):
        # Completed facts are usable while other windows are still being read.
        if not self.stop_event.is_set():
            self.published = {'windows':copy.deepcopy(self.cache),
                              'screen':copy.deepcopy(self.desktop_shot),
                              'limitations':list(desktop.get('limitations',[]))}

    def suspend(self):
        self.stop_event.set()
        self.wake.set()
        if self.worker:
            self.worker.join(timeout=20)
            if self.worker.is_alive():raise RuntimeError('窗口细节采集工作线程未结束')
        self.pending = None
        self.published = {}
        self.cache = {}
        self.desktop_shot = None
        self.last = 0
        self.last_channels={}

    def screen(self, desktop):  # 功能：只从真实截图接口读取像素，Wayland 不回退到不完整的 XWayland。
        if desktop.get("backend") == "gnome":  # GNOME 扩展在用户会话内采集授权画面。
            metadata = desktop.get("screen_capture")  # 读取与截图关联的元数据。
            if not metadata or metadata.get("captured_at",0) < self.started_at or time.time()-metadata.get("captured_at", 0) > max(15,self.options["native_screenshot_interval_seconds"]*3,self.options["screenshot_interval_seconds"]*3):  # 不复用无限陈旧的画面。
                raise ValueError("GNOME 截图未就绪或已过期")  # 报告真实能力缺口。
            root = snapshot_path().parent.resolve()  # 固定扩展缓存根。
            path = (root/metadata["file"]).resolve()  # 截图文件名由扩展给出。
            if not path.is_relative_to(root) or not path.is_file():  # 拒绝扩展快照中的越界路径。
                raise ValueError("GNOME 截图路径无效")  # 不读取任意文件。
            return Image.open(path).convert("RGB"), metadata.get("screen", [0, 0, 1, 1]), metadata  # 返回像素与实际采样时刻。
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":  # 不用 X11 抓图冒充完整 Wayland。
            raise ValueError("此 Wayland 桌面尚无已授权截图接口")  # 显式要求原生适配。
        image = ImageGrab.grab(all_screens=True)  # Pillow 在 X11/Windows/macOS 读取实际桌面。
        screen = desktop.get("screen") or [0, 0, image.width, image.height]  # 使用采集器的桌面坐标。
        return image.convert("RGB"), screen, {"captured_at": time.time()}  # 不调用模型，不做图像理解。

    def prepare_windows(self,desktop):
        windows = desktop.get("windows", [])  # 系统窗口枚举，不根据应用名称过滤。
        for window in windows:  # 原始身份每轮重新获取。
            window["process"] = process_info(window.get("pid"))  # PID 加创建时间避免重用。
            window["instance_key"] = digest({"window": window["id"], "process": window["process"].get("identity")})[:20]  # 稳定生命周期关联。
            window["supervisor_owned"] = window["process"].get("identity") in self.owned_processes  # 标题本身不能获得豁免。
        return desktop

    def refresh_due(self,desktop):
        if any(self.channel_due(name,desktop) for name in ("image","text","browser","logs")):return True
        screen_time=(desktop.get('screen_capture') or {}).get('captured_at',0)
        if self.enabled and self.desktop_shot is None and screen_time>self.last_details_at:return True
        for window in desktop.get('windows',[]):
            if window.get('supervisor_owned') or window.get('visible') is False or window.get('mapped') is False:continue
            cached=self.cache.get(self.key(window))
            if cached is None:return True
            ready_at=max(screen_time,(window.get('native_capture') or {}).get('captured_at',0))
            if self.enabled and not cached.get('screenshot') and ready_at>cached['details_captured_at']:return True
        return False

    def enrich(self, desktop):
        self.prepare_windows(desktop)
        windows=desktop.get('windows',[])
        candidates = [w for w in windows if not w.get("supervisor_owned") and w.get('visible') is not False and w.get('mapped') is not False and not w.get('minimized')]
        if not self.refresh_due(desktop):  # Only existing identities can reuse previously collected details.
            for window in candidates:  # 已缓存信息保留来源时间。
                window.update(self.cache.get(self.key(window), {}))  # 不把旧截图的时间改成现在。
            desktop["desktop_screenshot"] = self.desktop_shot  # 最新整屏也保留原始采集时间。
            return desktop  # 元数据与内容的时刻明确分开。
        self.last = time.monotonic()  # 记录本轮细节开始时间。
        self.last_details_at = time.time()
        image, screen, metadata = None, None, {}  # 无截图时仍可读取文字。
        image_due=self.channel_due("image",desktop) or self.desktop_shot is None
        text_due=self.channel_due("text",desktop)
        browser_due=self.channel_due("browser",desktop)
        logs_due=self.channel_due("logs",desktop)
        if image_due:self.desktop_shot = None  # 新请求失败不能冒充成功。
        if self.enabled and image_due:  # 明确同意截图后才读像素。
            try:  # 原生接口可能拒绝权限。
                image, screen, metadata = self.screen(desktop)  # 读取完整桌面可用画面。
                self.desktop_shot = self.save_image(image, {"scope": "full_desktop", "screen_rect": screen, "captured_at": metadata["captured_at"]}, (self.options["screen_width"], self.options["screen_height"]))  # 保留全画面，不裁掉其他显示器区域。
            except Exception as error:  # 显示失败不等于看到了正常桌面。
                desktop.setdefault("limitations", []).append("整屏截图不可用："+str(error)[:180])  # 报告真实缺口。
        desktop["desktop_screenshot"] = self.desktop_shot  # 整屏图片不归入某个软件的活动时长。
        self.publish_details(desktop)
        rotation = candidates[self.cursor:] + candidates[:self.cursor]  # 预算有限时轮流处理全部对象。
        selected = rotation
        offset=self.browser_cursor%max(1,len(candidates))
        read_selected = candidates[offset:] + candidates[:offset] if browser_due else selected
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='window-text') as worker:
            text = worker.submit(self.read_ui,read_selected,text_due,browser_due) if text_due or browser_due else None
            if image_due:self.capture_images(desktop,selected,image,screen,metadata)
            probes, notes = text.result() if text else ({},[])
        desktop.setdefault('limitations',[]).extend(notes)
        for channel,due in (("image",image_due),("text",text_due),("browser",browser_due),("logs",logs_due)):
            if due:self.last_channels[channel]=time.monotonic()
        page_budget=self.options['browser_pages']
        pages_read=0
        for window in selected:
            details = self.cache.get(self.key(window))
            if details is None:continue
            if logs_due:
                details["logs"]=self.generic_logs.read(window)+read_logs(self.log_configuration,window,self.options["log_bytes"])
                details["logs_captured_at"]=time.time()
            probe = probes.get(window["id"], {})
            if browser_due:
                documents=probe.get('documents',[])
                count=len(documents) if page_budget is None else max(0,page_budget-pages_read)
                details['browser_documents']=[{**document,'text':document['text'][:self.options['browser_chars']],
                                              'structure':{**document.get('structure',{}),'truncated':document.get('structure',{}).get('truncated',False) or len(document['text'])>self.options['browser_chars']},
                                              'capture_interval_seconds':self.options['browser_interval_seconds'],'captured_at':document.get('captured_at',time.time())} for document in documents[:count]]
                pages_read+=len(details['browser_documents'])
            if not text_due:
                window.update(details)
                self.publish_details(desktop)
                continue
            details["text_captured_at"]=time.time()
            probe = probes.get(window["id"], {})  # 未被读到的窗口不会拿另一窗口的文本代替。
            details["ui_text"] = redact(probe.get("text", ""))[:self.options["text_chars"]]  # 限定文字量，全文在分支中分页。
            details["ui_structure"] = probe.get("structure")
            details["text_scope"] = probe.get("scope", "unavailable")  # 不将文档接口全文说成全部可见。
            details["detail_notes"].extend(probe.get("notes", []))  # 保存准确的匹配与缺口说明。
            if self.ui_enabled and not probe: details["detail_notes"].append("此窗口无无障碍结果或本轮文字预算不足")  # 不静默遗漏。
            window.update(details)
            self.publish_details(desktop)
        self.publish_details(desktop)
        self.cursor = (self.cursor+1) % max(1, len(candidates))  # 下一轮让后面的窗口优先获取细节。
        if browser_due:self.browser_cursor+=1
        return desktop  # 原始数据完整进入后续分层报告。

    def read_ui(self,selected,native_due=True,browser_due=True):
        probes = {}
        notes = []
        if self.ui_enabled and selected:  # 一次子进程内读取多窗口，避免每窗口重复启动总线。
            try:  # 父进程硬超时覆盖系统接口挂起。
                request = [{k: w.get(k) for k in ("id", "pid", "native_id", "rect", "buffer_rect", "title", "focused")} for w in selected[:32]]  # 按原生身份和几何关联，不按软件名分支。
                for window in request:
                    window['_read']={'native_due':native_due,'browser_due':browser_due,'browser_pages':self.options['browser_pages'],'browser_offset':self.browser_cursor}
                reply = run_worker([sys.executable, "-m", "focus_demo.ui_probe", "--batch", "--stream", "--chars", str(max(self.options["text_chars"],self.options['browser_chars'])), "--nodes", str(self.options["text_nodes"])], input=json.dumps(request), capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], timeout=3.5, check=True)  # 包含解释器冷启动余量；内部 AT-SPI 仍有独立短预算。
                probes = probe_results(reply.stdout)  # 每个窗口独立返回结果与覆盖说明。
            except Exception as error:  # 依赖缺失或超时不能阻断截图回退。
                if isinstance(error, subprocess.TimeoutExpired):probes=probe_results(error.stdout or b'')
                reason = type(error).__name__
                if isinstance(error, subprocess.CalledProcessError):
                    reason += f" (exit={error.returncode}) " + redact((error.stderr or "").strip().splitlines()[-1] if (error.stderr or "").strip() else "无 stderr")[:240]
                notes.append("无障碍批量读取失败："+reason)  # 明确说明未读取。
        return probes,notes

    def capture_images(self,desktop,selected,image,screen,metadata):
        deadline = time.monotonic()+4.0  # 包含原生工作进程启动开销；预算仍有界，剩余窗口下轮轮转。
        self.cache = {self.key(w):self.cache.get(self.key(w),{}) for w in selected}
        for window in selected:  # 不再只保存固定前八个软件。
            if self.stop_event.is_set():break
            details = {**self.cache.get(self.key(window),{}), "details_captured_at": time.time(), "detail_notes": []}  # 通用日志优先；旧映射只保留兼容。
            if self.enabled:  # 每个 GUI 窗口都得到截图状态，不保证所有程序都提供图像。
                try:  # 优先独立窗口画面，无需切换或激活应用。
                    details["screenshot"] = self.native_shot(desktop, window, deadline)  # 可获取被遮挡窗口自身画面。
                except Exception as error:  # 原生接口失败时明确标注再考虑回退。
                    details["detail_notes"].append("独立窗口截图不可用："+str(error)[:130])  # 不能把裁剪叫独立画面。
                    if image is not None and window.get("visible"):  # 焦点不覆盖真实可见性。
                        try:  # GNOME 异步画面必须核对截图时身份与位置。
                            frozen = metadata.get("windows")  # 原生截图时的窗口目录。
                            if frozen is not None and not any(w.get("id")==window["id"] and w.get("pid")==window.get("pid") and w.get("title")==window["title"] and w.get("rect")==window["rect"] for w in frozen):  # 拒绝错配。
                                raise ValueError("窗口在整屏截图之后已改变")  # 不裁出错误程序。
                            details["screenshot"] = self.crop(image, screen, window, metadata["captured_at"])  # 标注可能含遮挡窗口。
                        except Exception as problem: details["detail_notes"].append(str(problem)[:130])  # 失败保持不可用。
            details["screenshot_status"] = "captured" if details.get("screenshot") else "unavailable" if self.enabled else "disabled"  # 每窗口都报告状态。
            self.cache[self.key(window)] = details  # 带身份关联保存。
            window.update(details)  # 不覆盖焦点、可见性或用户进程身份。
            self.publish_details(desktop)

    def save_image(self, image, metadata, bounds=None):  # 功能：对整屏和单窗口统一采用内容寻址存储。
        region = image.copy().convert("RGB")  # 不修改原始共享桌面像素。
        original = region.size  # 记录压缩前真实尺寸。
        bounds=bounds or (self.options["image_width"],self.options["image_height"])
        region.thumbnail(bounds)  # 只缩放不裁剪，保持所有显示内容。
        buffer = io.BytesIO(); region.save(buffer, format="PNG")  # PNG 用于本地可核查证据。
        raw = buffer.getvalue()  # 编码后按实际字节控制 IPC 与磁盘峰值。
        while len(raw) > 1_900_000 and min(region.size) > 200:  # 整屏仍保留全部内容，不裁掉其他显示器。
            region.thumbnail((max(1,int(region.width*.8)),max(1,int(region.height*.8))))  # 等比降低存储分辨率。
            buffer = io.BytesIO();region.save(buffer,format="PNG");raw=buffer.getvalue()  # 使用真实像素重编码。
        fingerprint = hashlib.sha256(raw).hexdigest()  # 按实际图片内容去重。
        path = self.directory/"screenshots"/(fingerprint+".png")  # 固定目录，不接受模型提供路径。
        path.parent.mkdir(parents=True, exist_ok=True)  # 私有运行目录由入口设置 umask。
        if not path.exists(): path.write_bytes(raw)  # 同一画面不重复占用空间。
        os.utime(path, None)  # 最近重新使用的旧像素不会在提交采样前被过期清理回收。
        return {**metadata, "path": path.relative_to(self.directory).as_posix(), "sha256": fingerprint, "width": region.width, "height": region.height, "original_size": list(original)}  # 来源时间与图像大小都保留。

    def native_shot(self, desktop, window, deadline):  # 功能：按系统实现独立窗口取证，不为任何软件写专用代码。
        if not window.get("mapped", window.get("visible", False)):  # 最小化/后台工作区不主动拉回。
            raise ValueError("窗口未展示；不激活、不恢复，保留不可用状态")  # 不能据后台图片判定用户在用。
        if desktop.get("backend") == "gnome":  # Wayland 由授权扩展在合成器内读取窗口。
            meta = window.get("native_capture")  # 扩展返回绑定原生窗口的文件。
            if not meta or meta.get("captured_at",0) < self.started_at or abs(time.time()-meta.get("captured_at", 0)) > max(15,self.options["native_screenshot_interval_seconds"]*3,self.options["screenshot_interval_seconds"]*3):  # 拒绝无图或过期数据。
                raise ValueError("GNOME 未提供新鲜的窗口图")  # 上层可用桌面区域补充。
            root = snapshot_path().parent.resolve()  # 只读固定缓存。
            path = (root/meta["file"]).resolve()  # 不信任任意路径。
            if not path.is_relative_to(root) or meta.get("pid")!=window.get("pid") or meta.get("window_id")!=window["id"] or meta.get("rect")!=window["rect"] or meta.get("title")!=window["title"]:  # 验证截图对象。
                raise ValueError("GNOME 窗口图关联不一致")  # 不把旧图挂到新窗口。
            with Image.open(path) as source: image = source.convert("RGB")  # 固定缓存 PNG。
            captured = meta["captured_at"]  # 保留异步真实时刻。
        else:  # X11/Windows 子进程使用原生句柄。
            if time.monotonic() >= deadline: raise ValueError("本轮独立窗口取证预算用完，下轮轮换")  # 不无限拖延采样。
            reply = run_worker([sys.executable, "-m", "focus_demo.window_probe"], input=json.dumps(window), capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1], timeout=max(.05, deadline-time.monotonic()), check=True)  # 接口阻塞可被父进程终止。
            value = json.loads(reply.stdout)  # 只接收结构化结果。
            if value.get("error"): raise ValueError(value["error"])  # 对原生接口失败不假报成功。
            image = Image.open(io.BytesIO(base64.b64decode(value["image"], validate=True))).convert("RGB")  # 真实窗口图片。
            captured = time.time()  # 区别于整屏快照的时间。
        return self.save_image(image, {"scope": "native_window_surface", "captured_at": captured, "window_id": window["id"], "pid": window.get("pid"), "instance_key": window.get("instance_key"), "note": "原生画面不证明用户正在观看；受保护/GPU 内容可能为空白。"})  # 原生窗口不等于焦点证据。

    def key(self, window):  # 功能：避免把前一窗口/程序的细节附到另一个对象。
        return digest({k: window.get(k) for k in ("instance_key", "title", "rect")})  # 不以应用名作为唯一键。

    def crop(self, image, screen, window, captured_at):  # 功能：保存桌面区域截图；被遮挡部分仍属于实际桌面而非目标程序内部。
        x, y, width, height = window["rect"]  # 使用本轮真实窗口矩形。
        sx, sy, sw, sh = screen  # 多屏和缩放使用原生坐标映射。
        box = [max(0, int((x-sx)*image.width/sw)), max(0, int((y-sy)*image.height/sh)), min(image.width, int((x+width-sx)*image.width/sw)), min(image.height, int((y+height-sy)*image.height/sh))]  # 限制在可捕获桌面内。
        if box[2] <= box[0] or box[3] <= box[1]:  # 窗口可能不在当前屏幕。
            raise ValueError("窗口位于截图范围外")  # 不生成无意义图片。
        region = image.crop(box)  # 裁出真实桌面区域，可能包含遮挡窗口。
        return self.save_image(region, {"captured_at": captured_at, "scope": "desktop_region_may_contain_occluding_windows", "window_id": window["id"], "instance_key": window.get("instance_key")})  # 不宣称是独立窗口画面。
