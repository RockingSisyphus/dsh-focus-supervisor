import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk
w=Gtk.Window(title='监工测试记事本 DSH_NOTEPAD');w.set_default_size(620,360)
v=Gtk.TextView();v.get_buffer().set_text('DSH_NOTEPAD_CONTENT\n这是本轮测试专门打开的可编辑记事本。\n最终仅关闭这个窗口，不操作其他程序。');w.add(v)
w.connect('destroy',Gtk.main_quit);w.show_all();w.present();Gtk.main()
