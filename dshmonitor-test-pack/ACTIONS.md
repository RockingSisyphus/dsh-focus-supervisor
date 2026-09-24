# JSON 场景与动作

`cases/*.json` 是唯一用例目录。必需元数据：`id`、`title`、`engine`（`dsh`/`command`）、`platforms`（`linux`/`windows`）、`group`（`regular`/`extended`/`manual`）、`verification`（`contract`/`desktop-contract`/`product`）。`timeout` 以秒为单位。`features` 对应 suite.json 分类。命令型契约用例提供 `argv`，支持 `$python`、`$output`、`$case`。

每个步骤有唯一 `id` 和 `op`，可用 `bind` 保存结果。`{"$ref":"名称.字段"}` 引用事实，支持 `$merge`、`$concat`、`$json`、`$time_after`、`$iso_after`。断言使用 `actual`、`operator`、`expected`；operator 支持 equals、not_equals、contains、not_contains、count、gt、lt、exists。断言失败不修改产品结果。

## 五组动作

注册表位于 `runtime/actions/`。每个动作返回事实，预期写在 JSON。以下是推荐的新增场景接口；现有用例保留旧步骤 ID 和兼容动作拼写。

| 组 | 动作 | 参数和结果 |
|---|---|---|
| UI | `ui.workspace`, `ui.open`, `ui.close` | 通过真实 DSH 页面选工作区、开关插件面板 |
| UI | `ui.click` | selector；实际页面控件点击 |
| UI | `ui.settings` | values、save；真实设置控件输入和保存 |
| UI | `ui.snapshot`, `ui.screenshot` | 读取页面或保存截图；screenshot 提供 name |
| UI | `ui.wait_plugin_state` | path、equals、timeout；轮询插件公开状态接口 |
| 模型 | `model.reply` | user、text；页面提交消息，固定端点返回文本 |
| 模型 | `model.call` | user、tool、arguments；经真实 DSH 调用工具，返回 value/raw/call_id |
| 模型 | `heartbeat.enable` | 固定端点接收真实心跳，返回 focus_observe |
| 夹具 | `fixture.app` | entity、windows、refuse_close；一次创建同进程窗口，多次调用创建多进程 |
| 夹具 | `fixture.browser` | entity、new_window、window、url/html；真实窗口或指定逻辑窗口的新标签 |
| 夹具 | `fixture.window` | entity、action（layout/activate/minimize/restore/close）、rect；操作后返回独立实际状态 |
| 夹具 | `fixture.interact` | entity、action（fill/click/select/navigate/scroll）；网页 selector/text/url/dy，原生控件 role/name 或 Windows control |
| 桌面 | `fixture.observe`, `fixture.wait`, `desktop.snapshot` | 实际窗口 ID/PID、位置、焦点、最小化状态；浏览器另有 tab_id/browser_window_id/visibility |
| 桌面 | `native.authorize` | 实际系统授权；Linux 密码由一次性 VM 环境提供，Windows 通过 VM 输入通道确认 UAC |
| 桌面 | `desktop.popup_click` | 点击本轮真实通知窗口内按钮，并确认窗口消失 |
| 后台观察 | `state.read`, `state.wait`, `state.fields` | 读取正式服务/持久化状态；wait 使用 task_id/status |
| 后台观察 | `report.wait`, `report.target` | 等真实报告、按逻辑实体映射实际证据 target_ref |
| 后台观察 | `evidence.inspect` | 以正常用户读取正式导出的证据；权限不足真实失败 |
| 生命周期 | `backend.restart` | 故障恢复前置操作；不替代工具调用 |

`fixture.page` 将当前真实 DSH 页绑定到逻辑 ID；优先用浏览器 PID，必要时临时唯一标题定位后恢复标题。`fixture.wait` 使用 expected 字段路径与 timeout 等待事实，返回 matched 及最后观察，不执行激活。

