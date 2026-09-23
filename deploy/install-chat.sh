#!/bin/bash
set -euo pipefail
if [ "$(id -u)" != 0 ]; then echo '请使用 sudo bash deploy/install-chat.sh 用户名'; exit 1; fi
account=${1:?需要桌面用户名}
id "$account" >/dev/null
if command -v apt-get >/dev/null; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-gi python3-pyatspi python3-pil python3-xlib gir1.2-gtk-3.0 gir1.2-gsound-1.0 dbus-x11
fi
source_dir=$(cd "$(dirname "$0")/.." && pwd)
if systemctl is-active --quiet dafeiyu-supervisor.service; then
  echo '现有监工服务正在运行，请先在 DSH 结束测试任务，等待后台退出后再更新。'; exit 1
fi
install -d -m 755 /opt/dafeiyu /opt/dafeiyu/deploy /etc/dafeiyu
cp -r "$source_dir/focus_demo" /opt/dafeiyu/
cp "$source_dir/dsh-plugin/default-prompts.json" /opt/dafeiyu/focus_demo/default_prompts.json
cp "$source_dir/deploy/chat_service.py" "$source_dir/deploy/chat_sensor.py" "$source_dir/deploy/evidence_worker.py" "$source_dir/deploy/desktop_setup.py" "$source_dir/deploy/desktop_notify.py" "$source_dir/deploy/open_chat.py" "$source_dir/deploy/focus_window.py" /opt/dafeiyu/deploy/
cp -r "$source_dir/dsh-plugin/assets" /opt/dafeiyu/
/usr/bin/python3 -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('GSound','1.0')" || echo "桌面弹窗/声音依赖缺失：请安装 python3-gi、gir1.2-gtk-3.0、gir1.2-gsound-1.0（发行版包名可能不同）。"
cp -r "$source_dir/gnome-extension" /opt/dafeiyu/
cp "$source_dir/requirements.txt" /opt/dafeiyu/requirements.txt
cp "$source_dir/deploy/retire_legacy.py" /opt/dafeiyu/deploy/
/usr/bin/python3 -I /opt/dafeiyu/deploy/retire_legacy.py /opt/dafeiyu "$(getent passwd "$account" | cut -d: -f6)"
chown -R root:root /opt/dafeiyu
chmod -R go-w /opt/dafeiyu
if [ ! -x /opt/dafeiyu/venv/bin/python ]; then /usr/bin/python3 -m venv /opt/dafeiyu/venv; fi
/opt/dafeiyu/venv/bin/pip -q install -r /opt/dafeiyu/requirements.txt
/usr/bin/python3 - "$account" <<'PY'
import json,sys,pathlib
p=pathlib.Path('/etc/dafeiyu/config.json')
if not p.exists():
 p.write_text(json.dumps({'desktop_user':sys.argv[1],'data_dir':'/var/lib/dafeiyu','socket':'/run/dafeiyu/agent.sock','interval':600,'sample':2}))
 p.chmod(0o644)
PY
cat > /etc/systemd/system/dafeiyu-supervisor.service <<'UNIT'
[Unit]
Description=大肥鱼监工 — task-bound independent supervisor
After=network.target systemd-user-sessions.service
StartLimitIntervalSec=0
RefuseManualStop=yes
[Service]
Type=simple
ExecStart=/opt/dafeiyu/venv/bin/python -I /opt/dafeiyu/deploy/chat_service.py
WorkingDirectory=/opt/dafeiyu
RuntimeDirectory=dafeiyu
RuntimeDirectoryMode=0755
UMask=0077
Restart=always
RestartSec=2
RestartPreventExitStatus=42
SuccessExitStatus=42
TimeoutStopSec=40
[Install]
WantedBy=multi-user.target
UNIT
cat > /usr/local/sbin/dafeiyu-start <<'START'
#!/bin/sh
[ "$#" -eq 0 ] || exit 2
exec /usr/bin/systemctl start dafeiyu-supervisor.service
START
cat > /usr/local/sbin/dafeiyu-recover <<'RECOVER'
#!/bin/sh
# Explicit administrator recovery, independent of AI/model availability.
[ "$(id -u)" -eq 0 ] || { echo '需要管理员权限'; exit 1; }
[ "$#" -gt 0 ] || { echo '用法：sudo dafeiyu-recover 系统故障原因'; exit 1; }
/usr/bin/python3 - "$*" <<'PY'
import json,pathlib,sys
p=pathlib.Path('/var/lib/dafeiyu');p.mkdir(parents=True,exist_ok=True)
(p/'recovery.json').write_text(json.dumps({'reason':sys.argv[1]}))
PY
/usr/bin/systemctl start dafeiyu-supervisor.service
echo '已请求管理员恢复；后台将记录原因并结束监督，不会伪造任务完成。'
RECOVER
chmod 755 /usr/local/sbin/dafeiyu-start /usr/local/sbin/dafeiyu-recover
printf '%s ALL=(root) NOPASSWD: /usr/local/sbin/dafeiyu-start ""\n' "$account" > /etc/sudoers.d/dafeiyu-start
chmod 440 /etc/sudoers.d/dafeiyu-start
visudo -cf /etc/sudoers.d/dafeiyu-start
systemctl daemon-reload
if command -v gnome-shell >/dev/null && command -v gnome-extensions >/dev/null; then
  account_uid=$(id -u "$account")
  desktop_command=(runuser -u "$account" -- env XDG_RUNTIME_DIR="/run/user/$account_uid")
  if [ -S "/run/user/$account_uid/bus" ]; then
    desktop_command+=(DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$account_uid/bus")
  else
    desktop_command+=(dbus-run-session --)
  fi
  "${desktop_command[@]}" /usr/bin/python3 /opt/dafeiyu/deploy/desktop_setup.py install --source /opt/dafeiyu/gnome-extension
  "${desktop_command[@]}" /usr/bin/python3 /opt/dafeiyu/deploy/desktop_setup.py probe
else
  printf '本机没有 GNOME Shell：X11 使用原生采集，其他 Wayland 桌面当前不支持。\n'
fi
printf '后台已安装；桌面采集状态见上方。需要重新登录时，登录前截图尚不可用。\n'


browser_uid=$(id -u "$account")
