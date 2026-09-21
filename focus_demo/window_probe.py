"""按操作系统读取独立窗口画面；不切换焦点、不恢复最小化窗口、不修改合成器配置。"""
import base64  # 传输有界 PNG 字节。
import io  # 保存图片到内存。
import json  # 读取父进程冻结的窗口身份。
import sys  # 选择系统后端。
from PIL import Image  # 解码真实窗口像素，不做 OCR。
from .platforms import process_info  # 防止窗口所属 PID 被复用。


def x11_image(window):  # 功能：只读取合成器已经重定向的窗口像素，不创建隐形窗口或改变焦点。
    from Xlib import X, display  # 仅在 X11 加载原生接口。
    connection = display.Display()  # 为有硬超时的子进程建立独立连接。
    pixmap = None  # 退出时释放本次引用，不销毁原窗口。
    try:  # 不同图形后端可能不支持 Composite。
        if not connection.has_extension('Composite'):  # 无扩展时不可声称读到了独立画面。
            raise ValueError('X11 未提供 Composite')  # 由上层决定有标签的桌面裁剪回退。
        native = connection.create_resource_object('window', int(window['id'].split(':')[-1]))  # 用原生句柄定位。
        prop = native.get_full_property(connection.intern_atom('_NET_WM_PID'), X.AnyPropertyType)  # 校验窗口所属进程。
        if prop is None or int(prop.value[0]) != int(window['pid']):  # 窗口已更换时拒绝旧目标。
            raise ValueError('窗口进程已改变')  # 不把新程序画面附到旧程序。
        if native.get_attributes().map_state != X.IsViewable:  # 最小化后可能只剩陈旧 backing store。
            raise ValueError('窗口未映射，不主动恢复窗口')  # 保留不可用状态。
        # Reparenting WMs redirect the outer frame, not necessarily its client.
        surface = native
        offset_x = offset_y = 0
        client_geometry = native.get_geometry()
        for _ in range(16):
            tree = surface.query_tree()
            if tree.parent.id == tree.root.id: break
            geometry = surface.get_geometry()
            offset_x += geometry.x + geometry.border_width
            offset_y += geometry.y + geometry.border_width
            surface = tree.parent
        pixmap = surface.composite_name_window_pixmap()  # 只引用现有 backing pixmap；不调用 redirect_window。
        geometry = pixmap.get_geometry()  # 读取真实像素尺寸。
        if not 0 < geometry.width * geometry.height <= 32_000_000:  # 限制异常窗口的内存使用。
            raise ValueError('窗口像素规模超出预算')  # 返回明确缺口。
        raw = pixmap.get_image(0, 0, geometry.width, geometry.height, X.ZPixmap, 0xffffffff)  # 读取窗口自身像素。
        fmt = next((f for f in connection.display.info.pixmap_formats if f.depth == raw.depth), None)  # 获取服务端像素布局。
        if fmt is None or fmt.bits_per_pixel not in (24, 32) or connection.display.info.image_byte_order != X.LSBFirst:  # 不猜测未知颜色格式。
            raise ValueError('当前 X11 像素格式暂不支持')  # 调用方记录能力缺口。
        stride = ((geometry.width * fmt.bits_per_pixel + fmt.scanline_pad - 1) // fmt.scanline_pad) * (fmt.scanline_pad // 8)  # 处理行对齐。
        return Image.frombytes('RGB', (geometry.width, geometry.height), raw.data, 'raw', 'BGRX' if fmt.bits_per_pixel == 32 else 'BGR', stride, 1).crop((offset_x, offset_y, offset_x+client_geometry.width, offset_y+client_geometry.height))  # 转换而不补造像素。
    finally:  # 任何异常均不遗留 pixmap 引用。
        if pixmap is not None:  # 仅释放本次取得的引用。
            try: pixmap.free()  # 不销毁应用持有的原图。
            except Exception: pass  # 连接已经失效时由服务器回收。
        connection.close()  # 退出独立连接。


def windows_image(window):  # 功能：用 HWND 调用 PrintWindow；阻塞由父进程硬超时终止。
    import ctypes  # 调用 Windows 原生抓取接口。
    from ctypes import wintypes  # 明确 64 位句柄类型。
    import win32gui, win32ui  # 创建可释放的设备上下文。
    hwnd = int(window.get('native_id', window['id'].split(':')[-1]))  # 只使用原生句柄。
    user = ctypes.WinDLL('user32', use_last_error=True)  # 不执行任意命令。
    user.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]  # 防止句柄截断。
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]  # 绑定进程。
    owner = wintypes.DWORD()  # 接收实际 PID。
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))  # 重新核验目标。
    if owner.value != window['pid'] or win32gui.IsIconic(hwnd):  # 不恢复最小化窗口，不使用失效目标。
        raise ValueError('窗口已变化或最小化')  # 报告明确原因。
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)  # 实际窗口尺寸。
    width, height = right-left, bottom-top  # 计算位图大小。
    if not 0 < width*height <= 32_000_000:  # 限定内存。
        raise ValueError('窗口尺寸无效')  # 不分配异常大位图。
    handle = win32gui.GetWindowDC(hwnd)  # 取得窗口绘制上下文。
    dc = win32ui.CreateDCFromHandle(handle)  # 创建可兼容位图的 DC。
    memory = dc.CreateCompatibleDC()  # 内存绘制不改变桌面布局。
    bitmap = win32ui.CreateBitmap()  # 申请独立图像对象。
    try:  # 确保原生资源释放。
        bitmap.CreateCompatibleBitmap(dc, width, height)  # 使用真实窗口尺寸。
        memory.SelectObject(bitmap)  # 将图像绑定到内存 DC。
        if not user.PrintWindow(hwnd, memory.GetSafeHdc(), 2):  # 请求完整内容，应用可不支持。
            raise ValueError('PrintWindow 未提供有效结果')  # 不假装成功。
        return Image.frombuffer('RGB', (width, height), bitmap.GetBitmapBits(True), 'raw', 'BGRX', 0, 1)  # 读取窗口渲染输出。
    finally:  # 父进程超时退出时系统也会回收子进程资源。
        win32gui.DeleteObject(bitmap.GetHandle())  # 释放位图。
        memory.DeleteDC(); dc.DeleteDC(); win32gui.ReleaseDC(hwnd, handle)  # 释放设备上下文。


