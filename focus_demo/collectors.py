"""真实环境采集：X11/GNOME 窗口与独立 Chrome 配置中的网页。"""
from .process_worker import run_worker
import json  # 导入运行所需模块。
import os  # 导入运行所需模块。
import sys  # 选择原生平台。
import time  # 导入运行所需模块。
import threading  # 导入运行所需模块。
from pathlib import Path  # 导入本模块需要的接口。
from .common import digest, clip  # 导入本模块需要的接口。


def intersection(a, b):  # 返回两个矩形的交集，用于计算窗口遮挡的近似值。
    """返回两个矩形的交集，用于计算窗口遮挡的近似值。"""
    x, y = max(a[0], b[0]), max(a[1], b[1])  # 保存下一步骤使用的计算结果。
    right, bottom = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])  # 保存下一步骤使用的计算结果。
    return [x, y, max(0, right - x), max(0, bottom - y)]  # 返回本步骤的结果。


def subtract(rect, cover):  # 从矩形中扣除遮挡部分，最多得到四个不重叠矩形。
    """从矩形中扣除遮挡部分，最多得到四个不重叠矩形。"""
    x, y, width, height = intersection(rect, cover)  # 保存下一步骤使用的计算结果。
    if width == 0 or height == 0:  # 仅在当前条件成立时处理。
        return [rect]  # 返回本步骤的结果。
    left, top, wide, high = rect  # 保存下一步骤使用的计算结果。
    candidates = [[left, top, wide, y - top], [left, y + height, wide, top + high - y - height], [left, y, x - left, height], [x + width, y, left + wide - x - width, height]]  # 保存下一步骤使用的计算结果。
    return [r for r in candidates if r[2] > 0 and r[3] > 0]  # 返回本步骤的结果。


def mark_visibility(windows, screen):  # 按从底到顶的顺序估算可见面积。
    """按从底到顶的顺序估算可见面积；透明和不规则窗口仍存在误差。"""
    covers = []  # 保存下一步骤使用的计算结果。
    for window in reversed(windows):  # 逐项处理集合中的记录。
        regions = window.get("shape_rects", [window["rect"]])
        pieces = [intersection(region, screen) for region in regions] if window["mapped"] else []  # 保存下一步骤使用的计算结果。
        for cover in covers:  # 逐项处理集合中的记录。
            pieces = [part for piece in pieces for part in subtract(piece, cover)]  # 保存下一步骤使用的计算结果。
        area = sum(piece[2] * piece[3] for piece in pieces)  # 保存下一步骤使用的计算结果。
        total = max(1, window["rect"][2] * window["rect"][3])  # 保存下一步骤使用的计算结果。
        window["visible_fraction_estimate"] = None if area and window.get("visibility_uncertain") else round(area / total, 3)  # 保存桌面窗口。
        window["visible"] = None if area and window.get("visibility_uncertain") else area > 0  # 保存桌面窗口。
        if window["mapped"] and window.get("occludes", True):
            covers.extend(regions)  # 汇集本次需要保留的记录。
    return windows  # 返回本步骤的结果。