`fixture.window` 仅用于前置条件、观察及清理。验收最小化/强杀/提醒必须使用 `model.call`，然后用 `fixture.observe` 或原生快照独立断言。不能用夹具关闭后宣称产品关闭成功。窗口通过 PID 与原生 ID 绑定，即使同标题也不猜目标。Wayland 布局后读取实际位置；等待过程中不重复激活。

## 最小示例

```json
{
  "schemaVersion": 1,
  "id": "example", "title": "真实聊天与标签输入", "engine": "dsh",
  "platforms": ["linux", "windows"], "group": "extended", "verification": "product",
  "features": ["test-reporting"], "timeout": 180,
  "steps": [
    {"id":"workspace", "op":"ui.workspace"},
    {"id":"reply", "op":"model.reply", "user":"测试开始", "text":"已收到测试。"},
    {"id":"page", "op":"fixture.browser", "entity":"notes", "html":"<title>笔记</title><input id='note'>"},
    {"id":"input", "op":"fixture.interact", "entity":"notes", "action":"fill", "selector":"#note", "text":"真实页面输入"}
  ]
}
```

完整的多窗口/同标题/多标签与读回断言见 `desktop-fixture-foundation.json`；真实采样、心跳、提醒、最小化、强杀见 `product-desktop-loop.json`。

## VM 层 JSON

`engine: command`、`execution: vm-orchestration` 用于跨重启流程。`case.run` 的 cases 是精确用例 ID，返回本次报告；`vm.reboot` 返回 before/after 启动标识。Windows 的 `vm.command.start` 从普通交互用户启动 argv，`vm.authorize` 接受真实 UAC，`vm.command.wait` 返回退出码和输出。业务预期仍由 JSON assert 表达。示例：`vm-login-recovery.json`、`windows-install-upgrade.json`。

Linux `installation: fresh` 在可丢弃层执行；不把准备过程当作产品安装。Windows existing-system 在现有 VM 内执行安装/升级。`ui-setup-click-windows` 是尚未安装后台时的一次按钮安装路径，列为 manual，不卸载系统来强造该状态。

## 报告与故障注入

每次来宾执行使用唯一目录，不复用完成标记。`result.json`、`steps.json`、模型请求、页面/原生截图与主报告共同组成证据。环境失败不会降级到替代后台。

`failure-missing-control`、`failure-service-unavailable`、`failure-success-with-live-target` 是显式人工选取的测试器故障注入；正确行为是 failed 和非零退出。第三项仅在该注入步骤伪造返回成功，后续独立窗口观察必须判失败；不能将这组结果计为产品通过。

## 跨退出、跨重启的真实会话

- `desktop.browser_exit` 通过浏览器关闭命令建立“应用已退出”的前置条件，并等待实际进程消失；它不是被测强关能力。
- `desktop.browser_reopened` 只观察新原生窗口和实际辅助功能文字，不打开页面、不切会话、不反复抢焦点。
- `default_browser: true` 让操作系统的真实 URL 启动命令临时指向本轮 Chrome/Edge profile；测试后恢复原关联。否则最初测试页和随后系统默认页会落入不同 profile，无法等价模拟用户关闭再打开自己的浏览器。
- `persistent_session: true` 的 VM 编排为其 `case.run` 分配同一临时 DSH profile。`session.save` 保存指定场景值并把该任务的清理交给恢复段；`session.load` 恢复引用，生产任务和会话本身由正式服务与 DSH 持久化。
- `report.wait` 可用 `created_after` 和 `exclude` 只观察恢复后产生的新报告；`model.tool_result` 按工具名和参数找到真实 DSH 回传的工具消息。
- 需要独立窗口画面的场景可在 `report.wait` 指定 `window_id` 和 `screenshot_scope: native_window_surface`，等待正式报告真正出现该范围的图片，再运行原有断言。持续观察窗口内容的场景用 `present_user: true` 明确模拟用户在场；否则后台会按设计转入离席并停止正文和图片采集。
- `vm-active-task-recovery` 结束或失败后，VM 层清理保存的那个测试任务和临时 profile。阶段失败与清理失败分别保留。

