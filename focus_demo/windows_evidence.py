"""Export project evidence with the installing user's ordinary desktop token.

The elevated service remains the action executor. Only filesystem delivery uses
the interactive desktop token, so OWNER RIGHTS inherited from a project refer to the user,
not Builtin Administrators. No password or per-report authorization is needed.
"""
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def desktop_user():
    import ctypes
    from ctypes import wintypes
    import win32api
    import win32con
    import win32security as security
    # TokenLinkedToken can be identification-only. The interactive shell owns
    # the actual ordinary primary token required for filesystem impersonation.
    user32=ctypes.WinDLL('user32',use_last_error=True)
    user32.GetShellWindow.restype=wintypes.HWND
    user32.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    pid=wintypes.DWORD()
    if not user32.GetWindowThreadProcessId(user32.GetShellWindow(),ctypes.byref(pid)):
        raise ctypes.WinError(ctypes.get_last_error())
    process=win32api.OpenProcess(0x1000,False,pid.value)
    token=None;impersonation=None
    try:
        token=security.OpenProcessToken(process,win32con.TOKEN_QUERY|win32con.TOKEN_DUPLICATE)
        impersonation=security.DuplicateToken(token,security.SecurityImpersonation)
        security.ImpersonateLoggedOnUser(impersonation)
        try:
            yield
        finally:
            security.RevertToSelf()
    finally:
        if impersonation is not None:impersonation.Close()
        if token is not None:token.Close()
        process.Close()


def repair_legacy_owner(folder):
    """Migrate only old administrator-owned plugin exports; preserve their ACLs."""
    import win32api
    import win32con
    import win32security as security
    folder=Path(folder)
    task=folder if folder.name.startswith('task-') else folder.parent
    if task.parent.name!='.dafeiyu':raise ValueError('不是任务证据目录')
    token=security.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
    try:user=security.GetTokenInformation(token,security.TokenUser)[0]
    finally:token.Close()
    administrators=security.CreateWellKnownSid(security.WinBuiltinAdministratorsSid,None)
    paths=[task.parent,task]
    if task.exists() and not task.is_symlink():
        import os
        for root,dirs,files in os.walk(task,followlinks=False):
            dirs[:]=[name for name in dirs if not (Path(root)/name).is_symlink()]
            paths.extend(Path(root)/name for name in dirs+files)
    for path in paths:
        if not path.exists() or path.is_symlink():continue
        sd=security.GetFileSecurity(str(path),security.OWNER_SECURITY_INFORMATION)
        if sd.GetSecurityDescriptorOwner()==administrators:
            security.SetNamedSecurityInfo(str(path),security.SE_FILE_OBJECT,security.OWNER_SECURITY_INFORMATION,user,None,None,None)


def deliver(operation,request):
    from .evidence_export import user_export,user_verify,user_cleanup
    repair_legacy_owner(request['folder'])
    with desktop_user():
        return {'export':user_export,'verify_export':user_verify,'cleanup_export':user_cleanup}[operation](request)