def main():  # 功能：窗口原生调用隔离在短命子进程中，不拖死监督调度。
    try:  # 所有结果都明确标识数据来源。
        window = json.loads(sys.stdin.read(16000))  # 仅接收窗口结构，不接受文件路径或代码。
        expected = window.get('process', {}).get('identity')  # 记录冻结进程生命周期。
        if expected and process_info(window['pid']).get('identity') != expected:  # 在读取前核验。
            raise ValueError('进程生命周期已改变')  # 不使用旧 PID。
        if window['id'].startswith('x11:'):  # Linux X11 标准合成接口。
            image = x11_image(window)  # 读取独立画面。
        elif sys.platform == 'win32':  # Windows 标准窗口接口。
            image = windows_image(window)  # 使用受超时限制的 PrintWindow。
        else:  # GNOME 扩展由父进程读取；其他平台明确不足。
            raise ValueError('本平台独立窗口抓取不可用')  # 不将桌面裁剪谎称原生窗口。
        if expected and process_info(window['pid']).get('identity') != expected:  # 读取后再次校验。
            raise ValueError('采集期间进程已变化')  # 不附加歧义图片。
        image.thumbnail((1600, 1200))  # 有限的细节分辨率。
        buffer = io.BytesIO(); image.save(buffer, format='PNG')  # 保存实际窗口像素。
        print(json.dumps({'image': base64.b64encode(buffer.getvalue()).decode(), 'scope': 'native_window_surface', 'notes': ['原生接口输出可能为空白或陈旧；不保证所有 GPU/保护内容可捕获。']}))  # 标明窗口接口边界。
    except Exception as error:  # 无能力时只报错，不输出虚构图像。
        print(json.dumps({'error': type(error).__name__+': '+str(error)[:160]}))  # 给调用方确定的回退依据。


if __name__ == '__main__':  # 仅作单次取证辅助进程。
    main()  # 读取一次后退出。
