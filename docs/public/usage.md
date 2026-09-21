# 使用详情

完整安装、任务设置、权限和数据说明见[README](../README.md)。

Linux 后台日志：`journalctl -u dafeiyu-supervisor.service`。后台无任务时退出是正常行为。Windows后台由安装器创建的计划任务管理。

升级：用新Release包运行同一条 `dsh plugin --profile web add <URL>` 命令更新插件，后台升级使用正式安装入口，保留任务数据库与自定义设置。源码Linux后台可运行 `sudo bash deploy/upgrade-chat.sh 用户名`；Windows使用 `deploy/install-windows.ps1`。GNOME是否需要重新登录，以实际加载提示为准。

任务保护默认关闭。开启后，预约或进行中任务会锁定UI设置和手动结束；任务需在监工会话中按约定处理。
