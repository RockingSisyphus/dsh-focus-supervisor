"""Install the desktop bridge and report live capabilities, independently of tasks."""
import argparse
import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

UUID = 'focus-demo@local.demo'
# 期望 Shell 里实际运行的扩展代码版本；与 gnome-extension/extension.js 的 CODE_VERSION、
# deploy/focus_window.py 的 EXTENSION_CODE_VERSION 必须一致（tests 里有契约测试盯着）。
EXPECTED_EXTENSION_CODE_VERSION = 'dafeiyu-13'

def command(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=8,
                          env={**os.environ, 'LC_ALL':'C'})

def setting(key):
    result=command(['gsettings','get','org.gnome.shell',key])
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    text=result.stdout.strip()
    return [] if text=='@as []' else ast.literal_eval(text)

def running_extension_version():
    """通过会话 D-Bus 查询实际加载的扩展版本；不可用时返回 None。"""
    from .desktop_bridge import call
    try:return call('status').get('code_version')
    except (OSError,ValueError,RuntimeError):return None

def install(source):
    accessibility=command(['gsettings','set','org.gnome.desktop.interface','toolkit-accessibility','true'])
    if accessibility.returncode:raise RuntimeError('系统无障碍配置失败：'+accessibility.stderr.strip())
    target=Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share'))) / 'gnome-shell/extensions' / UUID
    target.mkdir(parents=True,exist_ok=True)
    changed=[]
    for name in ('metadata.json','visibility.js','extension.js'):
        source_file=Path(source)/name
        target_file=target/name
        try:
            # 内容没变就不覆盖：GNOME 的文件监视会因此把扩展停掉重载，运行中这么做会让它变 INACTIVE。
            if target_file.exists() and target_file.read_bytes()==source_file.read_bytes():
                continue
        except OSError:
            pass
        temporary=target/(name+'.installing')
        shutil.copyfile(source_file,temporary)
        temporary.replace(target_file)
        changed.append(name)
    enabled=setting('enabled-extensions')
    if UUID not in enabled:
        result=command(['gsettings','set','org.gnome.shell','enabled-extensions',repr(enabled+[UUID])])
        if result.returncode: raise RuntimeError(result.stderr.strip())
    disabled=setting('disabled-extensions')
    if UUID in disabled:
        result=command(['gsettings','set','org.gnome.shell','disabled-extensions',repr([s for s in disabled if s!=UUID])])
        if result.returncode: raise RuntimeError(result.stderr.strip())
    # First-time local installs may be undiscovered until login; keep this distinct
    # from enable failures and leave GNOME's global extension policy untouched.
    command(['gnome-extensions','enable',UUID])
    # 尝试让运行中的 Shell 立刻加载新代码。GNOME 50.1 实测只在接口里声明了 ReloadExtension、
    # 调用会报 not implemented，所以失败不算安装失败，而是如实告诉用户需要注销重登一次。
    reload_result=command(['gdbus','call','--session','--dest','org.gnome.Shell.Extensions',
        '--object-path','/org/gnome/Shell/Extensions','--method',
        'org.gnome.Shell.Extensions.ReloadExtension',UUID])
    reloaded=reload_result.returncode==0
    running=running_extension_version()
    result=status()
    result.update({'files_changed':changed,'reload_attempted':True,'reloaded':reloaded,
        'expected_code_version':EXPECTED_EXTENSION_CODE_VERSION,'running_code_version':running,
        'version_matches':running==EXPECTED_EXTENSION_CODE_VERSION})
    if not changed and running==EXPECTED_EXTENSION_CODE_VERSION:
        result['message']='扩展文件未变化，Shell 里跑的已经是这一版（%s）。' % running
    elif running==EXPECTED_EXTENSION_CODE_VERSION:
        result['message']='扩展已更新，Shell 里已加载这一版（%s）。' % running
    else:
        result['message']=('扩展文件已安装；Shell 里' + ('还是旧版 %s' % running if running else '尚未加载它')
            + '，需要注销并重新登录一次才会生效（GNOME 50.1 上 ReloadExtension 未实现，'
            + 'Shell 也不会为全新扩展重新扫描）。在此之前新桌面接口不可用，不回退到旧文件通信。')
    return result

