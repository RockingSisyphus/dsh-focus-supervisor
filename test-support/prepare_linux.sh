#!/bin/bash
set -euo pipefail
root=$(pwd)
sudo cloud-init status --wait
sudo apt-get update -qq
sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-gi python3-pyatspi python3-tk python3-pil gir1.2-gtk-3.0 gir1.2-gsound-1.0 sound-theme-freedesktop
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt playwright PyYAML pytest
# Real product browser: system Chrome on the logged-in Wayland desktop.
if ! command -v google-chrome >/dev/null; then
 curl -fL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/dsh-test-chrome.deb
 sudo apt-get install -y /tmp/dsh-test-chrome.deb
 rm /tmp/dsh-test-chrome.deb
fi
version=$(python3 -c "import json;print(json.load(open('test-support/runtime.json'))['node'])")
if [ ! -x "$HOME/.local/node/bin/node" ]; then
 mkdir -p "$HOME/.local/node"
 curl -fL "https://nodejs.org/dist/v$version/node-v$version-linux-x64.tar.xz" | tar xJ --strip-components=1 -C "$HOME/.local/node"
fi
export PATH="$HOME/.local/node/bin:$PATH"
# Use the same configured VM network for upstream curl installers launched via
# polkit/runuser, whose environment does not inherit the desktop's proxy vars.
if [ -n "${HTTPS_PROXY:-${HTTP_PROXY:-}}" ] && [ ! -e "$HOME/.curlrc" ]; then
 (umask 077; printf 'proxy = "%s"\n' "${HTTPS_PROXY:-$HTTP_PROXY}" > "$HOME/.curlrc")
fi
mkdir -p "$HOME/dsh-runtime"
packages=$(python3 -c "import json;print(' '.join(k+'@'+v for k,v in json.load(open('test-support/runtime.json'))['npm'].items()))")
(cd "$HOME/dsh-runtime" && npm install --no-audit --no-fund $packages)
# 市场安装路径 dsh plugin add 是一个 pnpm 转发器，来宾里必须有 pnpm。
command -v pnpm >/dev/null || npm install -g --no-audit --no-fund pnpm
ln -sfn "$HOME/dsh-runtime/node_modules" "$root/dsh-plugin/node_modules"

# Test guest only: prevent an idle lock from hiding the desktop during unattended runs.
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
gsettings set org.gnome.desktop.session idle-delay 0
gsettings set org.gnome.desktop.screensaver lock-enabled false

# The desktop uses NetworkManager; cloud-image networkd must not wait for
# interfaces it no longer manages on every boot of this dedicated guest.
if systemctl is-active --quiet NetworkManager; then
 sudo systemctl disable --now systemd-networkd-wait-online.service
fi

# Independent test-side Shell driver. A changed extension needs a new login.
driver="$HOME/.local/share/gnome-shell/extensions/dsh-test-desktop@local"
changed=0
if ! diff -qr test-support/gnome-driver "$driver" >/dev/null 2>&1; then changed=1; fi
mkdir -p "$driver"
cp test-support/gnome-driver/* "$driver/"
/usr/bin/python3 - <<'PYCODE'
from gi.repository import Gio
settings=Gio.Settings.new('org.gnome.shell')
enabled=settings.get_strv('enabled-extensions')
if 'dsh-test-desktop@local' not in enabled:settings.set_strv('enabled-extensions',enabled+['dsh-test-desktop@local'])
settings.set_boolean('disable-user-extensions',False)
Gio.Settings.sync()
PYCODE
if [ "$changed" = 1 ]; then
 sudo systemctl restart gdm3
fi

# Wait for the new user's compositor, not just the SSH daemon.
for attempt in $(seq 1 60); do
 if gdbus call --session --dest org.dsh.TestDesktop --object-path /org/dsh/TestDesktop --method org.dsh.TestDesktop.Call '{"op":"snapshot"}' >/dev/null 2>&1; then exit 0; fi
 sleep 1
done
loginctl show-user tester -p Display -p State >&2
session=$(loginctl show-user tester -p Display --value)
[ -z "$session" ] || loginctl show-session "$session" -p Type -p State -p Active >&2
gnome-extensions info dsh-test-desktop@local >&2 || true
echo 'GNOME test driver did not become ready after login' >&2
exit 1
