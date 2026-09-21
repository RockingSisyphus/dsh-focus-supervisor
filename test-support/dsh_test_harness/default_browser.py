"""Temporarily route OS URL opening to the same real browser profile as the test."""
import os,subprocess,uuid
from pathlib import Path

class DefaultBrowser:
    def __init__(self,argv):
        self.argv=argv;self.saved=[];self.created=[]
        if os.name=='nt':
            import winreg
            for scheme in ('http','https'):
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,'Software\\Microsoft\\Windows\\Shell\\Associations\\UrlAssociations\\'+scheme+'\\UserChoice') as key:
                    progid=winreg.QueryValueEx(key,'ProgId')[0]
                path='Software\\Classes\\'+progid+'\\shell\\open\\command'
                if any(row[0]==path for row in self.saved):continue
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path) as key:old=winreg.QueryValueEx(key,'')
                except FileNotFoundError:old=None
                self.saved.append((path,old))
                parts=path.split('\\')
                for i in range(3,len(parts)+1):
                    partial='\\'.join(parts[:i])
                    try:
                        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,partial):pass
                    except FileNotFoundError:self.created.append(partial)
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,path) as key:
                    winreg.SetValueEx(key,'',0,winreg.REG_SZ,subprocess.list2cmdline(argv)+' "%1"')
        else:
            self.previous={scheme:subprocess.check_output(['xdg-mime','query','default','x-scheme-handler/'+scheme],text=True).strip() for scheme in ('http','https')}
            directory=Path.home()/'.local/share/applications';directory.mkdir(parents=True,exist_ok=True)
            self.file=directory/('dsh-test-browser-'+uuid.uuid4().hex+'.desktop')
            def quote(value):return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')+'"'
            self.file.write_text('[Desktop Entry]\nType=Application\nName=DSH test browser\nExec='+' '.join(quote(a) for a in argv)+' %U\nMimeType=x-scheme-handler/http;x-scheme-handler/https;\n',encoding='utf-8')
            subprocess.run(['xdg-mime','default',self.file.name,'x-scheme-handler/http','x-scheme-handler/https'],check=True)
    def close(self):
        if os.name=='nt':
            import winreg
            for path,old in self.saved:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,path,0,winreg.KEY_SET_VALUE) as key:
                    if old is None:winreg.DeleteValue(key,'')
                    else:winreg.SetValueEx(key,'',0,old[1],old[0])
            for path in reversed(self.created):winreg.DeleteKey(winreg.HKEY_CURRENT_USER,path)
        else:
            for scheme,previous in self.previous.items():subprocess.run(['xdg-mime','default',previous,'x-scheme-handler/'+scheme],check=True)
            self.file.unlink()
