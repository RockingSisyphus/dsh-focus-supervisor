# 普通应用结构化观察

Linux AT-SPI 与 Windows UIA 现在保留控件角色、父子层级、名称、文字和可读取的状态，通过共同渲染器输出 `native-ui-tree-v1` 摘录。实现只读取系统无障碍接口，没有应用名单，也不要求 BrowserSkill 或浏览器扩展。

`ui_text` 仍是原有报告的文字入口，现为带缩进的结构摘录；`text_scope=accessibility_structure`，`ui_structure` 提供采集节点数、渲染行数、截断和省略数量。现有心跳报告、程序分支以及 `read_evidence_text` 会自然取得这些文字，`inspect_evidence` 同时返回结构覆盖信息。无需增加新的模型接口或调用模型整理。

渲染规则：省略没有语义内容的布局容器；同一父子关系中重复的静态标签可合并；不同位置的同名按钮保留；字符串内换行转义，避免正文被误当成另一个控件。结构不是可操作句柄。密码和隐藏子树在采集阶段跳过。节点、单段文字、总时间及 12000 字符输出预算仍有界，截断会明确说明。

局限：未实现 OCR；图片、视频、自绘和远程桌面内部内容靠截图补充。无障碍的 showing/visible 状态不是屏幕像素遮挡结果；普通应用的结构摘录不证明用户看到了或理解了全部内容。长窗口可能只取得部分结构。macOS 保持原有文字采集，未在本轮改造或验证。

## 重复测试

普通回归：

```bash
.venv/bin/python -m pytest tests/test_ui_structure.py tests/test_application_capture.py tests/test_native_dbus.py tests/test_evidence_timeline.py tests/test_capture_contracts.py tests/test_report_contracts.py -q
```

真实双窗口 GTK 测试，在实际登录的 GNOME Wayland 桌面编辑真实控件并通过 DSH 验证采集；多窗口布局和读回由共用夹具覆盖：

```bash
.venv/bin/python dshmonitor-test-pack/run.py test --platform linux --case application-native-desktop --case desktop-fixture-foundation --output artifacts/structured-gtk-new-run
```

真实 GNOME 桌面，先自行布置窗口，再只读采集：

```bash
.venv/bin/python dshmonitor-test-pack/runtime/structured_desktop.py --backend gnome --output artifacts/structured-desktop-new-run
```

Windows 在登录用户的交互桌面中：

```powershell
C:\DafeiyuTest\venv\Scripts\python.exe dshmonitor-test-pack\runtime\structured_desktop.py --backend windows --output C:\DafeiyuTest\results\structured-new-run
```

QEMU Guest Agent 直接执行命令处于 Session 0，需按 WINDOWS_VM.md 的方式注册交互式按需任务再启动。上述脚本保存 samples.json、截图及实际 AI 报告 ai-report.json；completed.json 只代表采样完成。原始内容可能包含个人界面，保存在忽略 Git 的 artifacts 下，不提交或上传。

## 本次实际结果（2026-09-17）

- Linux 当前 GNOME 桌面：文件管理器 521 个控件整理为 194 行，QQ 378 个控件为 159 行，虚拟机查看器 35 个控件为 17 行；Codex 为 277 行，触发长度上限并明确标记。后者只取得当前应用的部分结构，不能宣称内容完整。
- Windows 真实交互会话：商店 61 个控件为 42 行，保留“主页 selected”、搜索分组和安装按钮；Edge 93 个控件为 53 行，包含工具栏、网址、页面及标签状态；迅雷浮窗只得到自身的少量结构，不把它冒充迅雷主界面。
- 普通 Linux 回归 97 项通过；Windows 应用/结构回归 13 项通过；真实 GTK 集成 8 项通过，包括密码与隐藏内容排除、修改后更新、同 PID 同标题双窗口不串读、无障碍断连后截图保留。
- 真实材料：`artifacts/structured-ui/`。不调用模型，不把测试结果宣称为模型理解通过。

修改已同步到 Windows VM 测试目录。Linux 实测运行的是本项目源码；现有 root 所有的 `/opt/dafeiyu` 常驻安装没有在本轮升级。下一次运行项目的 `deploy/upgrade-chat.sh` 会随整个 focus_demo 目录安装新渲染器，不额外引入依赖。
