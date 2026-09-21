"""原生窗口适配：Windows 与 macOS 为待实机验证的适配器，不伪装已支持完整桌面。"""
import os  # 获取进程身份与平台环境。
import sys  # 选择原生平台。
import time  # 标记采集时间。
import psutil  # 查询真实进程创建时间与可执行文件。
from pathlib import Path
from .common import digest  # 生成带进程生命周期的标识。


def process_info(pid):  # 功能：防止仅用标题或可复用 PID 关联程序。
    try:  # 已退出或无权限进程会报告缺口。
        process = psutil.Process(int(pid))  # 读取系统进程。
        with process.oneshot():
            info = {"pid": process.pid, "created_at": process.create_time()}
            # Identity is independent of permission-dependent metadata such as exe.
            if sys.platform == 'linux':
                # Epoch create_time adds /proc/stat btime, which can change when
                # the clock is corrected. Kernel start ticks do not change.
                stat=Path(f'/proc/{process.pid}/stat').read_text()
                start_ticks=int(stat.rsplit(')',1)[1].split()[19])
                lifecycle={'pid':process.pid,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'start_ticks':start_ticks}
                info.update(boot_id=lifecycle['boot_id'],start_ticks=start_ticks)
            else:lifecycle={'pid':process.pid,'created_at':info['created_at']}
            info["identity"] = digest(lifecycle)[:20]
            for key,read in (("name",process.name),("exe",process.exe)):
                try:info[key]=read()
                except psutil.AccessDenied:info[key]="";info[key+"_unavailable"]="AccessDenied"
        return info  # 返回核实的身份。
    except (psutil.Error, ValueError, TypeError, OSError) as error:  # 程序可能已关闭。
        return {"pid": pid, "identity_verified": False, "error": type(error).__name__}  # 不以猜测填补路径。