BrowserSkill 场景按正常 `dsh plugin add` 安装 0.3.0 插件，并操作 Chrome/Edge 扩展管理页加载真实扩展。VM 需安装对应平台的 `bsk`，并提供 `~/.local/share/dsh-test/browserskill-extension`（或 `BSK_TEST_EXTENSION`）中的真实扩展文件。本轮使用已安装的官方 0.3.0 扩展文件和官方 CLI；不复制浏览器账号、Cookie 或个人 profile。Windows 测试守护进程在普通交互用户下运行，使用本轮独立 `BSK_HOME`；该临时运行目录不打包为产品证据。

## 提醒唤回回归

`reminder-focus-*.json` 和 `reminder-reopen-browser.json` 共用以下动作。Linux 驱动只在 GNOME Wayland 执行，Windows 使用普通交互用户；驱动不修改产品判据。

| 动作 | 输入与事实结果 |
|---|---|
| `fixture.browser_state` | `entity` 指定逻辑窗口；返回标签 ID、visibility、选中标签及 `selection_source`。不能确定时 `selected=null`，不把隐藏等同于未选中。 |
| `fixture.watch_input` | `entity`、`seconds`、`chunks`；分段真实键入，记录前台时间线、实际控件文本和 `focus_retained`。不重复激活目标。 |
| `desktop.workspace` | 移动指定窗口并切换工作区；只建立前置条件，结束恢复原工作区。 |
| `desktop.popup_position` | `pid`、`side`；真实拖动提醒，使连续点击时两个按钮不互相遮挡。 |
| `desktop.popup_click` | 可选 `pid`、`wait_closed`；点击真实按钮，记录坐标及关闭事实，不直接调用产品回调。冻结页面场景可设 `state_probe: false`、`observe_page: false`，避免测试器先唤醒被测页面。 |
| `ui.wait_focus_result` | `timeout`；从本次点击计时，读取新请求终态。旧请求的 completed 不算本次完成。 |
| `ui.focus_diagnostics` | 记录请求状态、页面会话、原生窗口及浏览器标签栏；不修改焦点。 |
| `ui.restart_dsh` | 同 profile、同端口重启测试 DSH，观察页面令牌更新；`reload_page: false` 保留原标签状态，不由测试器刷新。 |
| `ui.use_claimant` | 将实际认领页面与已有逻辑窗口对应，用于多个 DSH 页面。 |
| `ui.use_opened_page` | 浏览器正式入口新开页面后连接观察，不代替生产选页或激活。 |

JSON 中显式断言会话、标签、原生前台、最小化状态、标签数量及输入结果。热态 10 秒、冷态 60 秒，成功后切到原生输入框观察 30 秒。测试恢复/选页仅用于前置条件和明确的后续用户操作；生产恢复期间禁用测试器补救。后台断连、控件找不到和原生观测失败均保留为失败，不改用 mock。

弹窗唤回的生产选页统一走 Linux AT-SPI 或 Windows UIA，再核对原生窗口和目标会话；即使测试浏览器已有 CDP 连接，也不能把连接本身当作唤回成功。`reminder-focus-native-connected` 在 Windows 验证已有连接时实际选页来源仍是 UIA。普通 Chrome/Edge 标签由系统 AT-SPI/UIA 标识并点击标签自身的关闭按钮，不要求远程调试端口。已有 CDP 连接仍可作为可选技术通道，不用于正文采集或唤回；其专项用例列为扩展测试，不计入普通浏览器验收。`force-close-browser-default`、`force-close-browser-minimized-native` 与 `force-close-browser-background-native` 验证普通浏览器的精确关闭与兄弟标签保留。