class X11Desktop:  # 封装当前组件的状态与接口。
    """读取 X 服务中的真实窗口、焦点、进程和矩形，不读取模拟事件。"""
    def __init__(self):  # 定义当前功能的处理入口。
        from Xlib import display  # 导入本模块需要的接口。
        self.display = display.Display()  # 保存下一步骤使用的计算结果。
        self.root = self.display.screen().root  # 保存下一步骤使用的计算结果。

    def property(self, window, name, default=None):  # 定义当前功能的处理入口。
        value = window.get_full_property(self.display.intern_atom(name), 0)  # 保存下一步骤使用的计算结果。
        return default if value is None else value.value  # 返回本步骤的结果。

    def capture(self):  # 定义当前功能的处理入口。
        active = self.property(self.root, "_NET_ACTIVE_WINDOW", [0])[0]  # 保存下一步骤使用的计算结果。
        current = self.property(self.root, "_NET_CURRENT_DESKTOP", [0])[0]  # 保存下一步骤使用的计算结果。
        identifiers = self.property(self.root, "_NET_CLIENT_LIST_STACKING", [])  # 保存下一步骤使用的计算结果。
        windows = []  # 保存窗口集合。
        for identifier in identifiers:  # 逐项处理集合中的记录。
            try:  # 捕获当前操作可能出现的异常。
                window = self.display.create_resource_object("window", int(identifier))  # 保存桌面窗口。
                attributes, geometry = window.get_attributes(), window.get_geometry()  # 保存下一步骤使用的计算结果。
                origin = self.root.translate_coords(window, 0, 0)  # 保存下一步骤使用的计算结果。
                raw_title = self.property(window, "_NET_WM_NAME", b"")  # 保存下一步骤使用的计算结果。
                title = raw_title.decode("utf-8", "replace") if isinstance(raw_title, bytes) else str(raw_title)  # 保存下一步骤使用的计算结果。
                title = title or str(window.get_wm_name() or "")  # 保存下一步骤使用的计算结果。
                wm_class = window.get_wm_class() or ("unknown", "unknown")  # 保存下一步骤使用的计算结果。
                pid = int(self.property(window, "_NET_WM_PID", [0])[0])  # 保存下一步骤使用的计算结果。
                desktop = int(self.property(window, "_NET_WM_DESKTOP", [current])[0])  # 保存下一步骤使用的计算结果。
                windows.append({"id": f"x11:{int(identifier)}", "app": "/".join(wm_class), "title": clip(title, 300), "pid": pid, "focused": int(identifier) == int(active), "mapped": attributes.map_state == 2 and desktop in (current, 0xFFFFFFFF), "rect": [origin.x, origin.y, geometry.width, geometry.height]})  # 汇集本次需要保留的记录。
            except Exception:  # 处理失败而不伪装为成功。
                continue  # 跳过不符合要求的记录。
        screen = self.display.screen()  # 保存下一步骤使用的计算结果。
        mark_visibility(windows, [0, 0, screen.width_in_pixels, screen.height_in_pixels])  # 执行当前步骤并保留既定边界。
        return {"backend": "x11", "available": True, "windows": windows, "screen": [0, 0, screen.width_in_pixels, screen.height_in_pixels], "limitations": ["可见面积按不透明矩形近似；没有推断非浏览器正文或用户是否理解内容。"]}  # 返回本步骤的结果。


class GnomeDesktop:  # 封装当前组件的状态与接口。
    """读取 GNOME Shell 扩展产生的真实桌面快照；过期时明确报告缺失。"""
    def __init__(self, path=None):  # 定义当前功能的处理入口。
        from .desktop_setup import snapshot_path
        self.path = Path(path) if path else snapshot_path()  # 保存文件路径。

    def request_capture(self, screenshots, wait=False, timeout=7.0):
        """Authorize before reading; wait only when a new detail sample is due."""
        from .common import write_json
        requested_at = time.time()
        write_json(self.path.parent / "capture-request.json",
                   {"expires_at": requested_at + max(8, getattr(self,"sampling",{}).get("interval_seconds",2)*4), "screenshots": screenshots, "sampling":getattr(self,"sampling",{})})
        # Shell throttles shots to five seconds and publishes on a 500 ms tick.
        deadline = time.monotonic() + timeout
        while True:
            desktop = self.capture()
            if not wait or not screenshots:
                return desktop
            meta = desktop.get("screen_capture") or {}
            root = self.path.parent.resolve()
            path = (root / meta.get("file", "")).resolve()
            if meta.get("captured_at", 0) >= requested_at and path.is_relative_to(root) and path.is_file():
                return desktop
            if time.monotonic() >= deadline:
                desktop["screen_capture"] = None
                desktop.setdefault("limitations", []).append("等待本次 GNOME 截图超时；未使用请求前的旧图。")
                return desktop
            time.sleep(.05)

    def capture(self):  # 定义当前功能的处理入口。
        try:  # 捕获当前操作可能出现的异常。
            data = json.loads(self.path.read_text(encoding="utf-8"))  # 保存结构化数据。
            if abs(time.time() - data["ts"]) > 4:  # 仅在当前条件成立时处理。
                raise ValueError("GNOME 快照已过期：请检查扩展是否启用或屏幕是否锁定")  # 拒绝无效操作并给出原因。
            if data.get("stacking_order") == "bottom_to_top":
                mark_visibility(data["windows"], data["screen"])
                data["limitations"] = ["可见面积按不透明矩形近似；透明和不规则窗口可能有误差。"]
            else:
                data.setdefault("limitations", []).append("GNOME 扩展未提供层叠顺序；无法判断完全遮挡，请更新扩展并重新登录。")
                for window in data.get("windows", []):
                    if window.get("mapped") and window.get("visible"):
                        window["visible"] = None
                        window["visibility_status"] = "unknown_stacking_order"
            data["available"] = True  # 保存结构化数据。
            return data  # 返回本步骤的结果。
        except Exception as error:
            if isinstance(error, FileNotFoundError):
                from .desktop_setup import status
                message = status()["message"]
            else:
                message = str(error)
            return {"backend": "gnome", "available": False, "windows": [], "limitations": [message]}  # 返回本步骤的结果。


