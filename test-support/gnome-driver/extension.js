import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
const XML='<node><interface name="org.dsh.TestDesktop"><method name="Call"><arg type="s" direction="in"/><arg type="s" direction="out"/></method></interface></node>';
export default class Driver extends Extension {
 enable(){
  const seat=Clutter.get_default_backend().get_default_seat();
  this.keyboard=seat.create_virtual_device(Clutter.InputDeviceType.KEYBOARD_DEVICE);
  this.pointer=seat.create_virtual_device(Clutter.InputDeviceType.POINTER_DEVICE);
  this.object=Gio.DBusExportedObject.wrapJSObject(XML,this);
  this.object.export(Gio.DBus.session,'/org/dsh/TestDesktop');
  this.owner=Gio.bus_own_name_on_connection(Gio.DBus.session,'org.dsh.TestDesktop',Gio.BusNameOwnerFlags.NONE,null,null);
 }
 windows(){return global.get_window_actors().map(a=>a.meta_window);}
 async capture(path){
  const stream=Gio.File.new_for_path(path).replace(null,false,Gio.FileCreateFlags.REPLACE_DESTINATION,null);
  try{await new Shell.Screenshot().screenshot(false,stream);}finally{stream.close(null);}
 }
 snapshot(){return {backend:'gnome-wayland',active_workspace:global.workspace_manager.get_active_workspace_index(),workspace_count:global.workspace_manager.n_workspaces,at:Date.now()/1000,screen:[global.stage.width,global.stage.height],windows:this.windows().map(w=>{
  const r=w.get_frame_rect();return {id:'gnome:'+w.get_stable_sequence(),pid:w.get_pid(),workspace:w.get_workspace()?.index(),title:w.get_title(),focused:global.display.focus_window===w,minimized:w.minimized,mapped:!w.minimized&&w.showing_on_its_workspace(),rect:[r.x,r.y,r.width,r.height],client_type:w.get_client_type()===Meta.WindowClientType.WAYLAND?'wayland':'x11',gtk_window_path:w.get_gtk_window_object_path(),gtk_application_path:w.get_gtk_application_object_path(),gtk_bus_name:w.get_gtk_unique_bus_name()};
 })};}
 Call(raw){
  try {
   const r=JSON.parse(raw);let w;
   if(r.window_id){w=this.windows().find(w=>'gnome:'+w.get_stable_sequence()===r.window_id);if(!w)throw Error('Window does not exist: '+r.window_id);}
   if(r.op==='screenshot')this.capture(r.path).catch(e=>console.error('Test screenshot: '+e.message));
   else if(r.op==='workspace-move')w.change_workspace_by_index(r.workspace,false);
   else if(r.op==='workspace-switch')global.workspace_manager.get_workspace_by_index(r.workspace).activate(global.get_current_time());
   else if(r.op==='layout'){w.unmaximize(Meta.MaximizeFlags.BOTH);w.move_resize_frame(true,...r.rect);}
   else if(r.op==='activate'){if(w.minimized)w.unminimize();Main.activateWindow(w);}
   else if(r.op==='minimize')w.minimize();
   else if(r.op==='restore')w.unminimize();
   else if(r.op==='close')w.delete(global.get_current_time());
   else if(r.op==='click'){
    this.pointer.notify_absolute_motion(GLib.get_monotonic_time(),r.x,r.y);
    this.pointer.notify_button(GLib.get_monotonic_time(),1,Clutter.ButtonState.PRESSED);
    this.pointer.notify_button(GLib.get_monotonic_time(),1,Clutter.ButtonState.RELEASED);
   } else if(r.op==='keys'){
    const keys=r.keys.map(k=>Clutter['KEY_'+k]??k);
    for(const k of keys)this.keyboard.notify_keyval(GLib.get_monotonic_time(),k,Clutter.KeyState.PRESSED);
    for(const k of keys.reverse())this.keyboard.notify_keyval(GLib.get_monotonic_time(),k,Clutter.KeyState.RELEASED);
   } else if(r.op!=='snapshot')throw Error('Unknown operation '+r.op);
   return JSON.stringify(this.snapshot());
  }catch(e){return JSON.stringify({error:e.message});}
 }
 disable(){this.object?.unexport();if(this.owner)Gio.bus_unown_name(this.owner);this.keyboard=null;this.pointer=null;}
}