class WindowsDesktop:  # 功能：读取 HWND、焦点、PID 和物理像素矩形。
    def __init__(self):  # 在 Windows 上才加载系统 DLL。
        import ctypes  # 调用原生系统接口。
        from ctypes import wintypes  # 避免 64 位窗口句柄截断。
        self.c, self.w = ctypes, wintypes  # 保存类型定义。
        self.u = ctypes.WinDLL("user32", use_last_error=True)  # 读取窗口系统接口。
        self.u.GetForegroundWindow.restype = wintypes.HWND  # 明确指针宽度。
        self.u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]  # 正确读取进程编号。
        self.u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]  # 正确读取矩形。
        self.u.GetWindowTextLengthW.argtypes = [wintypes.HWND]  # 正确处理句柄。
        self.u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]  # Unicode 标题。
        self.u.IsWindowVisible.argtypes = [wintypes.HWND]  # 正确判断显示标记。
        self.u.IsIconic.argtypes = [wintypes.HWND]  # 检查最小化。
        self.dwm = ctypes.WinDLL("dwmapi")
        self.gdi = ctypes.WinDLL("gdi32")
        self.dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD]
        self.dwm.DwmGetWindowAttribute.restype = ctypes.c_long
        self.u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.u.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.u.GetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE]
        self.u.GetLayeredWindowAttributes.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BYTE), ctypes.POINTER(wintypes.DWORD)]
        self.gdi.CreateRectRgn.argtypes = [ctypes.c_int]*4
        self.gdi.CreateRectRgn.restype = wintypes.HANDLE
        self.gdi.GetRegionData.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID]
        self.gdi.GetRegionData.restype = wintypes.DWORD
        self.gdi.DeleteObject.argtypes = [wintypes.HANDLE]
        try:  # 启用每显示器 DPI 感知，降低缩放坐标误配。
            self.u.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # 设置当前采集进程，不改变用户系统缩放。
        except (AttributeError, OSError):  # 老系统可能不支持。
            pass  # 后续能力报告不会承诺无误差。

    def geometry(self, hwnd, rect):
        """Use compositor visibility and explicit regions, never assume layered opacity."""
        c, w, u = self.c, self.w, self.u
        cloak = w.DWORD()
        status = self.dwm.DwmGetWindowAttribute(hwnd, 14, c.byref(cloak), c.sizeof(cloak))
        style = u.GetWindowLongPtrW(hwnd, -20)
        classname = c.create_unicode_buffer(256)
        u.GetClassNameW(hwnd, classname, len(classname))
        result = {"cloaked": bool(cloak.value) if status == 0 else None,
                  "window_class": classname.value, "occludes": True}
        # These are Windows desktop surfaces, not app-specific adapters.
        result["desktop_shell"] = classname.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")
        region = self.gdi.CreateRectRgn(0, 0, 0, 0)
        try:
            kind = u.GetWindowRgn(hwnd, region)
            if kind == 1:  # NULLREGION is an explicitly empty shape; ERROR means no explicit region.
                result["shape_rects"] = []
            elif kind in (2, 3):
                size = self.gdi.GetRegionData(region, 0, None)
                if 32 <= size <= 32 + 512*16:
                    data = c.create_string_buffer(size)
                    if self.gdi.GetRegionData(region, size, data):
                        import struct
                        header, _, count, _ = struct.unpack_from('<4I', data.raw)
                        if header == 32 and header + count*16 <= size:
                            result["shape_rects"] = [[rect[0]+a, rect[1]+b, right-a, bottom-b]
                                for a, b, right, bottom in struct.iter_unpack('<4i', data.raw[header:header+count*16])]
                if "shape_rects" not in result:
                    result.update(occludes=False, visibility_uncertain=True)
        finally:
            self.gdi.DeleteObject(region)
        if style & 0x80000:  # WS_EX_LAYERED: per-pixel alpha may not be queryable.
            key, alpha, flags = w.DWORD(), w.BYTE(), w.DWORD()
            known = bool(u.GetLayeredWindowAttributes(hwnd, c.byref(key), c.byref(alpha), c.byref(flags)))
            opaque = known and not (flags.value & 1) and bool(flags.value & 2) and alpha.value == 255
            if known and flags.value & 2 and alpha.value == 0:
                result["shape_rects"] = []
            if not opaque:
                result.update(occludes=False, visibility_uncertain=True,
                              visibility_note="透明分层窗口：矩形不是可见像素范围；不以其包围框遮挡其他应用。")
        if status != 0:
            result.update(occludes=False, visibility_uncertain=True)
        return result

    def capture(self):  # 采集真实顶层窗口，不读取应用思想或音视频。
        from .collectors import mark_visibility  # 共用近似遮挡算法。
        c, w, u = self.c, self.w, self.u  # 使用平台类型。
        # EnumWindows enumerates our thread's desktop even while Winlogon owns
        # the screen. Its windows must not be described as currently visible.
        u.OpenInputDesktop.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        u.OpenInputDesktop.restype = w.HANDLE
        u.GetThreadDesktop.argtypes = [w.DWORD]
        u.GetThreadDesktop.restype = w.HANDLE
        u.GetUserObjectInformationW.argtypes = [w.HANDLE, c.c_int, w.LPVOID, w.DWORD, c.POINTER(w.DWORD)]
        u.CloseDesktop.argtypes = [w.HANDLE]
        active = u.OpenInputDesktop(0, False, 1)  # DESKTOP_READOBJECTS
        try:
            if not active: raise c.WinError(c.get_last_error())
            def name(handle):
                value = c.create_unicode_buffer(256); needed = w.DWORD()
                if not u.GetUserObjectInformationW(handle, 2, value, c.sizeof(value), c.byref(needed)):
                    raise c.WinError(c.get_last_error())
                return value.value
            current = u.GetThreadDesktop(c.windll.kernel32.GetCurrentThreadId())
            if name(active) != name(current):
                raise RuntimeError('当前输入桌面与采集桌面不同（锁屏或系统授权界面）')
        except OSError as error:
            return {'backend':'windows','available':False,'windows':[],
                    'limitations':['当前输入桌面不可访问：'+str(error)]}
        except RuntimeError as error:
            return {'backend':'windows','available':False,'windows':[], 'limitations':[str(error)]}
        finally:
            if active:u.CloseDesktop(active)
        windows, focused = [], u.GetForegroundWindow()  # 准备返回列表。
        callback_type = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)  # 采用原生枚举签名。
        def visit(hwnd, value):  # 对每个顶层窗口采样。
            length = u.GetWindowTextLengthW(hwnd)  # 读取标题长度。
            title = c.create_unicode_buffer(max(1, min(length+1, 4096)))  # 限制标题缓冲区。
            u.GetWindowTextW(hwnd, title, len(title))  # 读取实际标题。
            pid, rect = w.DWORD(), w.RECT()  # 准备原生输出。
            u.GetWindowThreadProcessId(hwnd, c.byref(pid))  # 关联真实进程。
            u.GetWindowRect(hwnd, c.byref(rect))  # 取得屏幕矩形。
            info = process_info(pid.value)  # 获取生命周期信息。
            bounds = [rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top]
            geometry = self.geometry(hwnd, bounds)
            mapped = bool(u.IsWindowVisible(hwnd)) and not bool(u.IsIconic(hwnd)) and not geometry["cloaked"]
            windows.append({"id": f"win:{int(hwnd)}", "native_id": int(hwnd), "app": info.get("name", "unknown"), "title": title.value, "pid": pid.value, "process": info, "focused": hwnd == focused, "mapped": mapped, "minimized": bool(u.IsIconic(hwnd)), "rect": bounds, **geometry})
            return True  # 继续枚举所有窗口。
        callback = callback_type(visit)  # 保持回调引用存活。
        u.EnumWindows.argtypes = [callback_type, w.LPARAM]  # 明确 64 位回调与参数宽度。
        u.EnumWindows.restype = w.BOOL  # 明确枚举结果。
        u.EnumWindows(callback, 0)  # 枚举实际窗口。
        windows.reverse()  # EnumWindows 从顶部开始；遮挡算法要求底到顶。
        screen = [u.GetSystemMetrics(76), u.GetSystemMetrics(77), u.GetSystemMetrics(78), u.GetSystemMetrics(79)]  # 覆盖多显示器虚拟桌面。
        mark_visibility(windows, screen)  # 明确只是矩形近似。
        return {"backend": "windows", "available": True, "windows": [item for item in windows if not item["desktop_shell"]], "screen": screen, "limitations": ["普通窗口按矩形/系统区域估算遮挡；透明分层窗口的像素可见性标为未知，不以透明包围框遮挡其他窗口。"]}  # 如实标记支持程度。


