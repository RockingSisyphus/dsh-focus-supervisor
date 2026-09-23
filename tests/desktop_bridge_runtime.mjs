// Contract tests with delayed I/O, not a substitute for real GNOME execution.
import fs from 'node:fs';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../gnome-extension/extension.js',import.meta.url),'utf8').replace(/^import .*;.*$/gm,'').replace('export default class DesktopBridge','return class DesktopBridge');
let waiting=[],files=new Set(),drawFailure=false,drawFalse=false,sequence=0,disconnects=[];
const later=(cb,value,finish)=>{waiting.push(()=>cb(value,finish));};
class File {
 constructor(path){this.path=path;}
 get_child(name){return new File(this.path+'/'+name);}
 make_directory_async(priority,cancel,callback){later(callback,this,{});}
 make_directory_finish(){return true;}
 replace_async(etag,backup,flags,priority,cancel,callback){later(callback,this,{});}
 replace_finish(){files.add(this.path);return new Stream();}
 delete_async(priority,cancel,callback){later(callback,this,{});}
 delete_finish(){files.delete(this.path);return true;}
}
class Stream {close_async(priority,cancel,callback){later(callback,this,{});} close_finish(){return true;}}
class Variant {constructor(type,value){this.value=value;}}
const GLib={PRIORITY_DEFAULT:0,Variant,get_user_runtime_dir:()=>'/runtime',build_filenamev:p=>p.join('/'),uuid_string_random:()=>String(++sequence)};
const Gio={File:{new_for_path:p=>new File(p)},FileCreateFlags:{PRIVATE:1},IOErrorEnum:{EXISTS:1,NOT_FOUND:2},DBus:{session:{}},BusNameOwnerFlags:{NONE:0},BusNameWatcherFlags:{NONE:0},
 DBusExportedObject:{wrapJSObject:()=>({export(){},unexport(){}})},bus_own_name_on_connection:()=>1,bus_unown_name(){},bus_watch_name_on_connection:(bus,sender,flags,appeared,vanished)=>{disconnects.push(vanished);return disconnects.length;},bus_unwatch_name(){}};
const Shell={Screenshot:class {async screenshot(){if(drawFailure)throw Error('injected capture failure');return [!drawFalse,{}];} }};
const Bridge=new Function('GLib','Gio','Shell','Main','Extension','visibleIds',source)(GLib,Gio,Shell,{},class{},()=>new Set());
const bridge=new Bridge();bridge.enable();
bridge.snapshot=function(session){session.snapshots++;return {windows:[],screen:[0,0,100,100],ts:Date.now()/1000};};
globalThis.global={get_window_actors:()=>[]};
async function flush(){for(let i=0;i<80;i++){const batch=waiting;waiting=[];for(const callback of batch)callback();await Promise.resolve();}}
function call(op,sender=':test'){let reply;const result=bridge.CallAsync([JSON.stringify({op,id:op})],{get_sender:()=>sender,return_value:value=>{reply=JSON.parse(value.value[0]);}});return {result,get reply(){return reply;}};}
const pending=call('capture');
await Promise.resolve();
const busy=call('capture');await busy.result;assert.match(busy.reply.error,/正在进行/);
const status=call('status');await status.result;assert.equal(status.reply.busy,true);
assert.equal(status.reply.screenshots,0); // Status answered before any delayed file operation.
await flush();await pending.result;assert.ok(pending.reply.screen_capture);assert.equal(files.size,1);
const foreign=call('release',':other');await foreign.result;assert.equal(foreign.reply.released,false);assert.equal(files.size,1);
const release=call('release');await flush();await release.result;assert.equal(files.size,0);
const oldDisconnect=disconnects[0];
const next=call('capture');await flush();await next.result;
oldDisconnect();await flush();assert.equal(files.size,1); // Retired connection cannot revoke the next batch.
const nextRelease=call('release');await flush();await nextRelease.result;assert.equal(files.size,0);
drawFailure=true;const failed=call('capture');await flush();await failed.result;assert.match(failed.reply.error,/injected/);assert.equal(files.size,0);
drawFailure=false;drawFalse=true;const empty=call('capture');await flush();await empty.result;assert.match(empty.reply.error,/写入失败/);assert.equal(files.size,0);drawFalse=false;
const cancelled=call('capture');await Promise.resolve();bridge.disable();bridge.enable();await flush();await cancelled.result;
assert.match(cancelled.reply.error,/取消|停用/);assert.equal(files.size,0);assert.equal(bridge.session.snapshots,0);
console.log('Delayed I/O, single-flight, failure cleanup and disable/re-enable contracts passed');