`fixture.page_lifecycle` 可在真实 Chrome/Edge 标签上设置 `frozen` / `active`，只用于建立浏览器页面生命周期前置条件。冻结期间 `fixture.wait(native_only: true)` 只读原生窗口，不访问页面 JavaScript；先独立确认产品恢复原窗口，再解除测试侧强制冻结并核对原页认领请求。`reminder-focus-stale-minimized` 验证 DSH 重启后旧标签恢复，`reminder-focus-frozen-live` 验证 DSH 持续运行时的旧标签恢复，`reminder-focus-frozen-background-native` 验证后台标签的原生后备；后者移除测试 profile 的端口发现文件。

提醒及冷启动浏览器以本轮实际创建的 PID/启动时间或专用 profile 清理，包括隐藏中的提醒；不清理日常浏览器。

`reminder-focus-native-default` 还对齐了本机的默认辅助功能条件：`browser_accessibility: false` 不添加强制辅助功能启动参数；`desktop_settings` 通过真实 GSettings 设置 GNOME 屏幕阅读器为关闭，并记录原值与实际值，清理时恢复。测试器的 AT-SPI 操作只访问指定应用的总线，兼容 `button/push button`、`entry/text` 角色名称，不遍历其他应用来准备按钮点击。这样不会依赖测试环境预先开启屏幕阅读器。

Windows 首次启动 Edge 出现 `Got it` 时，通过真实 UIA Invoke 操作该按钮并确认消失，记录在 `browser-setup.json`。这是浏览器环境准备；生产提醒按钮仍通过真实 VM 鼠标点击。其他应用通知遮挡引起的历史准备失败继续保留。

## 强制关闭目标与困难夹具

- `fixture.app` 支持 `refuse_close: true`、`close_behavior: save_prompt | hang` 和 `child_processes`。关闭事件写入夹具目录 `close-events.jsonl`；保存提示是真实原生对话框，hang 在收到原生关闭事件时阻塞应用。`fixture.observe` 的 `alive_children` 独立读取本轮子进程状态。
- `fixture.browser` 的 `native_only: true` 使用独立 Chrome/Edge profile 正常启动目标窗口和兄弟标签，不设置调试端口；`instance: "已有夹具ID"` 在同一 profile 和进程中另开窗口，可验证同进程同标题同尺寸的歧义场景。`fixture.select_tab` 通过原生无障碍接口建立后台标签前置条件。`separate_instance: true` 只用于扩展的已有连接技术场景。原生浏览器的 `fixture.interact(action="click")` 可点击真实网页控件并建立 `beforeunload` 用户激活；受 Playwright 控制的协议场景仍可用 `beforeunload_probe`。
- `report.target` 默认匹配原生窗口；`kind: browser_tab` 按 AT-SPI/UIA 的实际标签身份或已有连接的标签 ID 匹配正式报告引用。没有正文或截图不排除已有身份的动作目标；报告缺少目标时直接指出这一前置失败。
- `desktop.hide_browser_connection(entity=...)` 对指定测试 profile 移除端口发现文件。测试器保留已建立的连接用于独立观察，这是明确的连接故障注入，不代表浏览器从启动时就未开启调试。
- `force-close-*.json` 通过固定模型调用真实 `focus_act`；所有效果断言在清理之前。`minimize-window-state` 单独验证真实最小化状态。

`force-close-browser-default` 从启动时不设置调试端口，正式报告记录目标标签的原生身份。Linux 先激活报告关联的 GNOME 窗口再执行 AT-SPI 关闭按钮；Windows 最小化时先恢复该 HWND，再通过 UIA 关闭按钮。两端均独立核对目标标签消失、同窗口兄弟标签和窗口保留。精确关闭失败时，普通 `browser_tab` 调用返回失败而不扩大关闭范围。

`force-close-browser-same-size-windows` 在 Linux 上通过真实 DSH 报告取得目标后，于同一 Chrome 进程内再建两个同标题同尺寸窗口。测试侧保存目标和兄弟标签的 AT-SPI 对象身份并独立读取最终状态，避免观察器自身也重做有歧义的窗口尺寸匹配；断言目标标签消失且三个窗口和兄弟标签均保留。

