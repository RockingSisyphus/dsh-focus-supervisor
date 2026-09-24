"""Root-owned Linux supervisor; no model, public TCP port or arbitrary shell API."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import select
import signal
import socketserver
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from focus_demo.supervisor import Supervisor
from focus_demo.http_api import Handler

UNIT = 'dafeiyu-supervisor.service'


class Lifecycle:
    def __init__(self, account, enabled=True):
        self.account, self.enabled = account, enabled

    def enable(self):
        if self.enabled:
            subprocess.run(['systemctl', 'enable', UNIT], check=True, capture_output=True, timeout=10)

    def disable(self):
        if self.enabled:
            subprocess.run(['systemctl', 'disable', UNIT], check=True, capture_output=True, timeout=10)

    def wake_dsh(self):
        if self.enabled:
            subprocess.run(['runuser', '-u', self.account.pw_name, '--', 'env',
                            f'XDG_RUNTIME_DIR=/run/user/{self.account.pw_uid}',
                            f'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{self.account.pw_uid}/bus',
                            'systemctl', '--user', 'start', 'dsh-web.service'],
                           check=True, capture_output=True, timeout=15)


class Sensor:
    def __init__(self, account, directory):
        self.account, self.directory = account, directory
        self.process = None
        self.lock = threading.Lock()

    def stop(self):
        with self.lock:
            self._stop()

    def _stop(self):
        if self.process and self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process = None

    def call(self, operation, expected=None):
        call_started=time.monotonic()
        if operation in {'export','verify_export','cleanup_export'}:
            account=self.account
            result=subprocess.run([sys.executable,'-I',str(ROOT/'deploy/evidence_worker.py')],
                input=json.dumps({'operation':operation,'payload':expected}),text=True,capture_output=True,timeout=30,
                user=account.pw_uid,group=account.pw_gid,extra_groups=os.getgrouplist(account.pw_name,account.pw_gid))
            if result.returncode:raise RuntimeError(result.stderr.strip() or '证据文件操作失败')
            return json.loads(result.stdout)
        if operation == 'force_close':
            from focus_demo.close_actions import finish_process_fallback
            return finish_process_fallback(self.call('close_target',expected),lambda:self.call('observe_close_target',expected))
        with self.lock:
            if not self.process or self.process.poll() is not None:
                account = self.account
                env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': account.pw_dir,
                       'XDG_RUNTIME_DIR': f'/run/user/{account.pw_uid}',
                       'DBUS_SESSION_BUS_ADDRESS': f'unix:path=/run/user/{account.pw_uid}/bus'}
                self.process = subprocess.Popen([sys.executable, '-I', str(ROOT / 'deploy/chat_sensor.py')],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
                    user=account.pw_uid, group=account.pw_gid, extra_groups=os.getgrouplist(account.pw_name, account.pw_gid))
            try:
                self.process.stdin.write(json.dumps({'operation': operation, 'expected': expected}) + '\n')
                self.process.stdin.flush()
                if not select.select([self.process.stdout], [], [], 30)[0]:
                    raise TimeoutError('桌面采集超过30秒')
                line = self.process.stdout.readline(32_000_000)
                if not line.endswith('\n'):
                    raise ValueError('采集数据不完整或过大')
                response = json.loads(line)
                if 'error' in response:
                    raise ValueError(response['error'])
                result = response['result']
            except Exception:
                self._stop()
                raise
        # The pipe exchange is complete. Persistent screenshot writes must not
        # monopolize the desktop channel used for stop, presence and actions.
        if operation == 'capture':
            result['sample'].setdefault('capture_timings',{})['sensor_exchange']=time.monotonic()-call_started
            save_started=time.monotonic()
            self.save_images(result['images'])
            result['sample']['capture_timings']['save_images']=time.monotonic()-save_started
            return result['sample']
        return result

    def save_images(self, images):
        from PIL import Image
        folder = self.directory / 'screenshots'
        folder.mkdir(exist_ok=True)
        for claimed, encoded in images.items():
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != claimed:
                raise ValueError('无效的采集图片')
            with Image.open(io.BytesIO(raw)) as picture:
                if picture.format != 'PNG' or picture.width * picture.height > 12_000_000:
                    raise ValueError('无效的图片尺寸或格式')
                picture.verify()
            target = folder / (claimed + '.png')
            from focus_demo.common import screenshot_files
            with screenshot_files:
                if not target.exists():target.write_bytes(raw)



class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True




def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='/etc/dafeiyu/config.json')
    parser.add_argument('--test-mode', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    account = pwd.getpwnam(config['desktop_user'])
    directory = Path(config['data_dir'])
    directory.mkdir(parents=True, exist_ok=True)
    os.chown(directory, 0, account.pw_gid)
    os.chmod(directory, 0o750)
    lifecycle = Lifecycle(account, not args.test_mode)
    sensor = Sensor(account, directory)
    core = Supervisor(directory, lifecycle, sensor, interval=config.get('interval', 600),
                      sample=config.get('sample', 2), test_mode=args.test_mode or config.get('test_mode', False))
    core.execution={'platform':'linux','elevated':os.geteuid()==0,'force_close_executor':'root supervisor'}
    core.hold_reports = core.test_mode and config.get('preview', True)
    core.status_gid = account.pw_gid
    from focus_demo.status_writer import StatusWriter
    core.publisher=StatusWriter()
    core.publish_settings()
    address = Path(config['socket'])
    address.parent.mkdir(parents=True, exist_ok=True)
    address.unlink(missing_ok=True)
    server = Server(str(address), Handler)
    server.core = core
    os.chown(address, 0, account.pw_gid)
    address.chmod(0o660)
    stop = threading.Event()

    def refuse(signum, frame):
        # Manual service stops remain refused by systemd. A real OS shutdown
        # must finish normally rather than waiting for systemd's kill timeout.
        shutting_down = False
        if core.live():
            try:
                shutting_down = subprocess.run(['systemctl', 'is-system-running'], capture_output=True,
                                               text=True, timeout=2).stdout.strip() == 'stopping'
            except (OSError, subprocess.TimeoutExpired):
                pass
        if not core.live() or shutting_down:
            stop.set()
        else:
            core.store.log('stop_refused', {'signal': signum})
    signal.signal(signal.SIGTERM, refuse)
    signal.signal(signal.SIGINT, refuse)

    def sampler():
        next_sample=next_presence=0
        while not stop.is_set():
            now=time.monotonic()
            if now>=next_presence:
                core.poll_presence();next_presence=now+(5 if core.capture_state()=='away' else 2)
            if core.capture_state()!='collecting':
                core.capture()  # Suspend immediately, even with a long sampling interval.
                next_sample=0
            elif now>=next_sample:
                schedule_delay=max(0,now-next_sample) if next_sample else 0
                if schedule_delay>2:
                    print(json.dumps({'event':'sample_schedule_delay','seconds':round(schedule_delay,3)}),
                          file=sys.stderr,flush=True)
                core.capture()
                if core.settings()['debug_mode']:
                    print(json.dumps({'event':'capture_cycle','at':time.time(),
                                      'schedule_delay':round(schedule_delay,3),
                                      'timings':core.last_capture_timings},ensure_ascii=False),
                          file=sys.stderr,flush=True)
                if getattr(core,'last_capture_timings',{}).get('total',0)>max(5,core.sample*2):
                    print(json.dumps({'event':'slow_capture','timings':core.last_capture_timings},ensure_ascii=False),
                          file=sys.stderr,flush=True)
                next_sample=time.monotonic()+core.sample
            stop.wait(.25)
    capture_thread = threading.Thread(target=sampler, daemon=True)
    capture_thread.start()
    http_thread = threading.Thread(target=server.serve_forever, daemon=True)
    http_thread.start()
    wake_at = 0
    try:
        while not stop.wait(1):
            recovery = directory / 'recovery.json'
            if recovery.exists():
                core.recover(json.loads(recovery.read_text())['reason'])
                recovery.unlink()
            core.tick()
            with core.lock:
                if core.live():
                    if core.needs_dsh() and time.time() >= wake_at:
                        try:
                            lifecycle.wake_dsh()
                            core.notices_woken()
                        except Exception as error:
                            core.store.log('dsh_wake_failed', {'error': str(error)})
                        wake_at = time.time() + 15
                elif core.empty_since is not None and time.time() - core.empty_since >= 10:
                    core.shutting_down = True
                    lifecycle.disable()
                    stop.set()
                    break
        # Preserve autostart when the OS shuts down with a live agreement.
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        if sensor:
            sensor.stop()
        capture_thread.join(timeout=5)
        core.publisher.close()
        core.store.close()
        address.unlink(missing_ok=True)
    return 42


if __name__ == '__main__':
    raise SystemExit(main())
