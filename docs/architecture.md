# 当前架构与目录

生产路径：DSH → plugin.mjs / chat-host.mjs → 正式HTTP/Unix socket接口 → Supervisor / Control → 普通桌面采集器与原生helper。DSH模型调用留在DSH，后台不再运行旧Demo的模型循环。

| 目录 | 职责 |
| --- | --- |
| dsh-plugin | 工具注册、页面UI、动态上下文、回执投影、默认提示词、角色资源；backend是构建产物 |
| focus_demo | 兼容Python包名，保持安装路径及导入稳定 |
| deploy | Linux/Windows正式安装、升级、服务和原生helper入口；retire_legacy仅清理本插件已退役文件 |
| gnome-extension | 生产窗口身份、可见性、截图及桌面动作 |
| test-support | 通用ScenarioEngine、固定模型、UI/VM/进程与桌面驱动，Windows测试安装准备也在此 |
| dshmonitor-test-pack | 唯一用户测试CLI、业务JSON、夹具和业务动作注册 |
| tests | 当前产品单元、契约及页面宿主协议测试；不以它们代替真实产品验收 |
| scripts | 构建、正式插件注册、profile迁移及开发辅助 |
| vms | 旧调用路径的薄兼容转发，不再维护第二套VM驱动或业务场景 |
| docs/archive | 非运行历史源代码、旧报告及测试快照；代码存为.txt，不导入、不打包 |
| artifacts | 本地报告、聊天/桌面样本、临时包、上游研究与旧原图，不版本控制 |

## 后台模块边界

- 任务和通信：supervisor、control、http_api、store、lifecycle、presence。
- 采集与内容：collectors、details、ui_probe、atspi_dbus、ui_structure、native_browser、generic_logs、sampling_settings。
- 证据与活动：prompts、reports、activity、evidence_export、windows_evidence、materials。
- 动作和平台：actions、close_actions、browser_targets、native_close、window_probe、platforms、native_dbus、process_worker、desktop_setup。

模块按这些职责维护，但不为了目录层级额外搬动所有导入。native_close.py和window_probe.py是可终止子进程入口，不能因为静态import图不可达就删掉。

## 配置与构建

提示词唯一源码为dsh-plugin/default-prompts.json；采样字段唯一定义为focus_demo/sampling-settings.json。安装器复制正式包内容，保存的任务和自定义设置不覆盖。构建脚本只打包当前后台和必要helper，旧网页/网关/审批Demo已从活动源码移除。

本机DSH当前引用正式profile包。旧未引用热更新入口只移入本地artifacts，未修改其他插件或用户profile依赖。旧CLI保留参数转发以免断掉已有调用；所有新场景写入cases/*.json，VM差异留在驱动中。
