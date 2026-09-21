# 测试架构

依赖方向为：`cases JSON → Pack 动作注册表 → 通用 ScenarioEngine/VM/桌面夹具 → 实际 DSH、正式后台及系统控件`。固定模型服务仅替换模型端点。

- `run.py`：选择目录、默认 VM 路由、契约并行、桌面串行和汇总。
- `test-support/dsh_test_harness/catalog.py`：唯一用例发现和精确选择。
- `test-support/dsh_test_harness/scenario.py`：引用、断言、逐步事实与 not_run。
- `runtime/actions/{ui,model,fixture,desktop,backend}.py`：五组动作；预期只放 JSON。
- `test-support/dsh_test_harness/{entities,desktop,gui,native_control}.py`：逻辑 ID、系统窗口、真实控件、布局和独立观察。
- `test-support/gnome-driver/`：测试侧 Wayland 桌面控制，不打包进插件。
- `test-support/dsh_test_harness/vm/`：VM 生命周期、传输、交互用户、输入、授权和可丢弃层；scenario.py 只认识通用 case.run、reboot、command 等步骤。
- `runtime/backend.py`：正式服务外部客户端和只读状态观察，不启动替代 Supervisor/Sensor。
- `test-support/dsh_response_lab/`：固定模型回复与实际请求记录，不决定产品成功。

suite.json 仅维护分类，cross-platform.json 仅维护平台环境。每次来宾运行目录唯一；旧 vendor/runtime 模块是薄转发。测试启动的 VM 正常关机，原已开机的 VM 保持运行。清理只触及本轮资源，发生在独立产品断言之后。

层次、动作参数和故障注入见 [ACTIONS.md](ACTIONS.md)。旧演示与未等价迁移覆盖见 [归档说明](../docs/archive/test-harness/README.md)，不得把直接 Supervisor 测试或页面宿主桩结果提升为产品验收。