class MissingDesktop:  # 封装当前组件的状态与接口。
    """缺少受支持桌面时不伪造焦点，也不将 XWayland 当作完整桌面。"""
    def __init__(self, reason=""):  # 定义当前功能的处理入口。
        self.reason = reason  # 保存下一步骤使用的计算结果。

    def capture(self):  # 定义当前功能的处理入口。
        return {"backend": "unavailable", "available": False, "windows": [], "limitations": ["桌面采集不可用；浏览器文档焦点不能代替系统级焦点。", self.reason]}  # 返回本步骤的结果。


def desktop_backend(name):  # Wayland 自动选择 GNOME 快照，不静默回退到不完整的 X11 视图。
    """Wayland 自动选择 GNOME 快照，不静默回退到不完整的 X11 视图。"""
    if name == "windows" or name == "auto" and sys.platform == "win32":  # 不在 Windows 使用 X11 兼容层。
        from .platforms import WindowsDesktop  # 原生窗口句柄适配。
        return WindowsDesktop()  # 依赖缺失会明确报错。
    if name == "macos" or name == "auto" and sys.platform == "darwin":  # macOS 原生适配。
        from .platforms import MacDesktop  # 延迟加载平台依赖。
        return MacDesktop()  # 不假装 Linux 采集器通用。
    if name == "gnome" or name == "auto" and os.environ.get("XDG_SESSION_TYPE") == "wayland":  # 仅在当前条件成立时处理。
        return GnomeDesktop()  # 返回本步骤的结果。
    if name in ("auto", "x11"):  # 仅在当前条件成立时处理。
        try:  # 捕获当前操作可能出现的异常。
            return X11Desktop()  # 返回本步骤的结果。
        except Exception as error:  # 处理失败而不伪装为成功。
            return MissingDesktop(str(error))  # 返回本步骤的结果。
    return MissingDesktop()  # 返回本步骤的结果。


def associate_window(bounds, title, desktop):  # 功能：CDP 窗口几何、应用身份、标题共同关联；重复候选时保持未知。
    box = bounds.get("bounds", {})  # CDP 提供的是浏览器外框。
    if not all(key in box for key in ("left", "top", "width", "height")):  # 缺少几何时不退回纯标题匹配。
        return None, "缺少浏览器窗口几何"  # 保守报告关联失败。
    candidates = []  # 保存几何与身份均匹配的候选。
    for window in desktop.get("windows", []):  # 逐个核实原生窗口。
        identity = window.get("process", {})  # 进程路径优先于窗口自报类名。
        label = (identity.get("name", "")+" "+identity.get("exe", "")+" "+window.get("app", "")).lower()  # 应用身份多源组合。
        if not any(name in label for name in ("chrome", "chromium", "msedge")):  # 不把任意同名编辑器误作浏览器。
            continue  # 仍保留它自己的原生分支。
        x, y, width, height = window["rect"]  # 系统窗口矩形。
        near = abs(x-box["left"]) <= 40 and abs(y-box["top"]) <= 80 and abs(width-box["width"]) <= 80 and abs(height-box["height"]) <= 120  # 容许窗口装饰差异；DPI 不合则报告未知。
        if near and title and title in window.get("title", ""):  # 标题只作辅助条件。
            candidates.append(window)  # 不立即选第一个。
    if len(candidates) != 1:  # 同位置同标题或无法匹配时不能强行归因。
        return None, f"原生候选数={len(candidates)}，拒绝猜测"  # 执行关闭前也使用这一边界。
    return candidates[0], "cdp_window_id+native_geometry+process_identity+title"  # 没有混淆两种窗口 ID。


