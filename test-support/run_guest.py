"""Run a test command with the logged-in guest's actual desktop environment."""
import os,subprocess,sys
if sys.platform=='linux':
    runtime='/run/user/'+str(os.getuid())
    os.environ.update(XDG_RUNTIME_DIR=runtime,DBUS_SESSION_BUS_ADDRESS='unix:path='+runtime+'/bus')
    result=subprocess.run(['systemctl','--user','show-environment'],capture_output=True,text=True)
    for row in result.stdout.splitlines():
        key,_,value=row.partition('=')
        if key in {'DISPLAY','WAYLAND_DISPLAY','XAUTHORITY','XDG_SESSION_TYPE','XDG_CURRENT_DESKTOP'}:os.environ[key]=value
os.environ['DSH_TEST_GUEST']='1'
raise SystemExit(subprocess.run([sys.executable,*sys.argv[1:]]).returncode)
