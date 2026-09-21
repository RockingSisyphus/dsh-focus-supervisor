# Windows 虚拟机采集环境

## 当前布置（2026-09-17）

使用现有 Quickemu Windows 11 VM，没有新建或替换磁盘。通过 QEMU Guest Agent 执行 PowerShell、传输源码；不需要 Windows SSH 密码，也没有额外开放 SSH 服务。

- Linux 启动入口：`~/VMs/quickemu/start-windows-11.sh`，启动并显示 SPICE 窗口。
- Guest Agent socket：`~/VMs/quickemu/windows-11/windows-11-agent.sock`。
- Windows 用户：`rocki`；环境根目录 `C:\DafeiyuTest`。
- Python 3.13.15 x64：`C:\DafeiyuTest\Python313`。
- 独立 Python 环境：`C:\DafeiyuTest\venv`。
- 项目采集源码、测试包：`C:\DafeiyuTest\project`。
- 安装 requirements-test.txt 和微软 Visual C++ x64 运行库；修正项目 Windows 依赖为实际使用的 pywinauto、pywin32。

环境准备仅做依赖检查和交互会话验证，没有启动实际应用采集。此目录是 Windows **采集核心测试环境**，不是已完成移植的 Windows 常驻监工服务或已验收的完整 DSH 插件安装。BrowserSkill 专用浏览器通道默认关闭，当前准备先验证 Windows 通用窗口/UIA/截图采集；完整浏览器接入另行配置验证。

## 在用户布置好桌面后手动测试

`test-support/prepare-windows-test.ps1` 注册两个按需任务，没有开机/定时触发器：

- `Dafeiyu-Test-ready`：仅记录 Python、导入结果与会话编号；准备时运行。
- `Dafeiyu-Test-capture`：运行生产 Collector，默认 10 次真实采样、2 秒间隔；准备时不运行。

两个任务使用当前登录用户的 Interactive token，避免 Guest Agent 的 SYSTEM / Session 0 被误当作用户桌面。Windows 需保持登录且未锁定。

用户确认桌面布置完成后，通过 Guest Agent 执行下列 PowerShell：

```powershell
Start-ScheduledTask -TaskName 'Dafeiyu-Test-capture'
```

采集材料写入 `C:\DafeiyuTest\results\capture`。`completed.json` 只表示采样结束，必须另外核对 `samples.json` 和图片，不代表功能合格。修改布局前先取回本轮材料；下一轮可注册新的输出目录，避免覆盖上一轮原始证据。

宿主调用示例：

```bash
python3 dshmonitor-test-pack/runtime/qemu_guest.py \
  --socket "$HOME/VMs/quickemu/windows-11/windows-11-agent.sock" \
  --script /absolute/path/to/explicit-command.ps1
```

超时时返回 Windows PID，使用 `--status PID` 查询同一进程，不要重复启动安装器或采集任务。控制通道不会改变 Guest Agent 服务以外的系统远程访问配置。

后续测试范围：用户自行打开软件，确认焦点、完全遮挡、部分遮挡、最小化；检查独立窗口图是否为空白/混入遮挡画面、UIA 是否读到实际正文、日志来源是否真实。暂不执行关闭应用、通知、任务预约或收费模型调用。

官方安装来源：[Python Windows](https://www.python.org/downloads/windows/)、[Microsoft Visual C++ Runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist?view=msvc-170)。

## 2026-09-17 实测与修复

在上述交互桌面中，实际跑过最大化布局、浏览器与商店部分重叠布局。测试未调用模型。

- UIA 探针曾因中文 Windows 的 GBK 无法输出 U+200B 零宽字符而整批失败。探针现在通过 ASCII 转义 JSON 传输全部 Unicode，不要求用户改系统代码页。
- 原生窗口采集读取 DWM cloaked 状态、显式窗口区域和分层透明属性。桌面外壳不再作为应用取证对象；透明浮窗不作为不透明遮挡矩形。无法查询逐像素透明度时，`visible=null`、面积未知，保留可供 AI 查阅的截图与原因，不累计已确认可见时长。这是保守估计，不承诺所有透明/自绘窗口的逐像素精确判断。
- 日志只沿相同可执行文件的辅助进程链采集。不同程序即使由该进程启动也不算其日志；不同可执行文件的助手可能因此少收集，不能以父子进程关系证明属于同一应用。Windows 系统事件日志尚未接入。
- 重叠布局 5 次采样中，Edge 和商店均有实际界面文字与独立窗口图，文件管理器完全遮挡时无正文/截图，迅雷主窗在后台被排除。迅雷浮窗单独保留、不冒充其主界面。图片中的字不一定有 UIA 文本，独立窗口截图也可能有 GPU/透明区域显示差异。

回归用例在 `tests/test_application_capture.py`：GBK Unicode 协议、启动器与子应用日志隔离、透明浮窗遮挡、不规则窗口区域、未知可见性到 AI 报告的传递，以及真实同程序子进程日志。Windows 可在已准备环境中运行：

```powershell
C:\DafeiyuTest\venv\Scripts\python.exe -m pytest tests/test_application_capture.py -q
```

这组回归不替代实际 GUI 验收；原始桌面、窗口截图和 `samples.json` 仍需配合核对。

实现依据：[DWM 窗口属性](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)、[分层窗口透明度查询及限制](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlayeredwindowattributes)。
