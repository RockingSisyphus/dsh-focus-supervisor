// Thin, on-demand compositor bridge. No sampling timer and no file IPC.
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {visibleIds} from './visibility.js';
const CODE_VERSION = 'dafeiyu-13';
const NAME = 'org.dafeiyu.Desktop';
const XML = `<node><interface name="${NAME}"><method name="Call"><arg type="s" direction="in"/><arg type="s" direction="out"/></method></interface></node>`;
function asyncIO(object, method, finish, ...args) {
    return new Promise((resolve,reject) => object[method](...args,(source,result) => {
        try { resolve(source[finish](result)); } catch(error) { reject(error); }
    }));
}
async function remove(file) {
    try { await asyncIO(file,'delete_async','delete_finish',GLib.PRIORITY_DEFAULT,null); }
    catch(error) { if(!error.matches?.(Gio.IOErrorEnum,Gio.IOErrorEnum.NOT_FOUND)) throw error; }
}
export default class DesktopBridge extends Extension {
    enable() {
        this.session={stopped:false,batch:null,files:new Set(),cursor:0,snapshots:0,screenshots:0};
        this.object=Gio.DBusExportedObject.wrapJSObject(XML,this);
        this.object.export(Gio.DBus.session,'/org/dafeiyu/Desktop');
        this.owner=Gio.bus_own_name_on_connection(Gio.DBus.session,NAME,Gio.BusNameOwnerFlags.NONE,null,null);
    }
    snapshot(session) {
        session.snapshots++;
        const workspace=global.workspace_manager.get_active_workspace();
        const tracker=Shell.WindowTracker.get_default();
        const actors=global.get_window_actors();
        const windows=global.display.sort_windows_by_stacking(actors.map(a=>a.meta_window)).map(window=>{
            const actor=actors.find(a=>a.meta_window===window),rect=window.get_frame_rect();
            const mapped=!window.minimized && window.located_on_workspace(workspace) && window.showing_on_its_workspace();
            return {id:'gnome:'+window.get_stable_sequence(),app:tracker.get_window_app(window)?.get_id()||window.get_wm_class()||'unknown',title:window.get_title()||'',pid:window.get_pid(),focused:global.display.focus_window===window,mapped,minimized:window.minimized,visible:mapped&&actor.visible,rect:[rect.x,rect.y,rect.width,rect.height],buffer_rect:(r=>[r.x,r.y,r.width,r.height])(window.get_buffer_rect())};
        });
        return {ts:Date.now()/1000,backend:'gnome',available:true,stacking_order:'bottom_to_top',windows,screen:[0,0,global.stage.width,global.stage.height],screen_capture:null,limitations:[]};
    }
    async clear(session,cancel=true) {
        if(cancel && session.batch)session.batch.cancelled=true;
        session.captureOwner=null;
        if(session.watch){Gio.bus_unwatch_name(session.watch);session.watch=null;}
        const files=[...session.files];
        for(const file of files){await remove(file);session.files.delete(file);}
    }
    async image(session,batch,file,draw) {
        if(session.stopped||batch.cancelled)throw Error('截图请求已取消');
        session.files.add(file);
        let stream;
        try {
            stream=await asyncIO(file,'replace_async','replace_finish',null,false,Gio.FileCreateFlags.PRIVATE,GLib.PRIORITY_DEFAULT,null);
            if(session.stopped||batch.cancelled)throw Error('截图请求已取消');
            await draw(stream);
        } finally {
            try {if(stream)await asyncIO(stream,'close_async','close_finish',GLib.PRIORITY_DEFAULT,null);}
            finally {if(session.stopped||batch.cancelled){await remove(file);session.files.delete(file);}}
        }
        if(session.stopped||batch.cancelled)throw Error('截图请求已取消');
    }
    async capture(session,sender) {
        if(session.batch)throw Error('截图正在进行');
        // A dedicated client connection owns this batch until Release or disconnect.
        const batch={cancelled:false,sender};session.batch=batch;
        try {
            await this.clear(session,false);
            session.captureOwner=batch;
            session.watch=Gio.bus_watch_name_on_connection(Gio.DBus.session,sender,Gio.BusNameWatcherFlags.NONE,null,()=>{
                if(session.captureOwner===batch)this.clear(session).catch(error=>console.error(error.message));
            });
            const root=Gio.File.new_for_path(GLib.build_filenamev([GLib.get_user_runtime_dir(),'dafeiyu-desktop']));
            try {await asyncIO(root,'make_directory_async','make_directory_finish',GLib.PRIORITY_DEFAULT,null);}
            catch(error){if(!error.matches?.(Gio.IOErrorEnum,Gio.IOErrorEnum.EXISTS))throw error;}
            const data=this.snapshot(session),id=GLib.uuid_string_random();
            const filename='screen-'+id+'.png';session.screenshots++;
            await this.image(session,batch,root.get_child(filename),async stream=>{
                const [success]=await new Shell.Screenshot().screenshot(false,stream);
                if(!success)throw Error('桌面截图写入失败');
            });
            data.screen_capture={file:filename,captured_at:data.ts,windows:data.windows.map(w=>({...w})),screen:data.screen};
            const visible=visibleIds(data.windows,data.screen);
            const actors=global.get_window_actors().filter(a=>visible.has('gnome:'+a.meta_window.get_stable_sequence()));
            for(let n=0;n<Math.min(4,actors.length);n++) {
                const actor=actors[(session.cursor+n)%actors.length],w=actor.meta_window;
                const record=data.windows.find(row=>row.id==='gnome:'+w.get_stable_sequence());
                const name='window-'+w.get_stable_sequence()+'-'+id+'.png';
                try {
                    const texture=actor.paint_to_content(null).get_texture();
                    const captured=Date.now()/1000;
                    await this.image(session,batch,root.get_child(name),async stream=>{
                        const image=await Shell.Screenshot.composite_to_stream(texture,0,0,-1,-1,1,null,0,0,1,stream);
                        if(!image)throw Error('窗口截图写入失败');
                    });
                    record.native_capture={file:name,captured_at:captured,window_id:record.id,pid:record.pid,title:record.title,rect:record.rect};
                } catch(error) {data.limitations.push('窗口截图失败：'+error.message);}
            }
            session.cursor=(session.cursor+4)%Math.max(1,actors.length);
            if(session.stopped||batch.cancelled)throw Error('截图请求已取消');
            return data;
        } catch(error) {await this.clear(session);throw error;}
        finally {if(session.batch===batch)session.batch=null;}
    }
    action(request) {
        const now=Date.now()/1000;
        if(!(request.expires_at>now && request.expires_at<=now+3))throw Error('桌面动作请求已过期');
        const w=global.get_window_actors().map(a=>a.meta_window).find(w=>'gnome:'+w.get_stable_sequence()===request.window_id);
        if(!w)return {acted:false,already_closed:true,window_id:request.window_id,reason:'window-not-found'};
        const pidMatch=w.get_pid()===request.pid;
        const markerMatch=request.op==='focus' && typeof request.marker==='string' && request.marker.length>=3 && (w.get_title()||'').includes(request.marker);
        if(!pidMatch && !markerMatch)throw Error('窗口所属进程已改变');
        if(request.op==='minimize')w.minimize();
        else if(request.op==='close')w.delete(global.get_current_time());
        else {if(w.minimized)w.unminimize();Main.activateWindow(w);}
        return {acted:true,window_id:request.window_id,reason:'requested'};
    }
    async CallAsync([raw],invocation) {
        const session=this.session;let request={};
        try {
            request=JSON.parse(raw);
            if(session.stopped)throw Error('桌面接口已停用');
            let result;
            switch(request.op) {
            case 'status':result={running:true,snapshots:session.snapshots,screenshots:session.screenshots,busy:!!session.batch};break;
            case 'snapshot':result=this.snapshot(session);break;
            case 'capture':result=await this.capture(session,invocation.get_sender());break;
            case 'release':
                if(session.captureOwner && session.captureOwner.sender!==invocation.get_sender()) {
                    result={released:false,reason:'another-capture-owner'};
                } else {await this.clear(session);result={released:true};}
                break;
            case 'focus':case 'minimize':case 'close':result=this.action(request);break;
            default:throw Error('未知桌面操作');
            }
            if(session.stopped)throw Error('桌面接口已停用');
            invocation.return_value(new GLib.Variant('(s)',[JSON.stringify({...result,request_id:request.id,code_version:CODE_VERSION})]));
        } catch(error) {invocation.return_value(new GLib.Variant('(s)',[JSON.stringify({request_id:request.id,code_version:CODE_VERSION,error:error.message})]));}
    }
    disable() {
        const session=this.session;if(!session)return;
        session.stopped=true;
        this.object?.unexport();if(this.owner)Gio.bus_unown_name(this.owner);
        this.clear(session).catch(error=>console.error('Desktop cleanup: '+error.message));
    }
}
