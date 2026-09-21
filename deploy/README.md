# 正式部署入口

Linux：install-chat.sh首次安装，upgrade-chat.sh保留数据升级；Windows：install-windows.ps1。服务入口为chat_service.py、chat_sensor.py、windows_service.py。其余文件为桌面helper或退役文件迁移。

完整步骤见[安装与使用](../docs/usage.md)。旧focus-demo双服务、维护审批脚本已移到[归档](../docs/archive/demo-v0.4/deploy/README.md)，不属于当前产品。测试准备脚本位于test-support。