def status():
    session=os.environ.get('XDG_SESSION_TYPE','')
    desktop=os.environ.get('XDG_CURRENT_DESKTOP','')
    result={'session':session,'desktop':desktop,'screenshot_verified':False}
    if session=='x11':
        return dict(result,code='x11',message='X11 使用原生采集；截图能力以实际采集结果为准。')
    if session!='wayland' and not os.environ.get('WAYLAND_DISPLAY'):
        return dict(result,code='no_desktop_session',message='尚未连接图形会话；登录桌面后自动采集。')
    if desktop and 'gnome' not in desktop.lower() and 'ubuntu' not in desktop.lower():
        return dict(result,code='unsupported_wayland',message=f'当前 Wayland 桌面 {desktop} 尚未提供采集适配；此版本支持 GNOME Wayland 和 X11。')
    target=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share'))) / 'gnome-shell/extensions' / UUID
    result['installed']=(target/'extension.js').exists()
    if not result['installed']:
        return dict(result,code='not_installed',message='GNOME 采集扩展未安装。请运行插件的 install_gnome_extension.sh，或重新运行后台安装程序。')
    from .desktop_bridge import call
    try:
        running=call('status')
        return dict(result,code='bridge_running',bridge=running,message='桌面接口已就绪；只有执行任务或显式测试时才采集。')
    except (OSError,ValueError,RuntimeError) as error:
        result['bridge_error']=str(error)
    if not shutil.which('gnome-extensions'):
        return dict(result,code='missing_gnome_tools',message='缺少 gnome-extensions；请安装当前系统的 GNOME Shell 扩展管理组件。')
    info=command(['gnome-extensions','info',UUID])
    if info.returncode:
        return dict(result,code='login_required',message='采集扩展已安装并配置；当前 GNOME 尚未识别它。请保存工作后注销并重新登录，届时会自动启用。')
    state=next((s.split(':',1)[1].strip() for s in info.stdout.splitlines() if s.strip().startswith('State:')),'UNKNOWN')
    result['extension_state']=state
    if state=='UNKNOWN':
        return dict(result,code='status_unavailable',message='当前桌面接口不可用，扩展管理命令也未返回可识别状态。')
    if state!='ACTIVE':
        return dict(result,code='extension_inactive',message=f'GNOME 采集扩展状态为 {state}。请在扩展管理器启用“大肥鱼桌面采集”；若报错，查看扩展错误记录。')
    return dict(result,code='bridge_unavailable',message='扩展管理器显示已加载，但当前版本的桌面接口不可用；更新后请重新登录，不回退到旧文件通信。')

def probe():
    from .desktop_bridge import call,runtime_directory
    initial=status()
    if initial['code']!='bridge_running':return initial
    try:
        data=call('capture',timeout=10000)
        shot=data.get('screen_capture') or {}
        if not shot or not (runtime_directory()/shot['file']).is_file():raise RuntimeError('本次截图未产生图片')
        return dict(initial,code='ready',screenshot_verified=True,message='本次桌面截图验证成功，采集已结束。')
    except (OSError,ValueError,RuntimeError) as error:
        return dict(initial,code='screenshot_unavailable',message=str(error))
    finally:
        try:call('release')
        except (OSError,ValueError,RuntimeError):pass

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('operation',choices=['status','install','probe'])
    parser.add_argument('--source')
    args=parser.parse_args()
    try:
        value=install(args.source) if args.operation=='install' else probe() if args.operation=='probe' else status()
        print(json.dumps(value,ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'code':'setup_error','message':str(error),'screenshot_verified':False},ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    # 这个模块对外就是一个 CLI（status / install / probe）：没有这段，`python3 -m
    # focus_demo.desktop_setup install` 会静默地什么都不做还返回 0（在来宾里踩过）。
    sys.exit(main())
