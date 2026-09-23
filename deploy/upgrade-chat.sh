#!/bin/bash
# Upgrade program files without replacing the task database or stopping agreements.
set -euo pipefail
if [ "$(id -u)" != 0 ]; then echo '请使用 sudo bash deploy/upgrade-chat.sh 用户名'; exit 1; fi
account=${1:-${SUDO_USER:?需要桌面用户名}}
id "$account" >/dev/null
source_dir=$(cd "$(dirname "$0")/.." && pwd)
test -x /opt/dafeiyu/venv/bin/python || { echo '尚未安装后台，请先运行 install-chat.sh'; exit 1; }
stamp=$(date +%Y%m%d-%H%M%S)
backup="/opt/dafeiyu-backups/$stamp"
install -d -m 700 "$backup"
tar -C /opt/dafeiyu -czf "$backup/program.tar.gz" focus_demo deploy requirements.txt assets gnome-extension
cp /etc/dafeiyu/config.json "$backup/config.json"
# No evidence/database backup: retain the existing database in place, so task
# cleanup does not leave an extra copy of collected information behind.
cp -r "$source_dir/focus_demo" /opt/dafeiyu/
cp "$source_dir/dsh-plugin/default-prompts.json" /opt/dafeiyu/focus_demo/default_prompts.json
cp "$source_dir/requirements.txt" /opt/dafeiyu/requirements.txt
/opt/dafeiyu/venv/bin/pip -q install -r /opt/dafeiyu/requirements.txt
cp -r "$source_dir/gnome-extension" /opt/dafeiyu/
cp "$source_dir"/deploy/{chat_service,chat_sensor,evidence_worker,desktop_setup,desktop_notify,open_chat,focus_window}.py /opt/dafeiyu/deploy/
cp -r "$source_dir/dsh-plugin/assets" /opt/dafeiyu/
cp "$source_dir/deploy/retire_legacy.py" /opt/dafeiyu/deploy/
/usr/bin/python3 -I /opt/dafeiyu/deploy/retire_legacy.py /opt/dafeiyu "$(getent passwd "$account" | cut -d: -f6)"
chown -R root:root /opt/dafeiyu/focus_demo /opt/dafeiyu/deploy /opt/dafeiyu/assets /opt/dafeiyu/gnome-extension
chmod -R go-w /opt/dafeiyu/focus_demo /opt/dafeiyu/deploy /opt/dafeiyu/assets /opt/dafeiyu/gnome-extension
/opt/dafeiyu/venv/bin/python -m compileall -q /opt/dafeiyu/focus_demo /opt/dafeiyu/deploy
old_pid=$(systemctl show dafeiyu-supervisor.service -p MainPID --value)
if systemctl is-active --quiet dafeiyu-supervisor.service; then
  systemctl kill --kill-whom=main --signal=KILL dafeiyu-supervisor.service
else
  systemctl start dafeiyu-supervisor.service
fi
/usr/bin/python3 - "$account" "$old_pid" <<'PY'
import http.client,json,pathlib,pwd,socket,subprocess,sys,time
account=pwd.getpwnam(sys.argv[1]);old_pid=int(sys.argv[2] or 0)
class Local(http.client.HTTPConnection):
 def connect(self):
  self.sock=socket.socket(socket.AF_UNIX);self.sock.settimeout(40);self.sock.connect('/run/dafeiyu/agent.sock')
def call(route,body={}):
 c=Local('localhost');c.request('POST',route,json.dumps(body),{'Content-Type':'application/json'})
 r=c.getresponse();data=json.loads(r.read());c.close()
 if r.status!=200:raise RuntimeError(data)
 return data
for attempt in range(40):
 try:
  pid=int(subprocess.check_output(['systemctl','show','dafeiyu-supervisor.service','-p','MainPID','--value']))
  state=call('/state')
  if pid and pid!=old_pid and 'settings' in state:break
 except (OSError,ValueError,http.client.HTTPException):pass
 time.sleep(.5)
else:raise RuntimeError('新后台未就绪，请检查 journalctl -u dafeiyu-supervisor.service')
# Obtain legacy session cwd as the desktop user. Do not guess a project directory.
read_header=r'''
import json,pathlib,subprocess,sys
session=sys.argv[1]
if '/' in session or not session.startswith('session-'):raise ValueError('invalid session')
for p in (pathlib.Path.home()/'.dsh/sessions').glob('*/'+session+'/session.v3.jsonl.zstd'):
 child=subprocess.Popen(['zstd','-dc',str(p)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 try: header=json.loads(child.stdout.readline())
 finally: child.stdout.close();child.terminate();child.wait()
 cwd=header.get('cwd')
 if cwd and pathlib.Path(cwd).is_absolute() and pathlib.Path(cwd).is_dir():print(cwd);break
'''
for task in state['live']:
 if task.get('project_dir') and task.get('task_prompt'):continue
 try:
  cwd=task.get('project_dir') or subprocess.check_output(['runuser','-u',account.pw_name,'--','/usr/bin/python3','-c',read_header,task['session_id']],text=True,timeout=10).strip()
  if not cwd:raise ValueError('找不到原会话项目目录')
  call('/revise',{**task,'task_id':task['id'],'project_dir':cwd,
   'task_prompt':task.get('task_prompt') or '按照本任务已经商定的任务内容与完成标准监督，具体以任务约定为准。',
   'reason':'插件升级：补充原会话证据目录和沿用既有约定的心跳提示词。'})
  print('已保留并迁移任务：',task['id'],cwd)
 except Exception as e:print('任务仍保留，请让原监工会话使用 focus_revise 补充目录与 task_prompt：',task['id'],str(e))
print('新后台已运行；现有任务数量：',len(call('/state')['live']))
PY
# Frontend updates use the public package registration path. Do not write a
# source-checkout entry back into an installed DSH profile.
printf '后台已更新；DSH 插件请通过 dsh plugin add <安装包> 更新，保留现有会话及配置。\n'
/usr/bin/python3 -c "import gi; gi.require_version('Gtk','3.0'); gi.require_version('GSound','1.0')" || echo '请安装桌面提醒依赖：python3-gi、gir1.2-gtk-3.0、gir1.2-gsound-1.0（发行版名称可能不同）。'
printf '升级完成。程序备份：%s；原任务数据库未替换。\n' "$backup"

browser_uid=$(id -u "$account")

if command -v gnome-shell >/dev/null && command -v gnome-extensions >/dev/null; then
  runuser -u "$account" -- env XDG_RUNTIME_DIR="/run/user/$browser_uid" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$browser_uid/bus" /usr/bin/python3 /opt/dafeiyu/deploy/desktop_setup.py install --source /opt/dafeiyu/gnome-extension
  printf 'GNOME 采集扩展已更新；已登录的会话可能需要注销并重新登录才能加载新版遮挡检测。\n'
fi
