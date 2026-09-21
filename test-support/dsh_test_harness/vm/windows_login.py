"""Recognize the VM's Windows sign-in screen before sending credentials.

OCR stays on the controller, and screenshots stay in the private VM directory.
Never retry a rejected credential: that can lock the account.
"""
import re
import subprocess


def classify_screen(text):
    compact = re.sub(r'\s+', '', text).lower()
    if any(term in compact for term in (
        '不正确', '错误', '重试', 'incorrect', 'wrong', 'tryagain',
        'a1b2c3', '质询', 'challenge', '已锁定', 'lockedout',
        '登录选项已禁用', 'signinoptionisdisabled',
    )):
        return 'rejected'
    if any(term in compact for term in ('请稍候', '欢迎', 'pleasewait', 'welcome', '正在更新', 'workingonupdates')):
        return 'waiting'
    # Sparse-text OCR over the lock-screen photo reliably reads the Chinese prompt but
    # often loses the small Latin "PIN" label, so the localized "输入你的/输入您的" is
    # the signal. A password prompt is deliberately NOT treated as a PIN screen:
    # typing the PIN there risks locking the account.
    if any(term in compact for term in ('密码', 'password')):
        return 'password'
    if any(term in compact for term in ('输入你的', '输入您的', 'enteryour', '我忘记', 'iforgot')):
        return 'pin'
    if re.search(r'\b\d{1,2}[:：]\d{2}\b', text):
        return 'lock_screen'
    return 'unknown'


def read_screen(vm):
    path = vm.directory / 'login-current.ppm'
    vm.hmp('screendump ' + str(path))
    path.chmod(0o600)
    from PIL import Image
    with Image.open(path) as screen:
        if screen.convert('L').getextrema()[1] < 4:
            return 'display_off'
    result = subprocess.run(
        ['tesseract', str(path), 'stdout', '-l', 'eng+chi_sim', '--psm', '11'],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise RuntimeError('Windows login observation requires tesseract with eng and chi_sim language data')
    state=classify_screen(result.stdout)
    # The small Chinese password placeholder can be unreadable to OCR. For a
    # configured password account, recognize its large account name in the
    # actual sign-in pane; the field is focused by Windows itself.
    if state=='unknown' and vm.config.get('login_method')=='password' and vm.config.get('login_name'):
        from PIL import Image
        with Image.open(path) as im:
            w,h=im.size
            pane=im.crop((w*.25,h*.42,w*.75,h*.68)).resize((w,int(h*.52)))
            crop=path.with_name('login-pane.png');pane.save(crop);crop.chmod(0o600)
        text=subprocess.run(['tesseract',str(crop),'stdout','-l','eng+chi_sim','--psm','6'],capture_output=True,text=True,timeout=15).stdout
        pane_state=classify_screen(text)
        if pane_state!='unknown':return pane_state
        # The lock-screen wallpaper adds OCR noise beside the account name.
        # Match the complete configured name, not an otherwise empty OCR line.
        if re.search(r'(?<!\w)'+re.escape(vm.config['login_name'])+r'(?!\w)',text,re.IGNORECASE):return 'password'
    return state


def sign_in(vm, secret, *, timeout=180, method="pin"):
    import time
    deadline = time.monotonic() + timeout
    display_woken = False
    submitted = False
    entered_at = None
    dismissals = 0
    confirmed = False
    observations=[]
    while time.monotonic() < deadline:
        if vm.desktop_ready():
            return method+'_login' if submitted else 'already_logged_in'
        state = read_screen(vm)
        if getattr(vm,'diagnostic_out',None):
            import json
            observations.append({'at':time.time(),'state':state,'submitted':submitted})
            (vm.diagnostic_out/'login-observations.json').write_text(json.dumps(observations),encoding='utf-8')
        if state == 'display_off' and not display_woken:
            # An all-black frame has no login controls. Wake the display once;
            # credentials are still sent only after recognizing their field.
            vm.hmp('sendkey shift 80')
            display_woken = True
            continue
        if state == 'rejected':
            raise RuntimeError('Windows rejected the credential or requires account recovery; no automatic retry was made')
        if state == 'lock_screen' and not submitted:
            # One Enter right after boot can be swallowed while the guest is still painting,
            # and the previous code gave up after a single attempt. Keep asking, alternating
            # keys, until the PIN field actually appears.
            if dismissals < 8:
                vm.hmp('sendkey ' + ('ret' if dismissals % 2 == 0 else 'spc') + ' 80')
            dismissals += 1
            time.sleep(1.5)
            continue
        if state == method and not submitted:
            # Clear leftovers explicitly; Ctrl+A alone does not remove stale input.
            vm.hmp('sendkey ctrl-a 80'); time.sleep(.2)
            vm.hmp('sendkey backspace 80'); time.sleep(.2)
            for char in secret:
                key = ('shift-' + char.lower()) if char.isupper() else char
                vm.hmp('sendkey ' + key + ' 80')
                time.sleep(.5)
            submitted = True
            if method == 'password':
                vm.hmp('sendkey ret 80')
                confirmed = True
            entered_at = time.monotonic()
        elif state == method and submitted and not confirmed and time.monotonic() - entered_at > 10:
            # Some accounts require Enter; auto-submit PINs normally leave this
            # screen themselves. Never send Enter to an error or desktop screen.
            if not vm.desktop_ready():
                vm.hmp('sendkey ret 80')
                confirmed = True
        time.sleep(1)
    raise TimeoutError('Windows sign-in screen did not reach an unlocked desktop')
