#!/usr/bin/env bash
set -euo pipefail
SOURCE=$(cd "$(dirname "$0")" && pwd)
if [ "$(id -u)" = 0 ]; then
  echo '请以桌面用户运行此脚本；系统后台安装器会自动切换到指定用户。'; exit 1
fi
python3 "$SOURCE/deploy/desktop_setup.py" install --source "$SOURCE/gnome-extension"
python3 "$SOURCE/deploy/desktop_setup.py" probe
