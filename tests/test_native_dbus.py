"""GIO 后备路径的小型协议测试；标准 D-Bus 真通信，不代替 GTK 界面集成测试。"""
import os  # 关闭本测试创建的总线。
import signal  # 指定有限清理动作。
import subprocess  # 启动现有系统 dbus-daemon。
import sys  # 明确隔离缺失 pyatspi 的测试分支。
import pytest  # 测试框架。
from focus_demo.native_dbus import NativeBus  # 实际 GIO 客户端。
from focus_demo import atspi_dbus, ui_probe  # 检查后备选择和独立预算。


@pytest.fixture  # 功能：每个协议测试使用自己的真实总线。
def local_bus():  # 功能：不连接用户已有桌面会话。
    address, pid = subprocess.check_output(['dbus-daemon','--session','--fork','--print-address=1','--print-pid=1'], text=True).splitlines()  # 标准系统守护进程。
    try:  # 即使断言失败也关闭它。
        yield address  # 返回真实地址而非假接口。
    finally:  # 清理当前测试资源。
        try: os.kill(int(pid), signal.SIGTERM)  # 不结束其他会话。
        except ProcessLookupError: pass  # 已退出无需处理。


@pytest.mark.parametrize('address', ['tcp:host=localhost,port=12','unixexec:path=/bin/false','unix:path=/tmp/no;tcp:host=localhost,port=12'])  # 分别拒绝三个不允许的传输形式。
def test_reject_nonlocal_or_multiple_transports(address):  # 单一 Unix 地址之外全部拒绝。
    with pytest.raises(ValueError, match='Unix'): NativeBus(address)  # 不能仅检查字符串开头。


def test_real_dbus_names_pid_and_errors(local_bus):  # 标准总线的名字列表、PID 和错误需真实往返。
    bus = NativeBus(local_bus)  # 打开真实 GIO 连接。
    try:  # 一次连接复用多条只读调用。
        names = bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames','',(),200)  # 数组解码。
        own = next(name for name in names if name.startswith(':'))  # 测试总线中只有当前客户端。
        pid = bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','GetConnectionUnixProcessID','s',(own,),200)  # 字符串参数和无符号整数回复。
        assert pid == os.getpid()  # PID 来自总线认证。
        with pytest.raises(RuntimeError): bus.call('org.nonexistent.Service','/none','org.nonexistent.Interface','NoMethod','',(),100)  # 错误是可恢复异常。
        assert 'org.freedesktop.DBus' in bus.call('org.freedesktop.DBus','/org/freedesktop/DBus','org.freedesktop.DBus','ListNames','',(),200)  # 错误后同一连接仍可用。
    finally:  # 引用释放可以重复调用。
        bus.close(); bus.close()  # 不发生二次释放。


def test_argument_shape_rejected_before_call(local_bus):  # 防止错误参数送入 C ABI。
    bus = NativeBus(local_bus)  # 使用真实连接，测试不是假对象。
    try:  # 调用前先检查类型签名。
        with pytest.raises(ValueError): bus.call('x','/x','x','x','s',(),50)  # 参数缺失。
        with pytest.raises(ValueError): bus.call('x','/x','x','x','o',('/x',),50)  # 本模块没有开放任意复杂参数。
    finally: bus.close()  # 回收系统资源。


def test_missing_python_binding_selects_dbus(monkeypatch):  # 此项是明确的分支选择替身测试，不算实际正文读取。
    monkeypatch.setitem(sys.modules,'pyatspi',None)  # 只在此测试模拟绑定缺失。
    monkeypatch.setattr(atspi_dbus,'linux_batch',lambda windows,chars,nodes:{'selected':'standard-dbus','input':windows,'budget':(chars,nodes)})  # 捕获调用路由，不伪装真实接口。
    assert ui_probe.linux_batch([])=={'selected':'standard-dbus','input':[],'budget':(ui_probe.TEXT_CHARS,ui_probe.TEXT_NODES)}  # 默认路径确实选择标准后备。


def test_dbus_missing_pid_cannot_select_foreign_app(local_bus,monkeypatch):  # PID 不存在时保持不可用，不按标题猜别的应用。
    monkeypatch.setenv('AT_SPI_BUS_ADDRESS',local_bus)  # 真实但没有目标 GTK 应用的总线。
    result = atspi_dbus.linux_batch([{'id':'x11:test','pid':0,'rect':[0,0,1,1]}])  # 这里只构造匹配边界，不算桌面操作。
    assert result['x11:test']['scope']=='unavailable' and not result['x11:test']['text']  # 不产生虚构正文。
