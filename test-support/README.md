# 可复用 DSH 测试支持

分工参照 ERA-Test-Pack / ST-Test-Harness / ST-Response-Lab，未修改或依赖酒馆工具链源码。

- `dsh_test_harness`：JSON 求值、断言、逐步记录、真实 DSH 宿主、Playwright、GUI 工厂与操作系统适配。`ScenarioEngine` 接收外部 `actions` 注册表，不认识监工业务；操作系统差异集中在 `desktop.py`、`gui.py`、`win32.py`。
- `dsh_response_lab`：本机兼容 Chat Completions/Files 的固定回复服务。只按编排返回消息和工具调用，保留实际模型请求及图片；不调用付费模型，不导入监工。
- `../dshmonitor-test-pack`：业务用例 JSON、监工操作适配器、业务测试数据、功能覆盖表。`runtime/json_case.py` 与 `native_actions.py` 把业务操作接到共用执行器。旧 `runtime/host.py`、`model.py`、`ui.py` 等只保留兼容入口。

两模块可通过 `python -m pip install -e test-support` 安装。仓库内兼容入口直接加载它们，不需要修改机器的 Python 搜索路径。新增业务场景使用已有动作时只新增 JSON；新的底层能力仍需新增可复用动作，然后由 JSON 编排，不能凭 JSON 创造尚未实现的系统能力。

Windows 在交互用户桌面执行，Linux 使用真实登录的 GNOME Wayland 桌面。两端使用相同用例和断言。Windows 的测试桌面可能有其他应用，所以业务检查明确限定本轮夹具；完整采集材料保留其他可见应用，不把它们当成不存在。人工审核运行同一场景后保留真实浏览器，关闭页面结束，不另建审核网页。

## 环境

DSH 和 Node 版本、Python 依赖记录在 `runtime.json`。Windows 使用系统已有的 Edge；准备脚本 `prepare_windows.ps1 -Root C:\DafeiyuTest` 在已有 Python venv/QGA 的测试 VM 中安装 Node/DSH/Python 包、创建依赖 junction，并启用 Win32 长路径支持。安装需管理员权限，测试进程仍运行在已登录的交互会话。

Linux 通过 prepare_linux.sh 准备 DSH、系统 Chrome、GTK3、AT-SPI、独立测试侧 GNOME 扩展及原生通知/音频依赖。仅纯 Python/Node 契约测试不需要桌面。真实声音是否被人听见仍由人工审核确认。

VM 通用支持位于 `dsh_test_harness/vm/`，统一入口与动作说明见 [测试 Pack](../dshmonitor-test-pack/README.md)。桌面用例固定串行，契约用例可并行；短且独立的临时目录防止 Unix socket 路径超长，Windows 普通用户执行器使用 python.exe 与有效标准输入句柄。
