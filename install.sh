#!/bin/bash
# 大肥鱼监工：新电脑一条命令安装。
#
#   bash install.sh              # 注册 DSH 插件 + 安装受保护后台服务（需要时自动 sudo）
#   bash install.sh --check      # 只检查环境并打印计划，不做任何修改
#   bash install.sh --skip-backend
#   bash install.sh --modules /实际DSH/node_modules --profile ~/.dsh/profiles/web
#
# 不要用 root 运行本脚本：插件要写进桌面用户的 DSH profile，脚本只在安装后台时请求 sudo。
set -euo pipefail

repo=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
check=0; skip_backend=0; force_autostart=0
modules_arg=''; profile_arg=''; user_arg=''
while [ $# -gt 0 ]; do
  case "$1" in
    --check) check=1 ;;
    --skip-backend) skip_backend=1 ;;
    --force-autostart) force_autostart=1 ;;
    --modules) modules_arg=${2:?--modules 需要一个目录}; shift ;;
    --profile) profile_arg=${2:?--profile 需要一个目录}; shift ;;
    --user) user_arg=${2:?--user 需要一个用户名}; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "未知参数：$1（用 --help 查看用法）"; exit 2 ;;
  esac
  shift
done

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  ✅ %s\n' "$*"; }
warn() { printf '  ⚠️  %s\n' "$*"; }
die()  { printf '\n❌ %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" != 0 ] || die '请用桌面用户运行本脚本（不要 sudo bash install.sh）；脚本会在安装后台时自己请求 sudo。'
case "$(uname -s)" in Linux) : ;; *) die '本安装器面向 Linux 桌面（Windows 请用 deploy/install-windows.ps1 并在 DSH profile 注册插件）。' ;; esac
command -v systemctl >/dev/null || die '本机没有 systemd，无法安装受保护后台服务。'
command -v python3  >/dev/null || die '未找到 python3。'
desktop_user=${user_arg:-$(id -un)}

say '1/4 检查环境'
ok "仓库：$repo"
ok "桌面用户：$desktop_user"
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then ok "图形会话：${WAYLAND_DISPLAY:+wayland }${DISPLAY:+x11 }"; else warn '当前 shell 没有 DISPLAY/WAYLAND_DISPLAY：若在 SSH 里安装，桌面采集要在图形登录会话中才能验证。'; fi

say '2/4 定位 DSH 依赖与 profile'
if [ -n "$modules_arg" ]; then
  modules=$(cd "$modules_arg" && pwd)
else
  candidates=()
  for dir in "$HOME"/.npm/_npx/*/node_modules "$HOME"/.dsh/profiles/*/node_modules /usr/lib/node_modules /usr/local/lib/node_modules; do
    [ -f "$dir/@deepseek-ai/dsh-tools/package.json" ] && candidates+=("$dir")
  done
  npm_root=$(npm root -g 2>/dev/null || true)
  [ -n "$npm_root" ] && [ -f "$npm_root/@deepseek-ai/dsh-tools/package.json" ] && candidates+=("$npm_root")
  [ "${#candidates[@]}" -gt 0 ] || die '没找到 DSH 依赖（@deepseek-ai/dsh-tools）。请先安装并至少启动过一次 DSH，或用 --modules 指定 DSH 的 node_modules。'
  modules=$(for dir in "${candidates[@]}"; do printf '%s %s\n' "$(stat -c %Y "$dir" 2>/dev/null || echo 0)" "$dir"; done | sort -rn | head -1 | cut -d' ' -f2-)
fi
ok "DSH 模块：$modules"
profile=${profile_arg:-$HOME/.dsh/profiles/web}
if [ -f "$profile/cordis.yml" ] || [ -f "$profile/cordis.patch.yml" ]; then ok "DSH profile：$profile"; else warn "DSH profile 目录尚不存在，安装器会创建：$profile"; fi
plugin_row=$(grep -c 'id: focus-supervisor-chat' "$profile/cordis.patch.yml" 2>/dev/null || true)
[ "$plugin_row" != 0 ] && ok '插件条目已存在（重复安装会跳过，不会重复添加）'

autostart_unit="$HOME/.config/systemd/user/dsh-web.service"
autostart=1
if [ -f "$autostart_unit" ] && [ "$force_autostart" != 1 ]; then
  autostart=0
  warn "已存在 $autostart_unit：保留现状不改写（它会覆盖成固定端口 18768）。需要重写加 --force-autostart。"
fi

if [ "$check" = 1 ]; then
  say '检查完成（--check：未做任何修改）'
  printf '  将要执行：\n    1) python3 scripts/install-dsh-plugin.py --modules %s --profile %s%s\n    2) sudo bash %s/node_modules/dsh-focus-supervisor/backend/deploy/install-chat.sh %s\n    3) 打印校验结果与后续步骤\n' \
    "$modules" "$profile" "$([ "$autostart" = 0 ] && echo ' --no-autostart')" "$profile" "$desktop_user"
  [ "$skip_backend" = 1 ] && printf '  （--skip-backend：跳过第 2 步）\n'
  exit 0
fi

say '3/4 注册 DSH 插件（桌面用户）'
install_args=(--modules "$modules" --profile "$profile")
[ "$autostart" = 0 ] && install_args+=(--no-autostart)
python3 "$repo/scripts/install-dsh-plugin.py" "${install_args[@]}"
[ "$autostart" = 1 ] && ok '已注册 DSH 自启动单元（监工后台需要时才能把 DSH 拉起来）'

say '4/4 安装受保护后台服务（需要 sudo）'
if [ "$skip_backend" = 1 ]; then
  warn '--skip-backend：跳过后台安装，只完成插件注册。'
elif systemctl is-active --quiet dafeiyu-supervisor.service; then
  warn '后台服务正在运行：跳过安装。升级请用 sudo bash deploy/upgrade-chat.sh "$USER"（它会保留任务数据库）。'
else
  sudo bash "$profile/node_modules/dsh-focus-supervisor/backend/deploy/install-chat.sh" "$desktop_user"
  ok '后台服务已安装'
fi

say '安装结果'
[ -f "$profile/node_modules/dsh-focus-supervisor/package.json" ] && ok "正式插件包：$profile/node_modules/dsh-focus-supervisor" || warn '未找到安装后的插件包'
if systemctl list-unit-files dafeiyu-supervisor.service >/dev/null 2>&1; then
  state=$(systemctl is-active dafeiyu-supervisor.service 2>/dev/null || true)
  ok "后台服务：$state（空闲时按设计自行退出，有任务时由插件唤醒）"
else
  warn '后台服务未安装（可能用了 --skip-backend）'
fi
if [ -x /opt/dafeiyu/deploy/desktop_setup.py ]; then
  python3 /opt/dafeiyu/deploy/desktop_setup.py status 2>/dev/null | head -c 400 || warn '桌面采集状态暂不可读（首次安装后可能需要注销重登）。'
fi

say '下一步'
cat <<'NEXT'
  1) 重启 DSH 宿主让新插件生效：systemctl --user restart dsh-web    （或在 DSH 界面里退出后重新打开）
  2) 刷新浏览器页面，右下角应出现大肥鱼悬浮球。
  3) 在聊天里和 AI 商量目标与起止时间后，它才会用 focus_plan 建任务；没达成约定前不会采集桌面。
  4) GNOME/Wayland 首次安装可能要求注销并重新登录一次（安装器会打印 login_required）。
NEXT
