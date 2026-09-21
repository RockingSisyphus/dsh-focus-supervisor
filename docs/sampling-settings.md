# 采集与模型输出设置

打开插件“设置 · 采集与提示词”，展开“采集设置”或“模型输出”，修改后保存。每项显示用途、单位和默认值。“恢复本组默认值”只修改该组草稿，再保存生效，不重置自定义提示词。

仅当防任务中修改模式开启时，有任务或预约会锁定设置界面；该模式默认关闭。通过任务会话调用 `focus_settings` 可修改采集参数，原任务继续运行。例如：

```json
{"operation":"update","patch_json":"{\"sampling\":{\"interval_seconds\":6,\"browser_pages\":2},\"reporting\":{\"text_page_chars\":2000}}"}
```

未提交字段保持不变。正数时间允许小数；像素、字符、节点、字节及页数使用正整数。界面中的“不限”保存为 null，仅适用于浏览器每轮页数和心跳活动目录长度。

字段、用途、默认值以 `focus_demo/sampling-settings.json` 为唯一设置定义。原有默认行为保留，包括单窗口1600×1200和整屏2560×1600的区别，以及Linux1600节点、Windows500节点的区别。GNOME原生截图周期仅影响Linux合成器截图，不降低桌面动作响应频率。

参数在下一轮采集应用，不重建任务，重启后继续使用。周期并非严格限流，窗口变化可能提前刷新。浏览器页数限制针对可见窗口的选中页，优先焦点页，其余名额轮换；限1页且焦点页可用时，只读取焦点页。页面身份记录不受正文页数限制。

低频可能遗漏短时活动。采集时间、不可用、历史及截断标记继续保留；后台标签或隐藏窗口不会因为有缓存而算作当前使用。状态显示最近一次采集实际使用的参数；导出报告的 `settings_timeline` 记录各次参数变化。

“模型输出”只控制插件活动文字预览、心跳程序活动目录和正文详情每页长度。不限制模型工具调用次数、DSH通用文件读取或整个会话token，也不删除本地证据。分页结果的 `next_offset` 为下一页入口，null表示结束。

测试仍走 `dshmonitor-test-pack/run.py`：`sampling-settings-ui`、`sampling-settings-live`、`sampling-settings-pagination`、`sampling-settings-browser`、`sampling-settings-reboot`、`sampling-settings-low-frequency`；契约层为 `sampling-settings-contracts`。测试层新增 `model.paginate` 沿真实DSH工具游标读取所有页面；`sample.inspect` 观察原始样本和实际尺寸/时间/长度，不替代产品采集。

日志长度沿用原采集口径：文件尾部按字节读取，Linux journal 的格式化摘录按字符截断，二者共用 log_bytes 预算值。

`backend.pause` 为测试侧故障注入，暂停真正的服务进程后恢复，再独立观察断档；`backend.restart` 单独验证服务重启。两者不修改产品返回或生产保护设置。
