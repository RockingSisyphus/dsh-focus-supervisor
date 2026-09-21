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
                if operation == 'capture':
                    self.save_images(result['images'])
                    return result['sample']
                return result
            except Exception:
                self._stop()
                raise

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
            if not target.exists():
                target.write_bytes(raw)


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
    core.publish_settings()
    address = Path(config['socket'])
    address.parent.mkdir(parents=True, exist_ok=True)
    address.unlink(missing_ok=True)
    server = Server(str(address), Handler)
    server.core = core
    os.chown(address, 0, account.pw_gid)
    address.chmod(0o660)
    # A read-only status snapshot supports the floating ball while this process is idle/off.
    status_path = directory / 'status.json'
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
        while not stop.is_set():
            core.poll_presence()
            core.capture()
            stop.wait(5 if any(t.get('standby') for t in core.live()) else core.sample)
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
            os.chown(status_path, 0, account.pw_gid)
            status_path.chmod(0o640)
            with core.lock:
                if core.live() or core.needs_dsh():
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
        core.store.close()
        address.unlink(missing_ok=True)
    return 42


if __name__ == '__main__':
    raise SystemExit(main())