`report.read(report_id)` 只读取正式后台持久化报告。历史 CDP 连接故障场景先由真实 DSH `focus_check` 生成最新报告，再观察引用并移除测试端口发现文件；该场景已从可运行目录移除，历史版本保留在 Git。当前普通浏览器场景不创建调试端口，不伪造采样或修改报告。

### 强制关闭场景与产品接口

`force-close-*.json` 使用正式任务、`focus_check` 报告和 `report.target` 取得引用，然后由 `model.call` 经 DSH 调用 `focus_act`。不把夹具 PID 直接传给产品。普通浏览器的真实验收使用 `native_only` 夹具，实际读取目标进程命令行确认没有调试端口。旧版依赖 CDP 的标签场景已从可运行用例目录移除，历史版本可从 Git 追溯；CDP 仅保留现有连接的协议契约测试，不作为产品验收前提。

```json
{"task_id":"任务编号","action":"force_close","report_id":"报告编号","target_ref":"报告引用","target_kind":"browser_tab"}
```

首次标签关闭返回 `closed=false` 且 `escalation_available=true` 时，再次用 `focus_act(action="remind")` 告知整个浏览器可能关闭。若用户仍未回到任务，显式升级：

```json
{"task_id":"任务编号","action":"force_close","report_id":"同一有效报告编号","target_ref":"同一报告引用","target_kind":"browser_tab","force_kill":true}
```

`target_kind` 可省略（等于 `process`），也可为 `window` 或 `browser_tab`。窗口关闭最多观察 2.5 秒，未关闭则结束所属进程树；标签优先用系统原生无障碍控件精确关闭，报告只有已有连接身份时可使用该连接。标签身份缺失、原生控件不可用或动作无效时返回 `closed=false`、`actual_scope=none`、`escalation_available=true` 和影响范围提示，浏览器保持运行。AI 再次提醒用户后若仍未回到任务，才显式传 `force_kill=true` 直接结束所属浏览器进程树。单次精细调用由可终止的工作进程执行，上限 3 秒；不要求调试端口或借用确认。Windows 最小化时无法枚举 UIA 标签不得误报为“已关闭”。

结果保留 `closed`、`already_closed`，并提供 `target_kind`、`requested_target`、`actual_scope`、`attempts`。进程后备提供 `process_result` 及残留 `alive_pids`；部分退出与观察失败不能当作整棵进程树成功关闭。`actual_scope=none` 表示没有执行关闭，须同时看 `closed` 才能区分已消失与失败。最小化保留原行为及字段，使用原生最小化状态确认。

各场景在产品动作之后、清理之前执行 `entity.observe`，记录目标、兄弟窗口/标签及进程状态。进程存活误报、权限拒绝、PID 生命周期变化、部分进程树退出和阻塞工作进程的稳定故障注入属于契约层，不能计为自然产品故障或真实 VM 通过。

### 本机正式安装验证

本机专项与 VM 共用 `org.dsh.TestDesktop` 按需测试驱动；`--local` 继续只用于契约测试。测试入口负责启用和退出停用，停用后核对 D-Bus 名称释放。窗口以 GNOME 原生稳定 ID 关联，不再依赖 Tab Focus Demo 或 Codex WindowControl。生产关闭、最小化仍经 DSH 调用正式后台，测试接口只建立前置条件并独立观察。首次安装或驱动代码更新后，需要在测试前完成桌面重新登录。

本机 profile 使用真实 DSH `plugin add` 安装插件，只将模型端点指向固定服务，并显式选择该服务支持的 `chat-completions` 协议，避免新版 DSH 默认协议变化。测试清理仅结束本轮项目目录下创建的任务、已跟踪的提醒进程及独立浏览器 profile；不按“测试期间新出现”清理其他用户任务或提醒。


