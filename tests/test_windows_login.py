import sys
from pathlib import Path
from unittest.mock import patch
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'dshmonitor-test-pack/runtime'))
from windows_login import classify_screen, sign_in


class LoginTests(unittest.TestCase):
    def test_dark_display_wakes_before_recognized_password(self):
        class VM:
            def __init__(self): self.commands=[]; self.checks=iter([False,False,True])
            def desktop_ready(self): return next(self.checks)
            def hmp(self,command): self.commands.append(command)
        vm=VM()
        with patch('windows_login.read_screen',side_effect=['display_off','password']),patch('time.sleep'):
            self.assertEqual(sign_in(vm,'abc',method='password'),'password_login')
        self.assertEqual(vm.commands[0],'sendkey shift 80')
        self.assertEqual(vm.commands.count('sendkey ret 80'),1)

    def test_screen_states(self):
        for text, expected in [
            ('请输入密码', 'password'), ('Enter your password', 'password'),
            ('请稍候', 'waiting'), ('20:41 9月17日 星期四', 'lock_screen'),
            ('输入你的 PIN 我忘记了我的 PIN', 'pin'),
            ('PIN 不正确。请重试 输入你的 PIN', 'rejected'),
            ('Enter your PIN I forgot my PIN', 'pin'),
            ('Enter A1B2C3 to try again', 'rejected'),
        ]:
            self.assertEqual(classify_screen(text), expected)

    def test_wait_before_input_and_no_extra_enter_after_auto_submit(self):
        class VM:
            def __init__(self): self.commands=[]; self.checks=iter([False]*4+[True])
            def desktop_ready(self): return next(self.checks)
            def hmp(self, command): self.commands.append(command)
        vm=VM()
        with patch('windows_login.read_screen', side_effect=['waiting','lock_screen','waiting','pin']), patch('time.sleep'):
            self.assertEqual(sign_in(vm,'123456'), 'pin_login')
        self.assertEqual(vm.commands[0], 'sendkey ret 80')
        self.assertEqual(vm.commands.count('sendkey ret 80'),1)
        self.assertEqual(vm.commands[1:3],['sendkey ctrl-a 80','sendkey backspace 80'])
        self.assertEqual(len(vm.commands),9)

    def test_rejected_pin_is_not_retried(self):
        class VM:
            def desktop_ready(self): return False
            def hmp(self, command): raise AssertionError('must not type into rejection screen')
        with patch('windows_login.read_screen',return_value='rejected'):
            with self.assertRaisesRegex(RuntimeError,'no automatic retry'):
                sign_in(VM(),'123456')

    def test_password_login_submits_once_after_recognized_field(self):
        class VM:
            def __init__(self): self.commands=[];self.checks=iter([False,False,True])
            def desktop_ready(self): return next(self.checks)
            def hmp(self,command): self.commands.append(command)
        vm=VM()
        with patch('windows_login.read_screen',side_effect=['pin','password']),patch('time.sleep'):
            self.assertEqual(sign_in(vm,'Example123',method='password'),'password_login')
        self.assertEqual(vm.commands.count('sendkey ret 80'),1)
        self.assertEqual(vm.commands[:2],['sendkey ctrl-a 80','sendkey backspace 80'])
