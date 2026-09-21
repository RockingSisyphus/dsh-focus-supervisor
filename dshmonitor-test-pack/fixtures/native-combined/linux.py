"""Real GTK windows; the collector is never fed fixture metadata as evidence."""
import sys,json,os
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
root=Path(sys.argv[1]);root.mkdir(parents=True,exist_ok=True)
config=json.loads(Path(__file__).with_name('window-data.json').read_text(encoding='utf-8'))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'test-support'))
from dsh_test_harness.gnome import call,action
windows={};edits={};last=None;native_ids={}
log=(root/'fixture.log').open('w',encoding='utf-8');log.write(config['log_marker']+'\n');log.flush()
for key in config['keys']:
 win=Gtk.Window(title=config['title']+' '+key);win.set_default_size(380,340)
 box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);win.add(box)
 box.pack_start(Gtk.Label(label=config['group_prefix']+key),False,False,0)
 edit=Gtk.Entry();edit.set_text(key+config['edit_suffix']);box.pack_start(edit,False,False,0)
 check=Gtk.CheckButton(label=config['checkbox']);check.set_active(True);box.pack_start(check,False,False,0)
 secret=Gtk.Entry();secret.set_visibility(False);secret.set_text(config['password']);box.pack_start(secret,False,False,0)
 hidden=Gtk.Label(label=config['hidden']);hidden.set_no_show_all(True);box.pack_start(hidden,False,False,0)
 win.show_all()
 windows[key]=win;edits[key]=edit
(root/'ready.json').write_text(json.dumps({'pid':os.getpid()}),encoding='utf-8')
def update():
 global last
 try:
  if not native_ids:
   snapshot=call('snapshot')['windows']
   resolved={}
   for key,win in windows.items():
    found=next((w for w in snapshot if w['pid']==os.getpid() and w['title']==config['title']+' '+key),None)
    if not found:return True
    resolved[key]=found['id']
   native_ids.update(resolved)
   for win in windows.values():win.set_title(config['title'])
  data=json.loads((root/'command.json').read_text(encoding='utf-8'))
  if data['id']==last:return True
  for key,opts in data['windows'].items():
   win=windows[key]
   if 'text' in opts:edits[key].set_text(opts['text'])
   win.show_all()  # Visibility preconditions are applied by the external driver.
  if data.get('focus'):edits[data['focus']].grab_focus()
  log.write('PHASE '+data['id']+'\n');log.flush();last=data['id']
  (root/'applied.json').write_text(json.dumps({'id':last,'windows':{key:int(identifier.split(':')[-1]) for key,identifier in native_ids.items()}}),encoding='utf-8')
 except (OSError,ValueError):pass
 return True
import ctypes
bridge=ctypes.CDLL('libatk-bridge-2.0.so.0');bridge.atk_bridge_adaptor_init(None,None)
GLib.timeout_add(100,update);Gtk.main()