### 浏览器只读采集验收

第六阶段已移除自有采集扩展的安装步骤；系统无障碍是浏览器正文来源。`browser_skill` 只保留给显式测试该独立插件的场景。普通采集测试不加载它。

- `fixture.extension`：在指定浏览器实体的真实扩展管理页加载 `directory`，按 `name` 确认扩展出现。
- `fixture.browser_restart`：仅用于本轮独立浏览器profile；正常关闭后保留profile重启，不提供远程调试端口，返回真实启动参数是否含调试开关。
- `evidence.inspect` 新增 `browser_snapshots`、`browser_semantic_text`、`browser_semantic_status`，来自正式导出时间轴，失败不会替换为空模拟结果。

原始复现为 `browser-read-focus`；语义验收为 `browser-observer-semantics`；普通无调试端口配置为 `browser-observer-ordinary`；Wayland偏移窗口关联为 `browser-observer-offset`，其布局和语义预期全部在JSON中。焦点观察和内容断言分别保留，防止停止采集被误判成修复。

### 采样连续性与显示配置

- `sample.inspect`：`task_id`指定本轮任务，只读正式数据库，返回`count`、`intervals`、`max_interval`及原始分段耗时。不会填补缺帧或改写报告。
- `fixture.process`：`entity`指定本轮应用夹具，`action`为`suspend`或`resume`，实际暂停/恢复进程，返回进程状态。用于明确标注的故障注入；清理由夹具所有者负责。
- Linux场景元数据`desktop_size: [宽, 高]`：通过Mutter选择实际支持的Wayland显示模式，保存原配置并在结束恢复。仅测试显示配置；不是生产采集参数。
- 安装跨重启会话保留同一个真实浏览器profile；第一次通过扩展UI安装，恢复用例不重新安装。会话清理删除本轮profile。DSH任务与浏览器扩展是否恢复分别断言。

`state.read` 可传 `task_id`，仅过滤返回的 `tasks/live/reports/alerts`，用于本轮任务清理断言；不修改后台数据。省略时仍读取全局状态。

`report.wait.sampled_from_after` 按正式报告 `raw.real_start` 过滤，要求整段采样位于指定前置完成时刻之后；`sampled_after` 仍只要求 `raw.real_end` 越过该时刻。两者均不检查预期正文，不改报告。跨重启新建夹具验证使用前者，避免要求前置操作之前的样本包含未来页面。

`desktop.popup` 在两端统一按本轮提醒PID独立查询原生窗口并截图，不再启动额外完整采集器来证明弹窗存在；不会替代生产提醒动作。

`native.dialog`：`title`、`button`指定真实原生对话框与按钮；默认限定本轮DSH浏览器PID，`entity`可改为本轮夹具。`optional: true`允许确实不存在的浏览器提示，返回`present: false`；存在时真实点击并等待窗口关闭。用于浏览器自身的安装/启动确认，不修改产品权限或跳过实际系统提示。

Windows `native.dialog.menu_item` 可在点击按钮展开菜单后，按同进程真实UIA MenuItem名称点击选项，再确认原提示关闭。例如Edge的Not now需要选择Remind in 2 weeks；仅展开菜单不算确认完成。

`vm.observe_service.capture_error` 可指定等待的实际采集状态（例如null）；与原任务及sampled_after条件共同满足才结束。每次状态读取保存server_time/last_sample_at/capture_error，超时也保留，不能把新的失败尝试算采集恢复。

`model.messages` 读取固定模型实际收到的请求，支持 role、contains、latest，返回字符/UTF-8 字节计数。`model.paginate` 支持文本及 items_field 指定的列表分页。`native-browser-unfocused` 覆盖独立无扩展、无调试端口浏览器冷启动；`compact-model-input` 核对动态上下文、紧凑回执和活动分页。

### 第六阶段新增验证动作

