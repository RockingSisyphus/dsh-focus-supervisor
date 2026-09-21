# 本轮实际验证

2026-09-17，当前本机安装的 DSH 0.1.5-rc.1，Linux 私有 X11 桌面。

- 独立真实 DSH 中 15 项端到端检查通过，30 次本地固定模型请求。
- 浏览器 pageerror：0；监工后台循环异常：0。
- 心跳片段真实采集 6.491 秒，模拟覆盖后 600.0 秒；原始数据保持不变。
- 导出包含 3 张图片，程序分支映射非空；模型收到实际上传文件对应的图片引用。
- 实际模型请求：model=test-model，thinking={'type': 'enabled'}，reasoning_effort=high。
- 从真实 API 拒绝中确认预约冲突与提示词修改权限；从下一轮模型请求确认实际工具结果。
- 模型通过 DSH 原生 read 读取材料，统一 focus_act 关闭真实专用窗口并显示真实问号提醒。
- 完成后证据目录、后台报告和任务附加提示词清理，设置界面解锁。

本轮记录：`artifacts/dsh-harness-acceptance/result.json`、`checks.json`、`heartbeat-material.json` 和 `model/`。真实 DSH 页面截图见同目录。运行输出不提交 Git。

此外，45 项相关 Python 测试及 6 项插件测试通过。

这些结果覆盖软件调用链和材料传输。固定回复不评估真实模型的判断质量；私有 X11 场景不替代 GNOME Wayland 采集、root/systemd 防强杀、开机恢复的独立测试。本次未修改系统服务部署。
