"""Use the installer-registered DSH host without starting a competing profile."""
import subprocess


class UserServiceHost:
    def __init__(self, log):
        self.log = log
        self.unit = 'dsh-web.service'
        environment = self.run('show-environment').stdout.splitlines()
        self.previous_key = next((row.partition('=')[2] for row in environment if row.startswith('DSH_TEST_KEY=')), None)
        self.run('set-environment', 'DSH_TEST_KEY=local-fixed-not-a-real-key')
        self.restart()

    def run(self, *args):
        return subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, check=True, timeout=30)

    def restart(self):
        self.run('restart', self.unit)
        self.invocation = self.run('show', self.unit, '-p', 'InvocationID', '--value').stdout.strip()

    def refresh_log(self):
        result = subprocess.run(['journalctl', '--user', '_SYSTEMD_INVOCATION_ID='+self.invocation, '--no-pager', '-o', 'cat'], capture_output=True, text=True, check=True, timeout=10)
        self.log.write_text(result.stdout, encoding='utf-8')

    def poll(self):
        self.refresh_log()
        state = self.run('show', self.unit, '-p', 'ActiveState', '--value').stdout.strip()
        return None if state in ('active', 'activating') else 1

    def close(self):
        try:
            self.run('stop', self.unit)
        finally:
            if self.previous_key is None:
                self.run('unset-environment', 'DSH_TEST_KEY')
            else:
                self.run('set-environment', 'DSH_TEST_KEY='+self.previous_key)
