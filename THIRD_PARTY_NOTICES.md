# 参考来源与第三方组件

本项目原创代码按 AGPL-3.0-only 发布。第三方项目保留各自许可；“参考”不表示将其所有代码纳入本项目，也不表示对方认可或维护本插件。

## 实际研究和接入过的项目

| 项目 | 实际用途 | 当前关系 |
| --- | --- | --- |
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)（MIT） | DSH 工具、会话动态上下文、页面 UI、插件 bundle 与安装 API | 当前宿主及 peer dependencies |
| [Tencent BrowserSkill](https://github.com/Tencent/BrowserSkill)（MIT） | 早期浏览器正文采集和标签连接；研究其输出与普通浏览器的差异 | 已移除正文采集依赖；可用的既有精确连接仅用于关闭/唤回，不要求安装它 |
| [Chrome DevTools MCP](https://github.com/ChromeDevTools/chrome-devtools-mcp)（Apache-2.0） | 对比 SnapshotFormatter 与 Puppeteer 无障碍输出 | 研究参考，无运行时依赖 |
| [Puppeteer](https://github.com/puppeteer/puppeteer)（Apache-2.0） | 研究 AXNode 的 interesting/leaf 过滤规则；比较角色过滤对表格的影响 | 研究使用 puppeteer-core 25.10.0，未引入整个运行时 |
| [Playwright](https://github.com/microsoft/playwright) / [Playwright MCP](https://github.com/microsoft/playwright-mcp)（Apache-2.0） | 对比普通及 AI ARIA 快照、结构保留与去重；真实页面测试 | Playwright 用于测试，生产正文由系统无障碍读取 |
| [Cua](https://github.com/trycua/cua)（所研究 Driver Rust workspace 声明 MIT） | 研究原生应用的树表示和内容整理边界 | 研究参考，未安装 Cua 原生驱动作为生产依赖 |

研究源码版本：Chrome DevTools MCP `dc1d055e162a22dc3c63f902fa6a103f8029e28b`；Playwright MCP `f1257a5a67aff872f947fae274759f7d54853862`；Playwright `07f1a6154795f055f341b8972086533e8e48b36f`；Cua `9bbfa7dd3e27ca7f1861ede70aaca390174493f9`。

生产整理层 `focus_demo/ui_structure.py` 是针对 AT-SPI/UIA 节点的本项目实现，借鉴了空容器提升、父子重复文字合并和角色/状态保留的思路；没有将上述仓库整套整理器复制进产品。没有把参考项目的许可替换为 AGPL。

## 运行与测试依赖

Python 依赖见 requirements.txt：psutil（BSD）、Pillow（HPND）、Windows pywinauto（BSD）与 pywin32（PSF）。Linux 使用系统提供的 PyGObject、AT-SPI、GTK、GSound 和 GNOME Shell；这些组件按各自许可安装。macOS 的条件依赖并不代表本插件已验收支持 macOS。

测试使用 Playwright、pytest、QEMU、vncdotool、Pillow、PyYAML 等；依赖安装而非将上游源码副本放进生产包。具体版本约束见 requirements-test.txt。分发这些依赖的副本时，仍需遵守其各自许可和通知要求。

DSH 市场发布流程参考 [dsh-market](https://github.com/dsh-market/dsh-market) 和 [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin) 的公开文档，未将市场实现复制进插件。
