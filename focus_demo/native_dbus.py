"""通过系统 GIO 读取 D-Bus；只负责协议编解码，不实现任何应用适配。"""
import ctypes as c  # 使用标准库调用已经安装的系统动态库。


class Error(c.Structure):  # 功能：读取 GIO 返回的标准错误结构。
    _fields_ = [('domain', c.c_uint), ('code', c.c_int), ('message', c.c_char_p)]  # 对齐 GLib GError ABI。


class NativeBus:  # 功能：复用一条真实本机连接，避免每个控件都启动一个命令。
    def __init__(self, address=None):  # 功能：连接现有辅助功能总线或用户会话总线。
        self.glib = c.CDLL('libglib-2.0.so.0')  # 加载 Linux 桌面公共 GLib 库。
        self.gio = c.CDLL('libgio-2.0.so.0')  # 加载标准 GIO D-Bus 客户端。
        self.obj = c.CDLL('libgobject-2.0.so.0')  # 管理系统对象引用。
        p = c.c_void_p  # C 对象指针类型。
        self.error_free = self.bind(self.glib, 'g_error_free', None, [p])  # 错误对象释放器。
        self.unref = self.bind(self.glib, 'g_variant_unref', None, [p])  # GVariant 引用释放。
        self.kind = self.bind(self.glib, 'g_variant_get_type_string', c.c_char_p, [p])  # 获取实际序列化类型。
        self.size = self.bind(self.glib, 'g_variant_get_size', c.c_size_t, [p])  # 拒绝无界回复。
        self.count = self.bind(self.glib, 'g_variant_n_children', c.c_size_t, [p])  # 限制容器元素数。
        self.child = self.bind(self.glib, 'g_variant_get_child_value', p, [p, c.c_size_t])  # 获取拥有独立引用的子值。
        self.string = self.bind(self.glib, 'g_variant_get_string', c.c_char_p, [p, p])  # UTF-8 字符串读取。
        self.getters = {key: self.bind(self.glib, 'g_variant_get_' + name, result, [p]) for key, name, result in [('i', 'int32', c.c_int32), ('u', 'uint32', c.c_uint32), ('b', 'boolean', c.c_int), ('t', 'uint64', c.c_uint64), ('x', 'int64', c.c_int64), ('d', 'double', c.c_double), ('q', 'uint16', c.c_uint16), ('n', 'int16', c.c_int16), ('y', 'byte', c.c_ubyte)]}  # 解码协议常用标量。
        self.builders = {key: self.bind(self.glib, 'g_variant_new_' + name, p, [argument]) for key, name, argument in [('s', 'string', c.c_char_p), ('i', 'int32', c.c_int32), ('u', 'uint32', c.c_uint32)]}  # 本模块仅允许三个必要参数类型。
        self.tuple = self.bind(self.glib, 'g_variant_new_tuple', p, [c.POINTER(p), c.c_size_t])  # 构建类型安全的参数元组。
        self.sink = self.bind(self.glib, 'g_variant_ref_sink', p, [p])  # 明确管理浮动引用。
        self.object_unref = self.bind(self.obj, 'g_object_unref', None, [p])  # 连接对象释放。
        self.invoke = self.bind(self.gio, 'g_dbus_connection_call_sync', p, [p, c.c_char_p, c.c_char_p, c.c_char_p, c.c_char_p, p, p, c.c_int, c.c_int, p, c.POINTER(p)])  # 绑定公开的 GIO 同步调用接口。
        self.connection = None  # 构造失败时不释放无效指针。
        error = p()  # GError 必须初始化为空。
        if address is None:  # 普通桌面先查询标准辅助功能总线地址。
            constructor = self.bind(self.gio, 'g_bus_get_sync', p, [c.c_int, p, c.POINTER(p)])  # 标准用户会话总线。
            self.connection = constructor(2, None, c.byref(error))  # G_BUS_TYPE_SESSION 的固定枚举值。
        else:  # 已有明确的本机辅助功能地址。
            if not isinstance(address, str) or not address.startswith('unix:') or ';' in address or '\x00' in address or len(address) > 4096:  # 只允许单一本机地址，不接受远端后备或复合传输。
                raise ValueError('只允许现有本机 Unix D-Bus 地址')  # 限制连接范围。
            constructor = self.bind(self.gio, 'g_dbus_connection_new_for_address_sync', p, [c.c_char_p, c.c_int, p, p, c.POINTER(p)])  # 公共客户端构造函数。
            self.connection = constructor(address.encode(), 9, None, None, c.byref(error))  # 客户端认证加消息总线握手，不充当服务端。
        if not self.connection:  # 失败时提取真实系统错误。
            raise RuntimeError(self.message(error))  # 不伪造总线成功。
        self.bind(self.gio, 'g_dbus_connection_set_exit_on_close', None, [p, c.c_int])(self.connection, 0)  # 总线断开只使取证失败，不主动终止调用方。

    @staticmethod  # ABI 声明不需要对象状态。
    def bind(library, name, result, arguments):  # 功能：集中声明系统函数签名。
        function = getattr(library, name)  # 仅访问源码指定的公开函数。
        function.restype = result; function.argtypes = arguments  # 防止指针被截断。
        return function  # 返回已绑定函数。

    def message(self, pointer):  # 功能：提取并释放标准 GError。
        if not pointer:  # 某些接口可能没有附加说明。
            return '系统 D-Bus 调用失败，未提供详细原因'  # 保留明确错误状态。
        value = c.cast(pointer, c.POINTER(Error)).contents.message.decode('utf-8', 'replace')  # 只解码错误文字。
        self.error_free(pointer)  # 释放系统分配的错误对象。
        return value[:300]  # 不输出无限长度系统错误。

    def decode(self, value, depth=0):  # 功能：把有限 GVariant 转为 Python 数据，不执行内容。
        if depth > 16 or self.size(value) > 512000:  # 限制恶意或异常控件返回的复杂度。
            raise ValueError('D-Bus 返回超过深度或大小预算')  # 拒绝无界解码。
        kind = self.kind(value).decode()  # 读取标准类型字符串。
        if kind in ('s', 'o', 'g'):  # 字符串、对象路径和类型签名。
            return self.string(value, None).decode('utf-8', 'replace')  # 保留原始 Unicode 内容。
        if kind in self.getters:  # 数字和布尔标量。
            return self.getters[kind](value)  # 按实际 ABI 解码。
        if kind[0] not in 'a(v{':  # 不接受未知复合类型。
            raise ValueError('不支持的 D-Bus 返回类型：' + kind)  # 明确说明缺口。
        length = self.count(value)  # 获取实际子项数量。
        if length > 2048:  # 防止一次返回整份超大文档结构。
            raise ValueError('D-Bus 容器项数超过预算')  # 交由上层报告不完整。
        items = []  # 逐项转为独立 Python 数据。
        types = []  # variant 保留内部类型，与现有解析结构一致。
        for index in range(length):  # 处理有界子项。
            child = self.child(value, index)  # 取得新的引用。
            try:  # 无论解析成功与否，都要释放引用。
                types.append(self.kind(child).decode())  # 记录实际类型。
                items.append(self.decode(child, depth + 1))  # 递归处理标准数据。
            finally:  # 不使辅助功能循环泄漏内存。
                self.unref(child)  # 释放子值引用。
        if kind == 'v':  # 统一 variant 的可检查结构。
            return {'type': types[0], 'data': items[0]}  # 不将未知 variant 当可执行指令。
        return dict(items) if kind.startswith('a{') else items  # 字典与数组分别返回。

    def call(self, name, path, interface, method, signature, values, timeout_ms):  # 功能：只读方法调用，由上层固定其业务范围。
        if len(signature) != len(values) or any(key not in self.builders for key in signature):  # 参数只支持模块用到的基础类型。
            raise ValueError('无效的 D-Bus 请求参数')  # 不运行任意解析器代码。
        parts = [self.builders[key](value.encode() if key == 's' else int(value)) for key, value in zip(signature, values)]  # 构建类型安全参数。
        parameters = self.sink(self.tuple((c.c_void_p * len(parts))(*parts), len(parts)))  # 把所有浮动子值交给元组管理。
        error = c.c_void_p()  # 初始化可恢复错误指针。
        try:  # 同步请求拥有明确毫秒超时。
            reply = self.invoke(self.connection, name.encode(), path.encode(), interface.encode(), method.encode(), parameters, None, 0, timeout_ms, None, c.byref(error))  # GIO 完成本机消息交换。
            if not reply:  # 不将通信错误当作空正文。
                raise RuntimeError(self.message(error))  # 上层按覆盖缺口处理。
            try:  # 返回结果可能来自快速变化的真实控件树。
                data = self.decode(reply)  # 解码后立即脱离系统对象引用。
                return data[0] if len(data) == 1 else data  # 解包标准单返回值元组。
            finally:  # 释放整份回复。
                self.unref(reply)  # 不累积消息缓冲。
        finally:  # 请求参数始终释放。
            self.unref(parameters)  # 元组同时释放其子值。

    def close(self):  # 功能：结束本批连接，不改变 GUI 应用状态。
        if self.connection:  # 只处理实际打开的连接。
            self.object_unref(self.connection)  # 释放本客户端引用。
            self.connection = None  # 防止重复释放。
