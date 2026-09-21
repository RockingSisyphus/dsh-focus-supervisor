"""One native reminder, run as the desktop user; no shell strings or model logic."""
import json
import os
from pathlib import Path
import sys
import time

request=json.loads(sys.stdin.readline())
if sys.platform=='win32':
    sys.path.insert(0,str(Path(__file__).parent))
    from desktop_notify_windows import notify
    notify(request)
    raise SystemExit(0)
if os.environ.get('DISPLAY'):os.environ['GDK_BACKEND']='x11'
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gdk,GdkPixbuf,Gio,GLib,Pango
assets=Path(__file__).resolve().parents[1]/'assets'
if not assets.is_dir():assets=Path(__file__).resolve().parents[1]/'dsh-plugin/assets'
image=assets/(request['image']+'.png')
result={'pid':os.getpid(),'popup':False,'notification':False,'sound':False,'errors':[]}
window=None
if request.get('notification'):
    try:
        bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
        reply=bus.call_sync('org.freedesktop.Notifications','/org/freedesktop/Notifications',
            'org.freedesktop.Notifications','Notify',
            GLib.Variant('(susssasa{sv}i)',('大肥鱼监工',0,str(image),'大肥鱼监工',GLib.markup_escape_text(request['message']),[],{},10000)),
            GLib.VariantType.new('(u)'),Gio.DBusCallFlags.NONE,5000,None)
        result['notification']=True;result['notification_id']=reply.unpack()[0]
    except Exception as error:result['errors'].append('通知：'+str(error))
def apply_cute_style():
    """Blue-pink pastel card shared with the DSH floating panel; failure never blocks the popup."""
    try:
        provider=Gtk.CssProvider()
        provider.load_from_data(b'''
        #dafeiyu-window { background-color:#FBF7FF; }
        #dafeiyu-card { background-image: linear-gradient(150deg,#FFE9F4 0%,#F7F2FF 46%,#E8F3FF 100%); border-radius:24px; }
        #dafeiyu-title { color:#3F4B6E; font-size:15px; font-weight:700; }
        #dafeiyu-hint { color:#7C89AC; font-size:11px; }
        #dafeiyu-bubble { background-color:#FFFFFF; border-radius:18px; }
        #dafeiyu-message { color:#3F4B6E; font-size:15px; }
        #dafeiyu-primary { background-image: linear-gradient(135deg,#FFA7CB 0%,#9CCBFF 100%); color:#FFFFFF; font-weight:700;
          border:none; border-radius:16px; padding:11px 20px; }
        #dafeiyu-primary:hover { background-image: linear-gradient(135deg,#FF97C1 0%,#8BC2FF 100%); }
        #dafeiyu-note { color:#A9B4D0; font-size:10px; }
        ''')
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(),provider,Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    except Exception:
        pass
if request.get('popup'):
    try:
        ok,_=Gtk.init_check(None)
        if not ok:raise RuntimeError('无法连接图形会话')
        apply_cute_style()
        window=Gtk.Window(title='大肥鱼监工提醒')
        window.set_keep_above(True);window.set_resizable(False);window.set_border_width(0)
        window.set_name('dafeiyu-window')
        shell=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12)
        shell.set_name('dafeiyu-card');shell.set_border_width(20)
        window.add(shell)
        header=Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,spacing=8)
        title=Gtk.Label(label='🐟 大肥鱼监工');title.set_name('dafeiyu-title');title.set_xalign(0)
        header.pack_start(title,False,False,0)
        hint=Gtk.Label(label='温柔提醒');hint.set_name('dafeiyu-hint');hint.set_xalign(1)
        header.pack_end(hint,False,False,0)
        shell.pack_start(header,False,False,0)
        pixbuf=GdkPixbuf.Pixbuf.new_from_file_at_scale(str(image),320,320,True)
        shell.pack_start(Gtk.Image.new_from_pixbuf(pixbuf),False,False,0)
        bubble=Gtk.Box();bubble.set_name('dafeiyu-bubble')
        label=Gtk.Label(label=request['message']);label.set_name('dafeiyu-message')
        label.set_line_wrap(True);label.set_max_width_chars(34);label.set_selectable(True);label.set_can_focus(False)
        # Reminder text is model-written: keep a very long one from growing past the screen.
        try:
            label.set_lines(14);label.set_ellipsize(Pango.EllipsizeMode.END)
        except Exception:pass
        label.set_margin_top(12);label.set_margin_bottom(12);label.set_margin_start(16);label.set_margin_end(16)
        bubble.add(label);shell.pack_start(bubble,False,False,0)
        note=Gtk.Label(label='解释、修改约定和完成验收都在监工聊天里进行');note.set_name('dafeiyu-note')
        shell.pack_start(note,False,False,0)
        button=Gtk.Button(label='知道了，我去监工聊天里解释 / 继续任务')
        button.set_name('dafeiyu-primary')
        # A reminder must not hijack typing: while the popup holds keyboard focus, the next
        # Space/Enter in whatever the user is writing activates this button and opens a
        # browser page by accident. Keep it mouse-only.
        button.set_can_focus(False);button.set_focus_on_click(False);button.set_can_default(False)
        def return_to_chat(*_):
            sys.path.insert(0,str(Path(__file__).parent))
            from open_chat import FocusSuperseded,open_chat
            # Hide before foregrounding the destination so closing this popup cannot
            # hand focus back afterwards. Keep GTK responsive while the helper waits.
            button.set_sensitive(False);window.hide()
            def finish(error):
                if error:
                    label.set_text('无法打开监工聊天：'+str(error));button.set_sensitive(True);window.show_all()
                else:window.destroy()
                return False
            def work():
                try:open_chat(request['chat_url'],request.get('chat_registry'));error=None
                except FocusSuperseded:error=None
                except Exception as caught:error=caught
                GLib.idle_add(finish,error)
            import threading
            threading.Thread(target=work,daemon=True).start()
        button.connect('clicked',return_to_chat);shell.pack_start(button,False,False,0)
        window.connect('destroy',lambda *_:Gtk.main_quit())
        window.show_all()
        display=Gdk.Display.get_default();monitor=display.get_primary_monitor() or display.get_monitor(0)
        rect=monitor.get_workarea();width,height=window.get_size()
        window.move(rect.x+(rect.width-width)//2,rect.y+(rect.height-height)//2)
        # Stay visible without taking the keyboard away from the user's own window.
        try:
            window.set_accept_focus(False);window.set_focus_on_map(False);window.set_keep_above(True)
        except Exception:pass
        window.present();result['popup']=True
        if '--test-auto-close' in sys.argv:
            # Test-only: let the harness click the real button instead of guessing a spot.
            allocation=button.get_allocation()
            result['button_center']=[allocation.x+allocation.width//2,allocation.y+allocation.height//2]
    except Exception as error:result['errors'].append('弹窗：'+str(error))
if request.get('sound'):
    try:
        gi.require_version('GSound','1.0')
        from gi.repository import GSound
        sound=GSound.Context();sound.init(None)
        sound.play_simple({'event.id':'message-new-instant','application.name':'大肥鱼监工'},None)
        result['sound']=True
    except Exception as error:result['errors'].append('提示音：'+str(error))
print(json.dumps(result,ensure_ascii=True),flush=True)
if result['popup']:
    if '--test-auto-close' in sys.argv:GLib.timeout_add(8000,lambda:window.destroy())
    Gtk.main()
elif result['sound']:
    loop=GLib.MainLoop();GLib.timeout_add(1500,lambda:loop.quit());loop.run()
