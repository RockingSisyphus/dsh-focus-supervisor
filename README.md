<p align="center"><img src="dsh-plugin/assets/watching.png" width="160" alt="大肥鱼监工"></p>

# 大肥鱼监工 · DSH Focus Supervisor

让 DSH 中的 AI 根据真实桌面活动监督你自己约定的任务：提醒开始工作、发现偏离后询问、持续提醒，并在必要时最小化或强制关闭分心目标。

**支持 Windows 与 Linux GNOME Wayland。** 浏览器与应用正文通过系统无障碍读取，不需要额外安装浏览器采集扩展或 BrowserSkill。插件不会替 AI 决定什么算分心，也不承诺完整理解所有应用内容。

## 功能

- **任务约定与预约**：在原 DSH 会话中约定任务、时间、完成标准与到时处理；系统重启后恢复尚未结束的任务。
- **桌面证据**：窗口身份、焦点、可见时长、截图、可访问正文及部分应用日志；提供活动变化、分页详情和证据引用。
- **主动心跳**：把近期活动交给原会话，AI 决定是否继续取证、询问或提醒；重复任务背景放入会话动态上下文。
- **原生提醒与唤回**：弹窗、声音和通知，点击后回到对应 DSH 会话和浏览器窗口。
- **实际干预**：最小化窗口；force_close 支持进程、窗口和浏览器标签，精细关闭失败后可升级到关联窗口或进程树。
- **可调采集**：采样周期、图片尺寸、正文/日志长度、浏览器页数、模型概览和分页长度。
- **可选任务保护**：“防任务中修改模式”默认关闭，可随时修改设置、手动结束任务；开启后有预约/进行中任务时锁定设置和开关，并禁止 UI 手动结束。

强制关闭是用户主动选择的最终自我约束手段，**可能关闭同应用的其他窗口、标签，并丢失未保存内容**。不会在执行时再增加保存确认。AI 仍受原会话、任务、报告目标和进程生命周期等现有边界约束。

## 安装

### 前置条件

| 平台 | 要求 |
| --- | --- |
| Windows | 可正常运行的 DSH Web、Node.js、Python 3、Edge；能够确认安装时的 UAC 授权 |
| Linux | 可正常运行的 DSH Web、Node.js、Python 3、Chrome、systemd；当前完整验证环境为 Ubuntu 的 GNOME Wayland |

安装器自动安装后台 Python 环境及相关原生依赖。**Windows 的 Python 3 需先安装**。其他 Linux 发行版、非 GNOME Wayland、macOS 尚未作为完整支持平台验收。下载依赖需要网络。

### 一条命令安装插件

在普通桌面用户终端运行（不要以 root 安装 DSH profile）：

```bash
dsh plugin --profile web add https://github.com/RockingSisyphus/dsh-focus-supervisor/releases/download/v0.4.0/dsh-focus-supervisor.tgz
```

随后：

1. 打开或重启 DSH Web，点击大肥鱼的后台安装按钮。
2. 输入系统密码或确认 UAC；后台服务与启动项由安装器配置。
3. Linux 首次安装 GNOME 桌面扩展时，若提示需要重新登录，请注销并重新登录一次；日常使用不需要反复授权。

这不是“只装 DSH 就零操作完成”：系统授权、Python 前置依赖和首次 GNOME 登录要求仍存在。Windows 无需手动配置计划任务；Linux 无需手动编写 systemd 单元。

### 从插件市场安装

收录目标为 [dsh-market](https://github.com/dsh-market/dsh-market) 使用的社区目录。**首发正在提交收录，只有目录合并并同步后才能在市场搜索到，当前请使用上面的 Release 命令。** 收录后，在 DSH 设置 → 插件市场搜索“大肥鱼监工”或 `dsh-focus-supervisor`，点击安装，再按上述步骤安装后台。

项目声明了 DSH 的 `dsh.bundle` 和 `dsh.client`，Release 提供预构建安装包，不要求用户在安装插件时构建源码。当前没有发布 npm 注册表包，请勿把 `npm install dsh-focus-supervisor` 当作已可用入口。

## 使用

在 DSH 中说：“请监督我完成这项任务”，然后与 AI 约定工作内容、起止时间、完成标准和提醒方式。AI 可通过 `focus_help` 读取接口说明。

悬浮球可查看任务、打开设置和回到会话。工具包括 focus_plan、focus_revise、focus_finish、focus_check、focus_observe、focus_act、focus_status、focus_settings、focus_report 和 focus_help。`focus_act` 的 action 仅为 `remind`、`minimize_window`、`force_close`；窗口/标签关闭通过 force_close 的 target_kind 选择。

`focus_status` / `focus_check` 默认紧凑输出，可用 `detail="full"` 深入读取；`focus_report(operation="read_activity_changes")` 提供活动变化。正文缩短不会删除完整证据或动作引用。插件不限制 AI 额外调查或整个 DSH 会话的 token 用量。

## 数据与边界

桌面正文和截图可能包含敏感内容。后台在本机存储证据，DSH 会把插件交付的信息发送到**你为会话配置的模型服务**；不要将其理解为“数据绝不离开电脑”。插件没有另建云端采集账户。结束任务会按生命周期清理插件证据，DSH 聊天历史仍由 DSH 管理。

一般不采集最小化、完全遮挡、其他工作区或后台标签的新正文。无障碍可能返回视口外文字；Linux 同进程窗口无法逐窗归属时会按组呈现，可能包含隐藏窗口内容，明确交由 AI 结合截图判断。无法读取的内容和采集缺口不会当作已观察事实。

已知待处理：Windows 偶发唤回慢后备（BUG-27）、偶发报告停顿（BUG-32）；不影响本项目如实保留失败记录，参见 [当前问题](docs/known-issues.md)。

## 开发、许可与来源

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-test.txt
node scripts/build-backend-package.mjs
npm pack ./dsh-plugin
```

测试统一入口为 `dshmonitor-test-pack/run.py`，真实产品用例使用独立 VM、真实 DSH、正式后台、固定模型回复和实际 UI 操作；测试环境需自行配置，不会把普通电脑当作可清理的新机 VM。参见 [测试说明](dshmonitor-test-pack/README.md)、[架构](docs/architecture.md)、[使用详情](docs/usage.md)。

本项目原创代码采用 **[GNU AGPL v3（AGPL-3.0-only）](LICENSE)**。分发受该许可约束的作品，或向网络用户提供修改版本时，应履行相应源码提供义务；不等于仅仅使用插件就必须公开你所有无关仓库。准确义务以许可证正文为准，另见 [GNU FAQ](https://www.gnu.org/licenses/gpl-faq.html)。第三方组件仍遵守各自许可。

实际参考及依赖的 DeepSeek Harness、BrowserSkill、Chrome DevTools MCP、Puppeteer、Playwright、Cua 等项目，逐项注明在 [来源与第三方说明](THIRD_PARTY_NOTICES.md)。公开仓库不包含个人聊天、桌面样本、VM 镜像或下载的上游仓库。
