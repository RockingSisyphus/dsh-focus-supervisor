"""用真实 GTK3 创建测试界面；只写入控件，不给采集器注入任何数据。"""
import ctypes as c  # 直接调用当前系统 GTK 动态库。
import os  # 输出当前进程，方便与窗口关联核验。
from pathlib import Path  # 保存启动状态。
g = c.CDLL('libgtk-3.so.0')  # 加载系统实际安装的 GTK3。
def bind(name, result, types):  # 为 C 函数声明正确的 ABI。
    fn = getattr(g, name)  # 读取函数。
    fn.restype = result  # 声明返回值。
    fn.argtypes = types  # 声明参数类型。
    return fn  # 返回已绑定的函数。
p = c.c_void_p  # GUI 对象指针类型。
bind('gtk_init', None, [p,p])(None,None)  # 连接真实 X 显示。
new = bind('gtk_window_new',p,[c.c_int])  # 创建顶层窗口。
box_new = bind('gtk_box_new',p,[c.c_int,c.c_int])  # 创建容器。
add = bind('gtk_container_add',None,[p,p])  # 放置子控件。
pack = bind('gtk_box_pack_start',None,[p,p,c.c_int,c.c_int,c.c_uint])  # 排布控件。
for index, marker in enumerate(['ALPHA_REAL_ATSPI_314159','BETA_REAL_ATSPI_271828']):  # 同一进程的独立窗口。
    w = new(0)  # 真正创建窗口。
    bind('gtk_window_set_title',None,[p,c.c_char_p])(w, b'FocusTest GTK same title')  # 标识测试窗口。
    bind('gtk_window_set_default_size',None,[p,c.c_int,c.c_int])(w, 440, 320)  # 设置窗口尺寸。
    bind('gtk_window_move',None,[p,c.c_int,c.c_int])(w, 30+index*480, 40)  # 使几何不同。
    box = box_new(1, 8)  # 创建纵向容器。
    add(w,box)  # 添加容器。
    label = bind('gtk_label_new',p,[c.c_char_p])(f'{marker}\n真实界面文字：正在核验通用无障碍采集。'.encode())  # 显示中英文。
    pack(box,label,0,0,0)  # 放置文字标签。
    entry = bind('gtk_entry_new',p,[])()  # 创建普通输入框。
    bind('gtk_entry_set_text',None,[p,c.c_char_p])(entry, f'VISIBLE_EDITED_VALUE_{index}'.encode())  # 填入可见文字。
    pack(box,entry,0,0,0)  # 放置普通输入框。
    secret = bind('gtk_entry_new',p,[])()  # 创建密码控件。
    bind('gtk_entry_set_visibility',None,[p,c.c_int])(secret,0)  # 设置系统密码角色。
    bind('gtk_entry_set_text',None,[p,c.c_char_p])(secret,b'TEST_PASSWORD_MUST_NOT_LEAK_98765')  # 仅用于检测泄露的假密码。
    pack(box,secret,0,0,0)  # 添加密码字段。
    bind('gtk_widget_show_all',None,[p])(w)  # 真实显示所有控件。
bridge = c.CDLL('libatk-bridge-2.0.so.0')  # 系统自带的真实 AT-SPI 桥。
bridge.atk_bridge_adaptor_init.argtypes=[p,p]  # 声明桥初始化参数。
bridge.atk_bridge_adaptor_init(None,None)  # 启用标准辅助功能发布，不实现假接口。
Path(os.environ['FOCUS_FIXTURE_PID']).write_text(str(os.getpid()))  # 输出进程号供测试匹配。
g.gtk_main()  # 运行真正的 GUI 事件循环。
