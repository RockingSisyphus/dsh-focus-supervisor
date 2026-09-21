# DeepSeek 娘监工形象

原图保留在项目 `pic/`。当前 PNG 使用内置 image_gen 的 background-extraction 编辑，包含真实 alpha 通道。

| 文件 | 原图编号 | 状态 |
|---|---|---|
| sleep.png | 1 | 无任务 |
| scheduled.png | 2 | 有预约未开始 |
| watching.png | 3 | 监督期间等待下次检查 |
| checking.png | 4 | 已有待处理/已投递的检查报告 |
| start.png | 5 | 任务开始提醒 |
| celebrate.png | 6 | 任务完成且结束 |
| warning.png | 7 | AI 确认 off_task |

统一编辑提示词：

> Use case: background-extraction. Edit this exact supplied image into a transparent PNG UI mascot. Remove only the near-white background and ground shadow, making true alpha transparency (not a checkerboard drawing). Preserve the character exactly, same face pose clothes props colors composition and all floating symbols, letters, sparkles. Keep opaque white inside costume, eyes, paper, props and outlined speech bubbles. No redesign, no added elements. Preserve fine hair contours. Save output as a transparent PNG.


新增提醒变体（2026-09-17）：`question.png`（疑问）、`gentle.png`（温和）、`urgent.png`（严肃）；普通警告使用 `warning.png`。三张以已认可的 warning.png 为参考，经内置 imagegen 编辑，均为真实透明 PNG。资源作为插件 assets 打包，后台安装时也复制一份，不引用生成工具临时输出。

编辑提示词：

> Edit supplied mascot image. [Variant instruction below] Preserve this exact blue-haired chibi DeepSeek maid character, whale details, pose and rendering style. Full character, all props inside square frame. Genuine transparent alpha background, no white backdrop or checkerboard. Keep white clothing opaque. Output PNG.

- question: Replace warning sign with a large blue question mark; curious and concerned, gentle expression; replace red anger marks with blue question marks.
- gentle: Use a small pale yellow exclamation sign, kind encouraging expression, relaxed eyebrows and gentle blue marks; not angry.
- urgent: Use a prominent orange-red exclamation warning sign and a serious determined concerned expression; urgent but cute, no weapons or violence.
