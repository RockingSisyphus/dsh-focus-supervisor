"""Unprivileged desktop worker; speaks only capture/close over parent-owned pipes."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import select
import shutil
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from focus_demo.collectors import Collector

directory = Path.home() / '.cache/dafeiyu-sensor'
directory.mkdir(parents=True, exist_ok=True)
collector = None
signature = None
for line in sys.stdin:
    try:
        request = json.loads(line)
        env = subprocess.run(['systemctl', '--user', 'show-environment'], capture_output=True, text=True, timeout=4)
        for row in env.stdout.splitlines():
            key, _, value = row.partition('=')
            if key in {'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE', 'XDG_CURRENT_DESKTOP', 'XDG_CACHE_HOME', 'XDG_DATA_HOME'}:
                os.environ[key] = value
        if request['operation']=='presence':
            from focus_demo.presence import read_presence
            print(json.dumps({'result':read_presence()}),flush=True)
            continue
        if request['operation'] in {'notify','export','verify_export','cleanup_export','cleanup_capture'}:
            payload=request.get('expected') or {}
            if request['operation']=='notify':
                log=(directory/'notifications.log').open('a')
                child=subprocess.Popen(['/usr/bin/python3','-I',str(Path(__file__).with_name('desktop_notify.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=log,text=True,start_new_session=True)
                child.stdin.write(json.dumps(payload)+'\n');child.stdin.close();log.close()
                if not select.select([child.stdout],[],[],12)[0]:
                    child.terminate();raise TimeoutError('桌面提醒启动超时')
                result=json.loads(child.stdout.readline())
                child.stdout.close()
            elif request['operation']=='cleanup_capture':
                if collector:collector.suspend()
                for root in [directory/'screenshots',Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'focus-demo']:
                    for image in root.glob('*.png'):image.unlink(missing_ok=True)
                result={'removed':True}
            else:
                from focus_demo.evidence_export import user_export,user_verify,user_cleanup
                result={'export':user_export,'verify_export':user_verify,'cleanup_export':user_cleanup}[request['operation']](payload)
            print(json.dumps({'result':result},ensure_ascii=False),flush=True)
            continue
        current = tuple(os.environ.get(k) for k in ('DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'XDG_SESSION_TYPE'))
        if collector is None or current != signature:
            if collector: collector.suspend()
            config = SimpleNamespace(data_dir=str(directory), screenshots=True, ui_text=True,
                                     detail_interval=10, log_root=[], system_logs=True)
            collector = Collector('auto', 49998, 49999, config)
            signature = current
        if request['operation'] == 'capture':
            collector.configure((request.get('expected') or {}).get('sampling',{}))
            sample = collector.capture()
            images = {}
            shots = [sample['desktop'].get('desktop_screenshot')] + [w.get('screenshot') for w in sample['desktop'].get('windows', [])]
            for shot in shots:
                if shot and shot.get('path'):
                    source = (directory / shot['path']).resolve()
                    if source.is_relative_to(directory.resolve()) and source.stat().st_size <= 2_000_000:
                        images[shot['sha256']] = base64.b64encode(source.read_bytes()).decode('ascii')
            result = {'sample': sample, 'images': images}
        elif request['operation'] == 'close_target':
            from focus_demo.close_actions import force_close
            payload=request['expected']
            result=force_close(collector,payload['expected'],payload.get('target_kind','process'),defer_kill=True)
        elif request['operation'] == 'observe_close_target':
            from focus_demo.close_actions import observe_target
            payload=request['expected']
            result=observe_target(collector,payload['expected'],payload.get('target_kind','process'))
        elif request['operation'] == 'minimize':
            result = collector.minimize_window_verified(request['expected'])
        else:
            raise ValueError('Unknown sensor operation')
        print(json.dumps({'result': result}, ensure_ascii=False), flush=True)
    except Exception as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False), flush=True)

if collector:
    collector.suspend()
