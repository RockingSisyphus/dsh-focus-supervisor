"""Real GUI fixture; only its visible contents are scripted, never collector data."""
import os,json
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
window=Gtk.Window(title='论文阅读 · 人工审核测试');window.set_default_size(720,430)
label=Gtk.Label();window.add(label);window.connect('destroy',Gtk.main_quit)
control=Path(os.environ['FOCUS_FIXTURE_PID']).with_name('activity.json');previous=None
def update():
    global previous
    value=json.loads(control.read_text()) if control.exists() else {'title':'论文阅读 · 人工审核测试','text':'正在阅读论文：事务提交与回滚。\n这是专用测试窗口。'}
    if value!=previous:
        window.set_title(value['title']);label.set_text(value['text']);window.show_all();window.present();previous=value
    return True
update();GLib.timeout_add(250,update)
Path(os.environ['FOCUS_FIXTURE_PID']).write_text(str(os.getpid()))
Gtk.main()