class Collector:  # 封装当前组件的状态与接口。
    """组合桌面与浏览器事实；发生采集错误时保留覆盖缺口。"""
    def __init__(self, backend, chrome_port, supervisor_port, config=None):  # 定义当前功能的处理入口。
        self.lock = threading.RLock()  # 保存下一步骤使用的计算结果。
        self.desktop = desktop_backend(backend)  # 保存下一步骤使用的计算结果。
        from .details import DetailCollector  # 细节采集与桌面元数据分离。
        self.details = DetailCollector(config, self.detail_desktop) if config is not None else None  # 保存下一步骤使用的计算结果。

    def configure(self, settings):
        from .sampling_settings import merge
        options=merge(patch={'sampling':settings})['sampling']
        if getattr(self,'sampling',None)==options:return
        self.sampling=options
        if self.details:self.details.configure(options)
        if isinstance(self.desktop,GnomeDesktop):self.desktop.sampling=options

    def detail_desktop(self):
        if isinstance(self.desktop,GnomeDesktop):
            return self.desktop.request_capture(self.details.enabled)
        return self.desktop.capture()

    def capture(self):  # 定义当前功能的处理入口。
        with self.lock:  # 在受控资源或锁范围内执行。
            return self._capture()  # 返回本步骤的结果。

    def register_owned_process(self, pid):  # 功能：记录本程序创建的弹窗进程生命周期，不根据窗口标题豁免。
        from .platforms import process_info  # 查询真实启动时间与路径。
        identity = process_info(pid).get("identity")  # PID 重用不会继承豁免。
        if self.details and identity: self.details.owned_processes.add(identity)  # 只登记调用方确实持有的子进程。

    def minimize_window_verified(self, expected):  # 功能：只请求已复核的具体原生窗口最小化。
        from .actions import request_window_minimize  # 不给模型系统命令权限。
        return request_window_minimize(self, expected)  # 身份门禁与强杀共用同一执行器。

    def suspend(self):  # 功能：任务不在执行期时撤销 GNOME 取图授权，不再发起新采集。
        if self.details: self.details.suspend()
        if getattr(self.desktop, "path", None) is not None:  # 仅 GNOME 固定适配缓存。
            from .common import write_json  # 固定请求文件，防止残留授权继续取图。
            write_json(self.desktop.path.parent/"capture-request.json", {"expires_at": 0, "screenshots": False})  # 已经在途的系统截图只能等待结束。

    def _capture(self):  # 定义当前功能的处理入口。
        metadata_started = time.time()
        timings = {}
        started = time.monotonic()
        try:  # 捕获当前操作可能出现的异常。
            if isinstance(self.desktop, GnomeDesktop) and self.details:
                desktop = self.desktop.request_capture(self.details.enabled)
            else:
                desktop = self.desktop.capture()
        except Exception as error:  # 处理失败而不伪装为成功。
            desktop = {"backend": "failed", "available": False, "windows": [], "limitations": [str(error)]}  # 保存下一步骤使用的计算结果。
        timings['desktop_wait'] = time.monotonic()-started
        started = time.monotonic()
        for window in desktop.get('windows',[]):
            window['metadata_captured_at'] = desktop.get('ts') or metadata_started
        hidden = [{k: w.get(k) for k in ("id", "app", "title", "pid", "mapped", "minimized", "visible", "focused", "rect", "metadata_captured_at")} for w in desktop.get("windows", []) if w.get("visible") is False or w.get("mapped") is False]
        desktop["windows"] = [w for w in desktop.get("windows", []) if w.get("visible") is not False and w.get("mapped") is not False]
        if self.details and desktop.get('available'):  # 无法访问当前桌面时，不采集旧桌面的正文或截图。
            desktop = self.details.capture(desktop)  # 慢取证独立完成，当前元数据不等待。
        timings['details'] = time.monotonic()-started
        started = time.monotonic()
        from .platforms import process_info  # 关窗判据要核对进程生命周期，隐藏窗口同样需要身份。
        for window in hidden:  # 隐藏窗口只补身份，不读取正文或截图。
            window["process"] = process_info(window.get("pid"))
            window["instance_key"] = digest({"window": window["id"], "process": window["process"].get("identity")})[:20]
        desktop["windows"].extend(hidden)  # 隐藏窗口仅留内部元数据，不读取正文或截图。
        from .native_browser import snapshots
        browser = {'available':False, 'pages':[], 'limitations':[],
                   'semantic':snapshots(desktop, getattr(self,'sampling',{}))}
        # Metadata only; never enable a debugging connection or read hidden page bodies.
        import subprocess
        try:
            worker=run_worker([sys.executable,'-I',str(Path(__file__).with_name('browser_targets.py')),'capture'],input=json.dumps(desktop.get('windows',[])),capture_output=True,text=True,timeout=3)
            if worker.returncode:raise RuntimeError(worker.stderr[-500:])
            metadata=json.loads(worker.stdout)
            browser['action_targets']=metadata['targets']
            browser['limitations'] += ['浏览器动作目标：'+str(e) for e in metadata['errors']]
        except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as error:
            browser['action_targets']=[]
            browser['limitations'].append('浏览器动作目标不可用：'+str(error))
        timings["browser_and_targets"] = time.monotonic()-started
        return {"ts": time.time(), "mono": time.monotonic(), "capture_timings": timings, "desktop": desktop, "browser": browser}  # 返回本步骤的结果。
