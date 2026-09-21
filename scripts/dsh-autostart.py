"""Register the existing DSH host for supervisor-requested restart; no model keys."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--modules',type=Path,required=True);p.add_argument('--home',type=Path,required=True);p.add_argument('--node',default=shutil.which('node'));p.add_argument('--task-name',default='Dafeiyu-DSH');a=p.parse_args()
cli=a.modules.resolve()/'@deepseek-ai/dsh/lib/bin.js';home=a.home.resolve()
if not a.node:raise SystemExit('Node executable was not found')
command=[str(Path(a.node).resolve()),str(cli),'--profile','web','--host','127.0.0.1','--port','18768','--no-open']
if os.name=='nt':
    # A fixed launcher makes DSH_HOME explicit for Task Scheduler's environment.
    launcher=home/'start-dsh.ps1';home.mkdir(parents=True,exist_ok=True)
    quote=lambda s:"'"+str(s).replace("'","''")+"'"
    launcher.write_text('$env:DSH_HOME='+quote(home)+'\n& '+ ' '.join(quote(v) for v in command)+'\n',encoding='utf-8')
    script="$p=New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Highest; $a=New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "+quote('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+str(launcher)+'"')+"; $s=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries; Register-ScheduledTask -TaskName "+quote(a.task_name)+" -Action $a -Principal $p -Settings $s -Force | Out-Null"
    # No console window: this runs on the user's desktop and must not flash or steal focus.
    subprocess.run(['powershell','-NoProfile','-Command',"$ErrorActionPreference='Stop';"+script],check=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
else:
    folder=Path.home()/'.config/systemd/user';folder.mkdir(parents=True,exist_ok=True)
    quote=lambda s:'"'+str(s).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    (folder/'dsh-web.service').write_text('[Unit]\nDescription=DSH host restored by Dafeiyu supervisor\n[Service]\nType=simple\nEnvironment='+quote('DSH_HOME='+str(home))+'\nExecStart='+' '.join(map(quote,command))+'\nRestart=no\n')
    env={**os.environ,'XDG_RUNTIME_DIR':'/run/user/'+str(os.getuid()),'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/'+str(os.getuid())+'/bus'}
    subprocess.run(['systemctl','--user','daemon-reload'],env=env,check=True)
print('DSH restart entry registered; the supervisor starts it only while agreements exist.')
