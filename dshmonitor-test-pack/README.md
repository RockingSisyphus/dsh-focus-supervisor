# 监工插件测试

唯一用户入口是 `run.py`。`cases/*.json` 是用例定义和选择的唯一来源；`suite.json` 只描述功能分类，`cross-platform.json` 只描述平台环境。

```bash
.venv/bin/python dshmonitor-test-pack/run.py list
.venv/bin/python dshmonitor-test-pack/run.py test
.venv/bin/python dshmonitor-test-pack/run.py test --platform linux --case desktop-fixture-foundation
.venv/bin/python dshmonitor-test-pack/run.py test --platform windows --case product-desktop-loop
.venv/bin/python dshmonitor-test-pack/run.py test --extended
.venv/bin/python dshmonitor-test-pack/run.py test --human-review
.venv/bin/python dshmonitor-test-pack/run.py test --local
```

默认在现有 Linux、Windows VM 运行常规选集。Linux 使用登录后的 GNOME Wayland 桌面；Windows 使用现有系统和普通交互用户。产品场景中的 DSH、浏览器、插件和后台均实际运行；仅模型端点返回固定答案。后台通过正式安装配置连接，测试器不创建替代 Supervisor 或 Sensor。

`--case` 精确选择，不追加安装、重启或其他场景。`--extended` 扩大选集，VM 收到同一批精确 ID。`--local` 只允许契约测试。`--guest` 是 VM 调度器内部入口。`--workers=8` 只并行运行契约测试，同一 VM 的桌面场景串行。人工查看模式运行同一选集并打开 VM 查看器，每个场景结束后保留页面供检查，关闭页面后继续。manual 用例通过 --case 明确选择，不因打开查看器而自动加入故障注入或其他场景。

每次使用新的输出目录。`summary.json` 和 `report.md` 给出 `passed / failed / skipped / not_run`，失败阶段为 `environment / scenario / assertion / cleanup`。`layers` 区分契约、桌面契约和产品流程；契约通过不计入产品功能覆盖。缺少覆盖用例不会沿用历史 PASS。`--baseline` 只比较同平台同 ID 的本轮结果。

每个产品场景保留实际模型请求/回复、页面截图、步骤事实和失败信息。`steps.json` 中失败后的依赖步骤标为 `not_run`；明确独立的断言可以设置 `continue_on_failure: true`，继续收集其他结果，但整个用例仍失败。测试清理发生在产品效果断言之后。

- [VM 环境与安装](VM_TESTING.md)
- [JSON 动作](ACTIONS.md)
- [阶段实施与实测记录](../docs/audit-plan-2026-09-19.md)
- [旧路径归档说明](../docs/archive/test-harness/README.md)

## 固定边界

测试体系不修改生产强杀门禁。第二阶段唤回修复见 [实施记录](../docs/step2-implementation.md)；窗口/标签关闭、采样设置与内容精简已接入当前产品，见[当前架构](../docs/architecture.md)。用户使用强制干预是为了在多次提醒无效后，确实终止分心行为；额外确认、数据丢失阻拦、目标相关性审批会削弱这种最终手段并增加维护负担。用户明确接受这种最终手段可能波及相关窗口/标签或导致数据丢失，不能据此追加确认或阻断关闭。测试不得为了所谓安全增加这些产品门禁。

遇到安装权限界面，按用户愿意输入密码并授权处理，测试自动完成真实授权。目标是安装授权后长期正常使用，不能把频繁重新授权当作正常通过。没有新增免密 polkit 规则或替换 pkexec。测试基础设施失败与产品缺陷分别记录，不把代码检查、固定模型答案或动作返回值单独当作功能成功。
