import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdtemp,rm,readFile,writeFile} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {apply,formatReport,request} from './chat-host.mjs';
const socketName = dir => process.platform === 'win32' ? '\\\\.\\pipe\\dafeiyu-test-' + path.basename(dir) : path.join(dir,'agent.sock');
test('all chat tools compile against installed DSH; no artifact threshold or form fields',async()=>{
 const registrations=[],disposers=[];
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:()=>()=>{}},tools:{register:t=>registrations.push(t)},on:()=>{},webServer:{register:()=>()=>{}}};
 try{await apply(ctx);assert.equal(registrations.length,10);assert.ok(registrations.some(t=>t.name==='focus_plan'));assert.ok(!registrations.some(t=>t.name==='focus_dashboard'));
  for(const name of ['focus_plan','focus_revise']){
   const properties=registrations.find(t=>t.name===name).parameters.properties;
   assert.ok(!Object.hasOwn(properties,'deadline_policy'),`${name} has no deadline policy parameter`);
  }
  const settings=registrations.find(t=>t.name==='focus_settings');
  assert.ok(settings.parameters.properties.patch_json.description.includes('instructions_full'),'the model is told it may update the full documentation');}finally{for(const d of disposers.reverse())d();}
});
test('focus_help returns the full documentation as plain text without full-access escalation',async()=>{
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-help-'));
 const shipped=JSON.parse(await readFile(new URL('./default-prompts.json',import.meta.url),'utf8'));
 // An installation upgraded from an older version stored a row without the full document.
 await writeFile(path.join(dir,'settings.json'),JSON.stringify({id:'global',instructions:'旧版摘要',heartbeat_prompt:'旧版心跳',mascot_size:144}));
 const registrations=[],disposers=[],escalations=[];
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:()=>()=>{}},tools:{register:t=>registrations.push(t)},on:()=>{},webServer:{register:()=>()=>{}},
  sessionController:{resolveAgent:async()=>{escalations.push('resolved');return {agent:{session:{id:'chat'},ctx:{systemPrompt:{context:()=>()=>{}}}}};},prompt:async()=>({accepted:true})},
  permissionPresets:{current:()=>'danger-full-access',apply:(session,preset)=>escalations.push(preset)},approval:{setPolicy:()=>{}}};
 try{
  await apply(ctx,{stateDirectory:dir,socketPath:socketName(dir)});
  const help=registrations.find(t=>t.name==='focus_help');assert.ok(help,'focus_help must be registered');
  const result=await help.execute({}, {agent:{session:{id:'chat'},ctx:{systemPrompt:{context:()=>()=>{}}}}});
  assert.equal(typeof result.text,'string');
  assert.ok(result.text.includes('focus_status')&&result.text.includes('focus_plan'),'full API documentation is returned');
  assert.ok(result.text.includes(shipped.instructions_full),'a stored row without the new field falls back to the shipped document');
  assert.ok(shipped.instructions_full.includes('到点自动结束监督'));
  assert.ok(!shipped.instructions_full.includes('deadline_policy'));
  assert.ok(shipped.instructions.includes('agreement 与 task_prompt 应简短具体'));
  assert.ok(shipped.heartbeat_prompt.includes('临近结束仍未完成时'));
  assert.ok(result.text.includes('\n'),'documentation keeps real newlines instead of JSON escaping');
  assert.deepEqual(escalations,[],'reading the documentation must not switch the session to full access');
 }finally{for(const d of disposers.reverse())d();await rm(dir,{recursive:true});}
});
test('compact heartbeat keeps facts without repeating the agreement',()=>{
 const s=formatReport({phase:'monitor',report_id:'r',task:{id:'t',agreement:'读懂论文',start_at:1,end_at:2,allow_early_finish:true},overview:{program_count:0,gui_window_count:0,effective_observed_seconds:2,unobserved_gap_seconds:1,programs:[]},capture_error:'没有桌面权限'});
 for(const expected of ['报告编号：r','没有桌面权限','focus_report'])assert.ok(s.includes(expected));
});
test('heartbeat states the plugin-decided absence countdown so the model can ask the user',()=>{
 const base={phase:'monitor',report_id:'r',task:{id:'t',agreement:'读论文',start_at:1,end_at:2,allow_early_finish:true},overview:{program_count:0,gui_window_count:0,effective_observed_seconds:600,unobserved_gap_seconds:0,programs:[]},presence:{available:true,idle_seconds:620,last_input_at:1}};
 const quiet=formatReport({...base,input_activity:{available:true,idle_seconds:620,no_input_in_report:true,consecutive_no_input_heartbeats:2,heartbeats_until_standby:1,away_heartbeats:3}});
 assert.ok(quiet.includes('没有任何鼠标或键盘输入'),'quiet heartbeat says there was no input');
 assert.ok(quiet.includes('2/3')&&quiet.includes('1'),'quiet heartbeat shows the countdown');
 const active=formatReport({...base,input_activity:{available:true,idle_seconds:3,no_input_in_report:false,consecutive_no_input_heartbeats:0,heartbeats_until_standby:3,away_heartbeats:3}});
 assert.ok(active.includes('有新的鼠标或键盘输入'),'active heartbeat says there was input');
 const blind=formatReport({...base,presence:{available:false},input_activity:{available:false,no_input_in_report:null,consecutive_no_input_heartbeats:0,heartbeats_until_standby:3,away_heartbeats:3}});
 assert.ok(blind.includes('无法判断'),'unavailable input evidence is stated instead of guessed');
});
test('agent presence is documented as recorded only, never as the standby trigger',async()=>{
 const registrations=[],disposers=[];
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:()=>()=>{}},tools:{register:t=>registrations.push(t)},on:()=>{},webServer:{register:()=>()=>{}}};
 try{
  await apply(ctx);
  const observe=registrations.find(t=>t.name==='focus_observe');
  assert.ok(observe.parameters.properties.presence.description.includes('不触发待机'),'presence no longer decides standby');
  const settings=registrations.find(t=>t.name==='focus_settings');
  assert.ok(settings.parameters.properties.patch_json.description.includes('away_heartbeats'),'the threshold is configurable through settings');
 }finally{for(const d of disposers.reverse())d();}
});
test('Local socket transport rejects backend errors and returns structured data',async()=>{
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-socket-')),sock=socketName(dir);
 const server=http.createServer((req,res)=>{res.writeHead(req.url==='/bad'?400:200);res.end(JSON.stringify(req.url==='/bad'?{error:'wrong session'}:{live:[]}));});
 await new Promise(r=>server.listen(sock,r));
 try{assert.deepEqual(await request('/state',{},sock),{live:[]});await assert.rejects(request('/bad',{},sock),/wrong session/);}finally{await new Promise(r=>server.close(r));await rm(dir,{recursive:true});}
});
test('settings reset sends the prompts shipped with this plugin package',async()=>{
 const shipped=JSON.parse(await readFile(new URL('./default-prompts.json',import.meta.url),'utf8'));
 for(const key of ['instructions','instructions_full','heartbeat_prompt'])assert.ok(shipped[key]&&shipped[key].length,'default-prompts.json ships '+key);
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-reset-')),sock=socketName(dir);
 const seen=[];
 const server=http.createServer((req,res)=>{let body='';req.on('data',c=>body+=c);req.on('end',()=>{seen.push({url:req.url,body});res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({settings:{},ok:true}));});});
 await new Promise(r=>server.listen(sock,r));
 const routes=new Map(),disposers=[],injectListeners=[];
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:()=>()=>{}},tools:{register:()=>{}},on:(name,fn)=>{if(name==='webserver/index-inject')injectListeners.push(fn);},webServer:{register:r=>{routes.set(r.path,r.handler);return()=>{};}}};
 try{
  await apply(ctx,{socketPath:sock});
  const table=[];for(const fn of injectListeners)fn(table);
  const token=table.find(item=>item.name==='__DAFEIYU__')?.value?.token;
  assert.ok(token,'the settings route accepts the page token');
  const replies=[];
  const req={method:'POST',socket:{remoteAddress:'127.0.0.1'},headers:{'x-focus-token':token},
   async *[Symbol.asyncIterator](){yield JSON.stringify({reset:true});}};
  const res={writeHead(code,headers){this.code=code;this.headers=headers;},end(body){replies.push({code:this.code,body});}};
  await routes.get('/focus/settings')(req,res);
  const reset=seen.find(item=>item.url==='/settings/ui');
  assert.ok(reset,'reset is forwarded to the backend settings endpoint');
  const patch=JSON.parse(reset.body).patch;
  for(const key of ['instructions','instructions_full','heartbeat_prompt'])assert.equal(patch[key],shipped[key],'reset restores shipped '+key);
  assert.equal(patch.mascot_size,undefined,'reset leaves the mascot size alone');
 }finally{for(const d of disposers.reverse())d();await new Promise(r=>server.close(r));await rm(dir,{recursive:true});}
});
test('settings panel exposes the full documentation field and a reset control',async()=>{
 const source=await readFile(new URL('./client.js',import.meta.url),'utf8');
 assert.ok(source.includes('instructions_full'),'the settings panel can display the full documentation field');
 assert.ok(/reset:!0|reset:\s*true/.test(source),'the settings panel posts a reset request');
 assert.ok(source.includes('重置'),'the reset control is labelled for the user');
});
test('every session carries only the short summary; the full document stays on demand',async()=>{
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-summary-'));
 const sections=[],disposers=[];
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:s=>{sections.push(s);return()=>{};}},tools:{register:()=>{}},on:()=>{},webServer:{register:()=>()=>{}}};
 try{
  await apply(ctx,{stateDirectory:dir,socketPath:socketName(dir)});
  const summary=sections.find(s=>s.name==='dafeiyu-monitor');
  assert.ok(summary,'the plugin registers its always-on system-prompt section');
  const text=summary.text({});
  const shipped=JSON.parse(await readFile(new URL('./default-prompts.json',import.meta.url),'utf8'));
  assert.ok(text.length<1500,`the always-on summary stays small (${text.length} chars)`);
  assert.ok(shipped.instructions_full.length>3000,'the full API document is shipped for focus_help');
  assert.ok(!text.includes(shipped.instructions_full),'the full document is never injected into every session');
  assert.ok(text.includes('focus_help'),'the summary points the model at focus_help');
 }finally{for(const d of disposers.reverse())d();await rm(dir,{recursive:true});}
});
test('status tools never carry the full document into the model context',async()=>{
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-status-')),sock=socketName(dir);
 const full='# 完整文档\n'+'逐条接口说明。'.repeat(200);
 const state={settings:{id:'global',instructions:'# 摘要',instructions_full:full,heartbeat_prompt:'心跳',mascot_size:144},live:[],tasks:[],reports:[],alerts:[],events:[]};
 const server=http.createServer((req,res)=>{let body='';req.on('data',c=>body+=c);req.on('end',()=>{res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(req.url==='/state'?state:{settings:state.settings,ok:true}));});});
 await new Promise(r=>server.listen(sock,r));
 const registrations=[],disposers=[],routes=new Map(),inject=[];
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:()=>()=>{}},tools:{register:t=>registrations.push(t)},on:(name,fn)=>{if(name==='webserver/index-inject')inject.push(fn);},webServer:{register:r=>{routes.set(r.path,r.handler);return()=>{};}}};
 try{
  await apply(ctx,{socketPath:sock});
  const status=await registrations.find(t=>t.name==='focus_status').execute({},{agent:{session:{id:'chat'},ctx:{systemPrompt:{context:()=>()=>{}}}}});
  assert.equal(status.report.settings,undefined);
  assert.deepEqual(status.report.live,[]);
  const get=await registrations.find(t=>t.name==='focus_settings').execute({operation:'get'},{agent:{session:{id:'chat'},ctx:{systemPrompt:{context:()=>()=>{}}}}});
  assert.equal(get.report.instructions_full,full,'explicit settings query remains complete');
  const update=await registrations.find(t=>t.name==='focus_settings').execute({operation:'update',patch_json:'{"mascot_size":160}'},{agent:{session:{id:'chat'},ctx:{systemPrompt:{context:()=>()=>{}}}}});
  assert.equal(update.report.settings,undefined);
  assert.deepEqual(Object.keys(update.report.changed),['mascot_size']);
  // The browser settings panel still receives it: only the model-facing tools are trimmed.
  const table=[];for(const fn of inject)fn(table);const token=table.find(item=>item.name==='__DAFEIYU__')?.value?.token;
  let payload=null;const res={writeHead(){},end(body){payload=body;}};
  await routes.get('/focus/status')({method:'GET',socket:{remoteAddress:'127.0.0.1'},headers:{'x-focus-token':token}},res);
  assert.equal(JSON.parse(payload).settings.instructions_full,full,'the settings panel still receives the full document');
 }finally{for(const d of disposers.reverse())d();await new Promise(r=>server.close(r));await rm(dir,{recursive:true});}
});
test('the chat registry heals itself when something else overwrites it',async()=>{
 // 真机实测过：注册文件被别的进程改成死地址后，旧逻辑只在端口变化时才写，于是弹窗一直照着
 // 死地址回退。这里钉住"每次轮询都比对文件内容、不对就写回来"。
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-registry-')),sock=socketName(dir);
 const state={settings:{id:'global',instructions:'# 摘要',heartbeat_prompt:'心跳',mascot_size:144},live:[],tasks:[],reports:[],alerts:[],events:[]};
 const server=http.createServer((req,res)=>{req.on('data',()=>{});req.on('end',()=>{res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(req.url==='/state'?state:{ok:true}));});});
 await new Promise(r=>server.listen(sock,r));
 const disposers=[];
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:()=>()=>{}},tools:{register:()=>{}},
  on:()=>{},webServer:{port:41234,register:()=>()=>{}}};
 const previous=process.env.DSH_HOME;process.env.DSH_HOME=dir;
 try{
  await apply(ctx,{socketPath:sock});
  const file=path.join(dir,'dafeiyu-chat-endpoint.json');
  assert.equal((await readFile(file,'utf8')).trim(),'{"origin":"http://127.0.0.1:41234"}');
  await writeFile(file,JSON.stringify({origin:'http://127.0.0.1:9'}));
  const deadline=Date.now()+12000;
  while(Date.now()<deadline&&(await readFile(file,'utf8')).includes(':9'))await new Promise(r=>setTimeout(r,250));
  assert.equal((await readFile(file,'utf8')).trim(),'{"origin":"http://127.0.0.1:41234"}','被改写的注册文件必须被写回来');
 }finally{
  for(const d of disposers.reverse())d();
  if(previous===undefined)delete process.env.DSH_HOME;else process.env.DSH_HOME=previous;
  await new Promise(r=>server.close(r));await rm(dir,{recursive:true});
 }
});
test('a reminder switch request is claimed by exactly one open page',async()=>{
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-switch-')),sock=socketName(dir);
 const state={settings:{id:'global',instructions:'# 摘要',heartbeat_prompt:'心跳',mascot_size:144},live:[],
  tasks:[{id:'task-1',session_id:'session-target',project_dir:'/tmp/project'}],reports:[],alerts:[],events:[]};
 const server=http.createServer((req,res)=>{let body='';req.on('data',c=>body+=c);req.on('end',()=>{res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(req.url==='/state'?state:{ok:true}));});});
 await new Promise(r=>server.listen(sock,r));
 const disposers=[],routes=new Map(),inject=[];
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:()=>()=>{}},tools:{register:()=>{}},
  on:(name,fn)=>{if(name==='webserver/index-inject')inject.push(fn);},webServer:{register:r=>{routes.set(r.path,r.handler);return()=>{};}},
  // A deep link lands on DSH's real root; the launch token is the only thing its URL may carry.
  connection:{authenticatedUrl:base=>base+'?token=launch-token'}};
 const call=(path,options={})=>{const {method='POST',token,body,local=true,url,page,visible}=options;
  const chunks=body===undefined?[]:[Buffer.from(JSON.stringify(body))];
  const headers={...(token===undefined?{}:{'x-focus-token':token}),...(page?{'x-focus-page':page}:{}),...(visible===undefined?{}:{'x-focus-visible':visible?'1':'0'})};
  const req={method,url:url||path,headers,socket:{remoteAddress:local?'127.0.0.1':'10.0.0.1'},
   on(){},
   async *[Symbol.asyncIterator](){for(const chunk of chunks)yield chunk;}};
  let status=0,raw='';
  const res={writeHead(code){status=code;},end(value){raw=value===undefined?'':String(value);}};
  // Held responses answer after the handler returned, so the result is read lazily: a
  // long-poll that is still waiting has no status yet, and one that was just woken does.
  const result=()=>({get status(){return status;},get body(){try{return JSON.parse(raw);}catch{return raw;}}});
  return routes.get(path)(req,res).then(result);};
 try{
  await apply(ctx,{socketPath:sock});
  const table=[];for(const fn of inject)fn(table);const token=table.find(item=>item.name==='__DAFEIYU__')?.value?.token;
  assert.ok(token,'the page receives its plugin token');
  // No page has polled yet, so the popup must open one itself.
  const cold=await call('/focus/open-request',{body:{session:'session-target'}});
  assert.equal(cold.status,200);assert.equal(cold.body.open_page,false,'without a polling page the popup opens a browser');
  await call('/focus/status',{method:'GET',token});
  const warm=await call('/focus/open-request',{body:{session:'session-target'}});
  assert.equal(warm.body.open_page,true,'a polling page can take the switch');
  assert.ok(warm.body.id,'the request is addressable so the popup can wait for it');
  assert.equal((await call('/focus/open-request',{method:'GET',url:'/focus/open-request?id='+warm.body.id})).body.claimed,false);
  const first=await call('/focus/open-claim',{token});
  assert.deepEqual({session:first.body.session,project_dir:first.body.project_dir},{session:'session-target',project_dir:'/tmp/project'});
  assert.deepEqual((await call('/focus/open-claim',{token})).body,{},'a later tab must not switch as well');
  assert.equal((await call('/focus/open-request',{method:'GET',url:'/focus/open-request?id='+warm.body.id})).body.claimed,true);
  assert.equal((await call('/focus/open-request',{method:'GET',url:'/focus/open-request?id='+warm.body.id})).body.completed,false,'delivery is not successful navigation');
  assert.equal((await call('/focus/open-complete',{token,page:'wrong-page',body:{id:warm.body.id}})).status,409);
  assert.equal((await call('/focus/open-complete',{token,body:{id:warm.body.id}})).body.session_ready,true);
  assert.equal((await call('/focus/open-request',{method:'GET',url:'/focus/open-request?id='+warm.body.id})).body.session_ready,true);
  assert.equal((await call('/focus/open-request',{method:'GET',url:'/focus/open-request?id='+warm.body.id})).body.completed,false,'page navigation is not native activation');
  assert.equal((await call('/focus/open-result',{body:{id:warm.body.id,raised:true}})).body.completed,true);

  assert.equal((await call('/focus/open-release',{token,body:{id:warm.body.id}})).body.released,false,'terminal requests cannot be replayed');
  assert.deepEqual((await call('/focus/open-claim',{token})).body,{});
  const stale=await call('/focus/open-request',{body:{session:'session-target'}});
  await call('/focus/open-request',{body:{session:'session-target'}});
  assert.equal((await call('/focus/open-request',{method:'GET',url:'/focus/open-request?id='+stale.body.id})).body.expired,true,'a replaced request is stale');
  assert.equal((await call('/focus/open-complete',{token,body:{id:stale.body.id}})).status,409,'late page completion cannot overwrite the newest request');
  assert.equal((await call('/focus/open-result',{body:{id:stale.body.id,raised:true}})).status,409,'late native completion cannot overwrite the newest request');
  assert.equal((await call('/focus/open-claim',{})).status,403,'the claim needs the page token');
  assert.equal((await call('/focus/open-request',{body:{session:'session-unknown'}})).status,404,'only supervision sessions may be switched to');
  assert.equal((await call('/focus/open-request',{body:{session:'session-target'},local:false})).status,403,'loopback only');
  // A background tab cannot rely on its 5 second poll: the browser throttles it down to
  // about once a minute, which is exactly the window a reminder popup holds focus in. The
  // held channel therefore has to receive the switch as soon as the popup asks for it.
  await call('/focus/open-claim',{token});
  const firstHolder=call('/focus/claim-wait',{method:'GET',token});
  // Only the newest holder is kept: two tabs may not both switch for one reminder.
  const secondHolder=call('/focus/claim-wait',{method:'GET',token});
  assert.deepEqual((await firstHolder).body,{},'a replaced channel is released empty-handed');
  const handed=await call('/focus/open-request',{body:{session:'session-target'}});
  const delivered=await secondHolder;
  assert.equal(delivered.body.session,'session-target','the waiting page receives the switch without polling');
  assert.equal(delivered.body.project_dir,'/tmp/project','the switch carries the project directory the client needs');
  assert.equal((await call('/focus/open-request',{method:'GET',url:'/focus/open-request?id='+handed.body.id})).body.claimed,false,'sending to an orphaned channel cannot reserve a request');
  const liveClaim=await call('/focus/open-claim',{token,page:'live',body:{id:handed.body.id}});
  assert.equal(liveClaim.body.accepted,true,'a live page explicitly takes ownership');
  assert.deepEqual((await call('/focus/open-claim',{token,page:'late',body:{id:handed.body.id}})).body,{});
  assert.equal((await call('/focus/claim-wait',{})).status,403,'the held channel needs the page token');
  const holderA=await call('/focus/claim-wait',{method:'GET',token,page:'a'});
  const holderB=await call('/focus/claim-wait',{method:'GET',token,page:'b'});
  assert.equal(holderA.status,0);assert.equal(holderB.status,0,'pages do not evict each other');
  const offered=await call('/focus/open-request',{body:{session:'session-target'}});
  assert.equal(holderA.status,200);assert.equal(holderB.status,200,'all connected documents can notice an unclaimed request');
  assert.equal((await call('/focus/open-request',{method:'GET',url:'/focus/open-request?id='+offered.body.id})).body.claimed,false);
  assert.deepEqual((await call('/focus/open-claim',{token,page:'a',body:{id:handed.body.id}})).body,{},'a delayed offer cannot claim a replacement');
  assert.equal((await call('/focus/open-claim',{token,page:'b',body:{id:offered.body.id}})).body.accepted,true);
  const expiring=await call('/focus/open-request',{body:{session:'session-target'}});
  const now=Date.now;try{Date.now=()=>now()+70000;
    assert.deepEqual((await call('/focus/open-claim',{token})).body,{},'expired work cannot be claimed');
    assert.equal((await call('/focus/open-result',{body:{id:expiring.body.id,raised:true}})).status,409,'expired completion cannot revive a request');
  }finally{Date.now=now;}

  // The deep link is the reminder popup's address when no page takes the switch. DSH's URL
  // is always the bare root, so the link must not invent a session parameter: it arms the
  // handoff and lands on the real root, where the page claims it.
  const coldRequest=await call('/focus/open-request',{body:{session:'session-target'}});
  assert.equal((await call('/focus/open',{method:'GET',url:'/focus/open?session=session-target&request='+coldRequest.body.id})).status,200);
  assert.equal((await call('/focus/open-claim',{token})).body.id,coldRequest.body.id,'cold redirect reuses the popup request');
  const deep=await call('/focus/open',{method:'GET',url:'/focus/open?session=session-target'});
  assert.equal(deep.status,200);
  assert.ok(!String(deep.body).includes('focusSession'),'the link must not carry a session parameter');
  assert.ok(String(deep.body).includes('?token=launch-token'),'the link lands on the authenticated DSH root');
  assert.deepEqual((await call('/focus/open-claim',{token})).body,{},'GET must not offer a new request to the document being unloaded');
  assert.ok(String(deep.body).includes("fetch('/focus/open-request'"),'the landing document creates the handoff after navigation');
  await call('/focus/open-request',{body:{session:'session-target'}});
  assert.deepEqual({session:(await call('/focus/open-claim',{token})).body.session},{session:'session-target'},'the landed page can claim the deep link');
  assert.equal((await call('/focus/open',{method:'GET',url:'/focus/open?session=session-missing'})).status,404,'only supervision sessions may be linked');
  assert.equal((await call('/focus/open',{method:'GET',url:'/focus/open?session=session-target',local:false})).status,403,'loopback only');
 }finally{for(const d of disposers.reverse())d();await new Promise(r=>server.close(r));await rm(dir,{recursive:true});}
});