class MacDesktop:  # 功能：使用 Quartz 窗口编号和所属 PID；焦点无法唯一确定时保留未知。
    def capture(self):  # 在 macOS 上调用授权后的桌面接口。
        import Quartz as q  # 需要 pyobjc-framework-Quartz。
        import AppKit  # 用 NSWorkspace 获得前台应用 PID。
        from .collectors import mark_visibility  # 共用矩形覆盖算法。
        pid = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier()  # 这只是前台应用，不等于其中每个窗口都获得焦点。
        records = q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionAll, q.kCGNullWindowID) or []  # 获取可授权观察的窗口元数据。
        windows = []  # 保存原生窗口。
        for record in records:  # 逐个处理真实窗口记录。
            if record.get(q.kCGWindowLayer, 0) != 0:  # 跳过系统覆盖层的应用归因。
                continue  # 不把菜单栏当工作程序。
            bounds = record[q.kCGWindowBounds]  # Quartz 逻辑坐标。
            owner = int(record[q.kCGWindowOwnerPID])  # 获取所属进程。
            native = int(record[q.kCGWindowNumber])  # 窗口原生编号。
            windows.append({"id": f"mac:{native}", "native_id": native, "app": record.get(q.kCGWindowOwnerName, "unknown"), "title": record.get(q.kCGWindowName, ""), "pid": owner, "process": process_info(owner), "focused": False, "frontmost_app": owner == pid, "mapped": bool(record.get(q.kCGWindowIsOnscreen, False)), "rect": [bounds["X"], bounds["Y"], bounds["Width"], bounds["Height"]]})  # 不将应用焦点盲目赋予每个窗口。
        candidates = [w for w in windows if w["frontmost_app"] and w["mapped"]]  # 寻找唯一前台窗口。
        if len(candidates) == 1:  # 多窗口时必须通过辅助功能补核。
            candidates[0]["focused"] = True  # 唯一情况下才给出推断焦点。
            candidates[0]["focus_source"] = "unique_window_of_frontmost_app"  # 指明不是原生 AX 焦点。
        screen = [0, 0, q.CGDisplayPixelsWide(q.CGMainDisplayID()), q.CGDisplayPixelsHigh(q.CGMainDisplayID())]  # 主显示器回退值。
        windows.reverse()  # 调整堆叠顺序。
        mark_visibility(windows, screen)  # 当前对多屏与 Retina 的覆盖仍需实机校准。
        return {"backend": "macos", "available": True, "windows": windows, "screen": screen, "limitations": ["macOS 适配器尚未实机验证；多屏、Retina 坐标和多窗口焦点覆盖不完整，不应启用强制关闭。"]}  # 不把原型称为跨平台稳定成品。