- `data.select`：从 `rows` 中按 `where` 的精确字段值选择记录，返回列表；用于按真实窗口 ID 对照模型活动报告，不根据标题猜目标。
- `model.messages`：读取固定模型端点真实收到的消息；`latest` 默认只看最后请求，`role`/`contains`筛选，`selection: "last"`读取最后匹配消息。返回消息、字符及 UTF-8 字节数，不冒充模型 usage。
- `model.paginate`：通过真实 DSH 按工具的 `next_offset` 连续读取，记录全部页；同时支持文本页和 `changes` 列表。
- `session.command` 可用 `expected_text` 正则等待真实命令完成。例如 `/compact` 等待 `Compacted \\d+ history items`，不会把“没有可压缩历史”算作压缩成功。
- `native.accessibility_inventory`：观察原生窗口与系统无障碍身份。Linux 同时记录 GTK 标识、AT-SPI属性、屏幕/局部坐标及 MDI 序号；只观察，不修正产品状态。

`native-window-group` 按用户新增边界验证同进程歧义正文，包括隐藏成员；这不是通用隐藏窗口采集开关。`native-visibility-boundaries` 仍验证正常关联时后台标签、完全遮挡和最小化不出现新正文/窗口截图/日志。`native-document-close` 验证没有调试连接时，正式文档引用经真实 DSH 关闭所属窗口。


### 桌面空闲与 I/O 观察

- `service.observe`：不启动后台，观察真实服务、采集子进程、最后采样时间、状态文件修改时间及 GNOME `status` 计数，返回 `sample_changes`、`status_file_changes`、`bridge_delta`、`capture_changes`。Windows 的内容变化证据来自真实采样时间；Linux 另有合成器采集计数。
- `desktop.latency`：按 JSON 指定秒数测量真实 D-Bus 状态响应，返回错误数、最大值及 P95；逐次证据单独保存。它不是帧时间测量。
- `fault.desktop_io_delay`：仅 Linux 测试来宾，向 GNOME 主线程实际 `fsync` syscall 注入指定等待，跟踪记录并在结束时解除。明确属于系统调用故障注入，不冒充自然硬盘故障，也不在真机执行。
- `desktop-bridge-pixels`：除正文外，要求报告中的图片确实来自原生窗口表面，桌面裁剪后备不能填补这一断言。

本轮新增生命周期组合：`desktop-idle-lifecycle` 核对无任务、预约、确认完成等待及结束退出；`desktop-standby-lifecycle` 通过真实输入空闲触发离席，持续观察 60 秒后用真实输入恢复。`desktop-bridge-recovery-linux/windows` 沿用现有 `vm.desktop_session`、`vm.observe_service` 和跨重启 checkpoint 验证同一任务；恢复观察使用 `capture_error: null` 等待实际可用的新样本，而非收到任意一次失败样本就判定恢复。

- `fault.runtime_storage`：在 Linux VM 的插件私有截图目录挂载本轮拥有的小型 tmpfs 并填满；`restore` 或场景收尾卸载。不会填满整个用户 runtime，也不用于真机。
- `desktop.rpc`：直接记录生产桌面协议的结果／错误及临时文件数，仅用于故障观察；不替代 DSH 产品调用。
- `desktop.extension`：真实启停生产扩展并查询 D-Bus 接口，结束时恢复启用。
- `desktop.disconnect_capture`：真实子进程获取截图后异常退出，独立记录断连前后图片数。
- `fault.desktop_io_delay` 的 `target: service` 对正式 Linux 后台及其线程注入 fsync/fdatasync 延迟；`fault.io_restore` 解除本轮注入并返回实际 DELAYED 调用数。`desktop.latency` 同样可选择 `target: service` 测量只读状态响应。
- `desktop-bridge-faults` 在故障清除后仍须经真实 DSH 创建任务、读取新正文及原生窗口图片；任务进行中启停扩展和杀掉后台后，核对原任务与新采样恢复。
