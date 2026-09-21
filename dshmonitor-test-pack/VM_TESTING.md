# VM 测试环境

平台配置路径来自 `cross-platform.json`，默认使用 `~/.config/dshmonitor-test-pack/linux.json` 与 `windows.json`。可通过 `--linux-config`、`--windows-config` 覆盖。密码和 SSH 密钥保持在私人配置中，不写入仓库或报告。

宿主机使用 QEMU/qemu-img、SSH、Tesseract（eng 和 chi_sim）及 Python Pillow；查看器 remote-viewer/spicy 为人工查看所用。缺失依赖会报告环境错误，不替换真实权限界面。

通用实现位于 `test-support/dsh_test_harness/vm/`：生命周期、登录、来宾命令、文件传输、结果回传、查看器和物理输入；没有监工业务步骤。旧 runtime/vendor 路径只转发。每轮记录开始时电源状态，自动启动的 VM 完成后正常关机，原本运行的 VM 保持运行。Windows 使用每轮唯一的普通权限交互计划任务，结束后删除本轮任务；正式后台仍按正式安装方式运行。

## Linux

`--prepare` 安装测试依赖、系统 Chrome 和独立测试侧 GNOME 扩展。扩展变更时重新登录并等待真正的 D-Bus 服务出现。来宾执行器从用户管理器读取实际 Wayland、runtime、D-Bus 环境，并通过用户 systemd 单元启动测试进程，使真实权限界面可在图形登录会话处理。

测试 GNOME 驱动负责布局、前置最小化/恢复、焦点及独立窗口观察。普通原生输入使用 AT-SPI，浏览器是有窗口的 Chrome，实际记录其 `client_type=wayland`。生产最小化/强杀/提醒仍由 DSH 工具调用正式后台。等待过程中不重复激活窗口。

`installation: fresh` 用例使用配置中的 `clean_baseline` 指向的关机 Linux 镜像，建立可丢弃 backing overlay。基线本身没有插件、后台、任务或生产扩展；不能先删除产品再冒充干净环境。磁盘层中设置正常可认证的测试账户，再准备通用测试驱动；准备过程不安装被测产品。测试按市场路径安装插件、点击安装按钮，通过真实权限框输入密码。结束后关机并删除本轮磁盘层，源盘不被修改。没有可用基线时报告环境失败，不在宿主机或日常 VM 中执行清理替代。

## Windows

现有 VM 用于升级与回归，报告标注 `existing-system`。按第四阶段授权另建了 Windows 11 干净基线，来自安装 ISO 和新空盘；`installation: fresh` 使用其可丢弃磁盘层，报告标注 `clean-overlay`，不复制日常系统来冒充新机。普通测试进程使用 Limited 计划任务，后台安装经真实 UAC。画布按钮等没有标准控件的区域，从实际窗口截图定位后，通过 QEMU 物理输入点击，不调用产品按钮处理函数。

Windows 物理鼠标由 `vncdotool` 经 QEMU 的本地 Unix VNC socket 操作，测试启动脚本提供 `dsh-test-vnc.sock`，键鼠使用 QEMU xHCI 控制器（替换测试启动副本中的旧 EHCI，避免端口挂起后漏输入）；宿主依赖见 `requirements-test.txt`。已有 VM 若由其他入口启动，需正常重启到测试启动器，或在其启动参数提供同一 VNC socket。已删除手写 QMP 鼠标输入。前置窗口激活使用系统 UI Automation 按 HWND 执行一次 SetFocus，由独立前台窗口状态判定；不再扫描标题栏、临时置顶或补点，不依赖 AutoHotkey 或输入助手计划任务；不加入生产插件。`--cold-boot` 是旧 CLI 的显式兼容选项，可正常关机再启动，结束时仍按原始电源状态处理。

## 已知产品问题

实际结果和尚未完成的覆盖见 [当前问题](../docs/known-issues.md)。测试侧修复与产品失败必须分开：例如找到窗口和完成点击是测试器事实；目标窗口是否真正最小化、提醒是否回到正确会话，是产品断言。

真实权限框的一次授权是本次安装/升级授权；不代表为任意命令建立永久免密规则。正式服务和启动项由安装器持久化，之后常规用例不重复调用授权动作。用户明确允许测试自动输入密码及确认，不另行向用户索取重复许可。