test('Windows first install loads without backend config and reloads the installed endpoint',async()=>{
 const {installedWindowsConfig}=await import('./chat-host.mjs');
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-first-install-')),filename=path.join(dir,'config.json');
 try {
  const initial={socketPath:'/run/dafeiyu/agent.sock'};
  assert.deepEqual(await installedWindowsConfig(initial,filename),initial);
  await writeFile(filename,JSON.stringify({port:18769,token:'test-token',data_dir:dir,task_name:'test-task'}));
  const loaded=await installedWindowsConfig(initial,filename);
  assert.equal(loaded.socketPath,'http://127.0.0.1:18769');assert.equal(loaded.stateDirectory,dir);
 }finally{await rm(dir,{recursive:true,force:true});}
});

test('reminder routing stays responsive while the service state RPC is busy',async()=>{
 const dir=await mkdtemp(path.join(os.tmpdir(),'focus-busy-state-'));
 const sock=socketName(dir),routes=new Map(),disposers=[];
 const server=http.createServer((req,res)=>setTimeout(()=>{res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({tasks:[{session_id:'session-busy',project_dir:dir}]}));},2000));
 await new Promise(r=>server.listen(sock,r));
 await writeFile(path.join(dir,'status.json'),JSON.stringify({tasks:[{session_id:'session-busy',project_dir:dir}]}));
 const ctx={effect:fn=>{const d=fn();if(d)disposers.push(d);},systemPrompt:{section:()=>()=>{}},tools:{register:()=>{}},on:()=>{},webServer:{register:r=>{routes.set(r.path,r.handler);return()=>{};}}};
 try{
  await apply(ctx,{socketPath:sock,stateDirectory:dir});
  let response;
  const req={method:'POST',socket:{remoteAddress:'127.0.0.1'},async *[Symbol.asyncIterator](){yield JSON.stringify({session:'session-busy'});}};
  const call=routes.get('/focus/open-request')(req,{writeHead(code){this.code=code;},end(raw){response={code:this.code,body:JSON.parse(raw)};}});
  await Promise.race([call,new Promise(r=>setTimeout(r,1000))]);
  assert.equal(response?.code,200,'a busy state RPC must not outlast the popup request');
  assert.ok(response.body.id);
 }finally{for(const d of disposers.reverse())d();await new Promise(r=>server.close(r));await rm(dir,{recursive:true});}
});

test('sampling output cap retains evidence pointers and only bounds the activity directory',()=>{
 const data={task:{agreement:'work',id:'t',start_at:1,end_at:2},report_id:'r',overview:{programs:[{app:'APP'.repeat(80),id:'p',example_titles:[]}],effective_observed_seconds:1,unobserved_gap_seconds:0},evidence_export:{folder:'/evidence'},reporting:{overview_chars:25}};
 const actual=formatReport(data);
 assert.ok(actual.includes('- '+data.overview.programs[0].app.slice(0,23)+'\n[活动摘要已截断'));
 assert.ok(actual.includes('证据目录：/evidence'));
 assert.ok(actual.includes('报告编号：r'));
 assert.ok(!actual.includes(data.overview.programs[0].app));
});
