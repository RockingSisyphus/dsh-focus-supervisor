import http from 'node:http';
import z from '@deepseek-ai/schemastery';
import path from 'node:path';
import {mascotState} from './mascot-state.mjs';
import {compactResult,taskContext} from './model-output.mjs';
import {elevationPlan,installArtifacts,payloadStatus,runInstall,setupStatus} from './setup.mjs';
import {readFileSync} from 'node:fs';
import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { homedir } from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { createHash, randomBytes } from 'node:crypto';
import { defineTool } from '@deepseek-ai/dsh-tools';
export const name = 'focus-supervisor-chat';
export const inject = ['tools', 'sessionController', 'webServer', 'attachments', 'systemPrompt', 'permissionPresets', 'approval', 'connection'];
const execFileAsync = promisify(execFile);
const run = (file,args,options={}) => execFileAsync(file,args,{windowsHide:true,...options});
export function request(endpoint, body = {}, socketPath = '/run/dafeiyu/agent.sock', token = '', timeout = 40000) {
  return new Promise((resolve, reject) => {
    const data = JSON.stringify(body);
    let transport={socketPath};
    if(socketPath.startsWith('http:')){
      const url=new URL(socketPath);
      if(url.hostname!=='127.0.0.1'||!token)throw new Error('Loopback backend requires a token');
      transport={hostname:url.hostname,port:url.port};
    }
    const req = http.request({...transport, path:endpoint, method:'POST', headers:{'content-type':'application/json', 'content-length':Buffer.byteLength(data),...(token?{'authorization':'Bearer '+token}:{})}}, res => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', chunk => { text += chunk; if (text.length > 12_000_000) req.destroy(new Error('Report too large')); });
      res.on('end', () => { try { const result=JSON.parse(text); if(res.statusCode!==200) throw new Error(result.error); resolve(result); } catch(e){reject(e);} });
      res.on('error',reject);
    });
    req.setTimeout(timeout,()=>req.destroy(new Error('Supervisor timeout')));
    req.on('error',reject); req.end(data);
  });
}
const defaults=JSON.parse(readFileSync(new URL('./default-prompts.json',import.meta.url),'utf8'));
// These tools only read text; they must not switch the session to full access.
const READ_ONLY_TOOLS=['focus_status','focus_settings','focus_help'];
const samplingSchema=JSON.parse(readFileSync(new URL('./backend/focus_demo/sampling-settings.json',import.meta.url),'utf8'));
for(const fields of Object.values(samplingSchema))for(const spec of Object.values(fields))spec.default=spec.platform_defaults?.[process.platform==='linux'?'linux':'windows']??spec.default;
const samplingDefaults=Object.fromEntries(Object.entries(samplingSchema).map(([group,fields])=>[group,Object.fromEntries(Object.entries(fields).map(([key,spec])=>[key,spec.default]))]));
export const instructions = defaults.instructions;
function readConfiguredPrompts(directory){let saved={};try{saved=JSON.parse(readFileSync(path.join(directory,'settings.json'),'utf8'));}catch{}return {...defaults,...saved,...Object.fromEntries(Object.entries(samplingDefaults).map(([group,fields])=>[group,{...fields,...saved[group]}]))};}
const backendRequest=request;
export const Config=z.object({windowsTask:z.string().default(''),windowsStarter:z.string().default(''),backendToken:z.string().default(''),socketPath:z.string().default('/run/dafeiyu/agent.sock'),stateDirectory:z.string().default('/var/lib/dafeiyu'),desktopSetupScript:z.string().default('/opt/dafeiyu/deploy/desktop_setup.py')});

const str = (description,required=true) => ({type:'string',...(required?{required:true}:{}),description});
const agreement = {
  task_prompt:str('本任务每次心跳附加的监督提示词，创建时必填'),
  project_dir:str('当前监工会话的项目绝对目录，证据将写入其中的 .dafeiyu 子目录'),
  agreement:str('与用户协商确定的任务内容和完成标准'),
  start_at:str('ISO 8601 开始时间，必须带时区'), end_at:str('ISO 8601 结束时间，必须带时区'),
  check_interval_seconds:{type:'integer',description:'常规检查间隔，单位秒。预约时省略默认600秒；修订时省略保留当前间隔。'},
  allow_early_finish:{type:'boolean',required:true},
  deadline_policy:{type:'string',required:true,enum:['stop','discuss','continue']},
};
function dates(args) {
  for (const k of ['start_at','end_at']) {
    if (!/(Z|[+-]\d\d:\d\d)$/i.test(args[k]) || !Number.isFinite(Date.parse(args[k]))) throw new Error('时间必须是带时区的 ISO 8601');
    args[k]=Date.parse(args[k])/1000;
  }
  return args;
}
function humanIdle(seconds) {
  if (!Number.isFinite(seconds)) return '未知时长';
  const total = Math.max(0, Math.round(seconds));
  return total >= 60 ? `${Math.floor(total / 60)} 分 ${total % 60} 秒` : `${total} 秒`;
}
function inputActivityLine(data) {
  const activity = data.input_activity || {};
  if (activity.available === false || data.presence?.available === false)
    return '本轮输入活动：无法判断（空闲计数或采集接口不可用）；采集缺失不作为离席依据，请结合画面判断。';
  if (activity.no_input_in_report === true)
    return `本轮输入活动：本次心跳期间没有任何鼠标或键盘输入（已静止 ${humanIdle(activity.idle_seconds)}；连续无输入心跳 ${activity.consecutive_no_input_heartbeats}/${activity.away_heartbeats}，再有 ${activity.heartbeats_until_standby} 次将自动进入待机）。若你怀疑用户其实在场（例如任务本身不需要输入），请在待机前用 focus_act 弹窗询问是否真的离席。`;
  return `本轮输入活动：期间有新的鼠标或键盘输入（当前已静止 ${humanIdle(activity.idle_seconds)}）。`;
}
export function formatReport(data) {
  const {task,overview}=data;
  const rows=overview.activity_changes?.length
    ? overview.activity_changes.map(p=>`- ${p.title}（${p.window_id}）：焦点 ${p.focus_seconds}s，可见 ${p.visible_seconds}s，最长连续焦点 ${p.longest_focus_seconds}s；变化 ${JSON.stringify(p.recent_changes)}；证据 ${p.latest_evidence?.join(',')||'见活动详情'}`)
    : (overview.programs||[]).map(p=>`- ${p.app}（${p.id}）：焦点 ${p.focus_seconds}s，可见 ${p.visible_seconds}s；${(p.example_titles||[]).join(' / ')}`);
  const exported=data.evidence_export;
  const overviewLimit=data.reporting?.overview_chars;
  const summary=rows.join('\n')||'没有可用的窗口活动记录。';
  const shownSummary=overviewLimit&&summary.length>overviewLimit?summary.slice(0,overviewLimit)+'\n[活动摘要已截断；用 focus_report(read_activity_changes) 继续读取。]':summary;
  return `[大肥鱼心跳：${data.phase||'monitor'}]
${data.test_mode?'【测试模式】'+(data.test_time_override?`时长已模拟覆盖；真实采集 ${data.real_observed_seconds}s。`:'未覆盖采集时长。'):''}
任务编号：${task.id}；报告编号：${data.report_id}
采集时间范围：${data.window_start??'未知'} 至 ${data.window_end??'未知'}。
观察时长 ${overview.effective_observed_seconds}s，采集缺口 ${overview.unobserved_gap_seconds}s。
${inputActivityLine(data)}
${overview.activity_changes?.some(p=>p.body_scope==='process_window_group')?'正文含同进程歧义窗口组，可能包含隐藏内容；请结合截图自行判断归属。':''}
${shownSummary}
当前焦点：${(overview.current_objects||[]).filter(o=>o.focused).map(o=>o.title).join('；')||'未知或无焦点'}。
浏览器正文：${overview.browser_semantics?.snapshots||0} 条（失败 ${overview.browser_semantics?.failed_snapshots||0} 条）。系统摘录可能包含视口外文字；详情 browser-snapshots.json。
${(overview.browser_semantics?.limitations||[]).join('；')}
${data.capture_error?'采集不可用：'+data.capture_error:''}
${data.error||''}
证据目录：${exported?.folder||'尚不可用：'+(exported?.error||'未导出')}
活动变化用 focus_report(read_activity_changes) 分页；原始证据仍可按需读取。整屏若可用已附上。`;
}

export async function installedWindowsConfig(config,filename) {
  let installed;
  try { installed=JSON.parse((await readFile(filename,'utf8')).replace(/^\uFEFF/,'')); }
  catch(error) { if(error.code==='ENOENT')return config; throw error; }
  return {...config,socketPath:'http://127.0.0.1:'+installed.port,backendToken:installed.token,stateDirectory:installed.data_dir,windowsTask:installed.task_name,windowsStarter:installed.starter_task};
}

export async function apply(ctx,config={}) {
  const windowsAutoConfig=process.platform==='win32' && (!config.socketPath || config.socketPath==='/run/dafeiyu/agent.sock');
  const windowsConfigPath=path.join(process.env.ProgramData||'C:/ProgramData','Dafeiyu','config.json');
  if(windowsAutoConfig) config=await installedWindowsConfig(config,windowsConfigPath);
  // Test/demo hook: pretend the backend is missing so the first-run card is reachable.
  const forceSetup=config.forceSetup===true;
  let stateDirectory=config.stateDirectory||(process.platform==='win32'?path.join(process.env.ProgramData||'C:/ProgramData','Dafeiyu','data'):'/var/lib/dafeiyu');
  const request=(endpoint,body={},timeout)=>backendRequest(endpoint,body,config.socketPath||'/run/dafeiyu/agent.sock',config.backendToken||'',timeout);
  const configuredPrompts=()=>readConfiguredPrompts(stateDirectory);
  let disposed=false, polling=false, pollError=null;
  const deliveryErrors=new Map();
  const attempts=new Map();
  const dshHome=process.env.DSH_HOME||path.join(homedir(),'.dsh');
  const deliveryPath=path.join(dshHome,'dafeiyu-notices-delivered.json');
  const chatRegistry=path.join(dshHome,'dafeiyu-chat-endpoint.json');
  let registeredPort;
  async function registerChatEndpoint() {
    const port=ctx.webServer.port;
    if(!Number.isInteger(port)||port<=0)return;
    const wanted=JSON.stringify({origin:`http://127.0.0.1:${port}`});
    // 这个文件是"提醒弹窗该找哪个地址"的唯一凭据。它可能被别人改掉（另一个插件进程、测试
    // 夹具），而只按内存里的 registeredPort 判断就会一直不再写——于是弹窗照着死地址回退，
    // 开了个连不上的页面。所以每次轮询都比一下文件内容，不对就写回来。
    let current='';
    try{current=(await readFile(chatRegistry,'utf8')).trim();}catch{}
    if(registeredPort===port&&current===wanted)return;
    await mkdir(dshHome,{recursive:true});
    await writeFile(chatRegistry,wanted,{mode:0o600});
    registeredPort=port;
  }
  await registerChatEndpoint();
  let deliveredNotices=new Set();
  try{deliveredNotices=new Set(JSON.parse(await readFile(deliveryPath,'utf8')));}catch{}
  async function rememberNotice(id){
    deliveredNotices.add(id);await mkdir(path.dirname(deliveryPath),{recursive:true});
    await writeFile(deliveryPath+'.tmp',JSON.stringify([...deliveredNotices]),{mode:0o600});
    await rename(deliveryPath+'.tmp',deliveryPath);
  }
  const sessionPermissions={},permissionRepairs={};
  const lifetime=new AbortController();
  const uiToken=randomBytes(24).toString('hex');
  let installState=null,setupCache=null,setupCheckedAt=0;
  // A reminder's "back to the supervision chat" button asks an already open DSH page to
  // switch, instead of opening another tab. A live page explicitly accepts the offer;
  // page readiness and verified native foreground completion are separate outcomes.
  let lastStatusPollAt=0,pendingOpen=null,lastOpenRequest=null;
  const claimWaiters=new Map();
  // Every page reports itself while it polls: a page identifier and whether the user can
  // see it. Only diagnostics — a hidden page is what makes a switch invisible.
  const pageSightings=new Map();
  function notePage(req) {
    const page=String(req.headers['x-focus-page']||'').slice(0,32);
    if(!page)return;
    pageSightings.delete(page);
    pageSightings.set(page,{page,visible:req.headers['x-focus-visible']!=='0',at:Date.now()});
    // Keep the list bounded and drop pages that stopped polling long ago.
    for(const [key,value] of pageSightings){if(pageSightings.size>8||Date.now()-value.at>60000)pageSightings.delete(key);}
  }
  const OPEN_REQUEST_TTL_MS=60000, OPEN_PAGE_WINDOW_MS=12000, CLAIM_WAIT_HOLD_MS=90000;
  // A deep link lands on a page that still has to boot before it can claim, so its request
  // outlives the popup probe by a wide margin. Browsers also throttle the tab that is
  // loading behind the reminder popup.
  const OPEN_DEEP_LINK_TTL_MS=60000;
  function takePendingForClaim(page='legacy') {
    if(!pendingOpen||pendingOpen.claimed||pendingOpen.expires_at<Date.now())return null;
    pendingOpen.claimed=true;pendingOpen.page=page;
    if(lastOpenRequest)lastOpenRequest.claimed_at=Date.now();
    if(lastOpenRequest)lastOpenRequest.page=page;
    return {id:pendingOpen.id,session:pendingOpen.session,project_dir:pendingOpen.project_dir,expires_at:pendingOpen.expires_at,accepted:true};
  }
  function createOpenRequest(sessionId,projectDir,ttlMs) {
    pendingOpen={id:randomBytes(12).toString('hex'),session:sessionId,project_dir:projectDir||null,
      claimed:false,completed:false,expires_at:Date.now()+ttlMs};
    lastOpenRequest={id:pendingOpen.id,status:'pending',session:sessionId,open_page:claimWaiters.size>0||Date.now()-lastStatusPollAt<OPEN_PAGE_WINDOW_MS,
      created_at:Date.now(),claimed_at:null,released_at:null};
    // Keep one channel per page. Multiple tabs must not continuously evict one another.
    const candidates=[...claimWaiters.entries()].sort(([a],[b])=>Number(pageSightings.get(b)?.visible)-Number(pageSightings.get(a)?.visible));
    for(const [page,waiter] of candidates){
      claimWaiters.delete(page);clearTimeout(waiter.timer);
      if(waiter.closed())continue;
      // Delivery is only an offer. A departed document can leave a held response
      // behind; reserve the request only when a live page explicitly claims it.
      waiter.send({id:pendingOpen.id,session:pendingOpen.session,project_dir:pendingOpen.project_dir});
    }
    return pendingOpen;
  }
  function cachedSetupStatus() {
    if (!setupCache||Date.now()-setupCheckedAt>30000) { setupCache=setupStatus({force:forceSetup}); setupCheckedAt=Date.now(); }
    return setupCache;
  }
  ctx.effect(()=>ctx.systemPrompt.section({name:'dafeiyu-monitor',order:85,text:()=>configuredPrompts().instructions}));
  const contextAgents=new WeakSet();
  function attachTaskContext(agent) {
    if(!agent?.session||contextAgents.has(agent))return;
    ctx.effect(()=>agent.ctx.systemPrompt.context({name:'dafeiyu-task',order:85,text:()=>{
      try {return taskContext(JSON.parse(readFileSync(path.join(stateDirectory,'status.json'),'utf8')),agent.session.id,configuredPrompts());}
      catch(error){if(error.code==='ENOENT')return '';throw error;}
    }}));
    contextAgents.add(agent);
  }
  ctx.on('agent/created',({agent})=>attachTaskContext(agent));
  let desktopCache=null, desktopChecked=0;
  async function desktopStatus() {
    if(desktopCache && Date.now()-desktopChecked<10000)return desktopCache;
    try {
      const {stdout}=await run('/usr/bin/python3',['-I',config.desktopSetupScript||'/opt/dafeiyu/deploy/desktop_setup.py','status'],{timeout:12000,maxBuffer:100000});
      desktopCache=JSON.parse(stdout);
    } catch(e) {
      desktopCache={code:'setup_unavailable',screenshot_verified:false,message:'桌面采集组件尚未安装或无法检测，请运行后台安装程序。'};
    }
    desktopChecked=Date.now();return desktopCache;
  }
  async function rawState() {
    const desktop_setup=desktopCache;
    try { return {...await request('/state'),running:true,desktop_setup,session_permissions:{...sessionPermissions},permission_repairs:{...permissionRepairs}}; }
    catch(error) {
      if(!['ENOENT','ECONNREFUSED','EINVAL','ENOTSOCK','EACCES'].includes(error.code)) throw error;
      try { return {...JSON.parse(await readFile(path.join(stateDirectory,'status.json'),'utf8')),running:false,desktop_setup}; }
      catch(e) { if(e.code==='ENOENT') return {live:[],tasks:[],running:false,desktop_setup}; throw e; }
    }
  }
  async function focusTask(sessionId) {
    // The service publishes task/session metadata before acknowledging tools.
    // Reminder routing needs that metadata, not a fresh desktop/report RPC.
    try {
      const published=JSON.parse(await readFile(path.join(stateDirectory,'status.json'),'utf8'));
      const task=(published.tasks||[]).find(t=>t.session_id===sessionId);
      if(task)return task;
    } catch(error) { if(error.code!=='ENOENT')throw error; }
    const current=await rawState();
    return (current.tasks||[]).find(t=>t.session_id===sessionId);
  }
  async function state() {
    const value=await rawState(); const live=value.live||[];
    // The panel only needs the first-run card while the backend is missing; keep the
    // payload digest off the 5s polling path once it is installed.
    const installed=!forceSetup&&(value.running===true||installArtifacts().installed);
    // Which DSH pages are watching, and whether the user can actually see them. A handoff
    // taken by a hidden page switches a tab nobody is looking at, so this has to be
    // diagnosable instead of guessed from a click that appeared to do nothing.
    const pages=[...pageSightings.values()].map(p=>({page:p.page,visible:p.visible,seen_at:p.at}));
    const saved=value.settings||configuredPrompts();
    const protectedLive=saved.protect_task_changes?live:[];
    return {...value,delivery_errors:Object.fromEntries(deliveryErrors),poll_error:pollError,focus_request:lastOpenRequest,pages,setup:installed?{installed:true,required:false}:cachedSetupStatus(),setup_install:installState,
      settings:value.settings||{...saved,ui_locked:!!protectedLive.length,instructions_locked:!!protectedLive.length,heartbeat_locked:protectedLive.some(t=>['active','awaiting_extension','verified_waiting'].includes(t.status))},mascot:mascotState(value)};
  }
  async function ensureFullAccess(agentOrId) {
    const resolved=typeof agentOrId==='string'?await ctx.sessionController.resolveAgent(agentOrId):{agent:agentOrId};
    if(resolved.error)throw resolved.error;
    const agent=resolved.agent;
    attachTaskContext(agent);
    if(!agent?.session)throw new Error('无法恢复监工会话以配置完全访问权限');
    if(ctx.permissionPresets.current(agent.session)!=='danger-full-access')permissionRepairs[agent.session.id]=(permissionRepairs[agent.session.id]||0)+1;
    ctx.permissionPresets.apply(agent.session,'danger-full-access',policy=>ctx.approval.setPolicy(agent,policy));
    sessionPermissions[agent.session.id]=ctx.permissionPresets.current(agent.session);
    if(sessionPermissions[agent.session.id]!=='danger-full-access')throw new Error('监工会话完全访问权限未生效');
  }
  async function wake() {
    // First Windows task launch includes Task Scheduler/PowerShell and cold
    // Python imports. Count elapsed startup time, not fast connection refusals.
    const deadline=Date.now()+30000;
    while(Date.now()<deadline) {
      try { if(!(await request('/ensure',{},Math.max(1,deadline-Date.now()))).shutting_down)return; }
      catch(error) {
        if(!['ENOENT','ECONNREFUSED','ECONNRESET','EPIPE'].includes(error.code))throw error;
        if(!config.windowsTask && config.socketPath && config.socketPath!=='/run/dafeiyu/agent.sock')throw error;
      }
      // A start while the old process is exiting can be a no-op. Keep using the
      // installed starter until the new service actually accepts admission.
      if(config.windowsStarter)await run('schtasks',['/Run','/TN',config.windowsStarter],{timeout:20000});
      else if(config.windowsTask){await run('schtasks',['/Change','/TN',config.windowsTask,'/ENABLE'],{timeout:20000});await run('schtasks',['/Run','/TN',config.windowsTask],{timeout:20000});}
      else await run('sudo',['-n','/usr/local/sbin/dafeiyu-start'],{timeout:20000});
      await new Promise(r=>setTimeout(r,150));
    }
    throw new Error('监工服务未能接收任务；请检查后台服务启动日志');
  }
  function tool(name,description,parameters,execute) {
    ctx.tools.register(defineTool({name,description,parameters,
      async execute(args,exec) {
        attachTaskContext(exec.agent);
        if(!READ_ONLY_TOOLS.includes(name))await ensureFullAccess(exec.agent);
        const value=compactResult(name,await execute({...args},exec),args);
        let attachment;
        if(value?._image_base64) {
          attachment=await ctx.attachments.saveImage({data:Buffer.from(value._image_base64,'base64'),mediaType:'image/jpeg',name:'监工桌面证据'});
          delete value._image_base64;
        }
        if(value&&typeof value==='object'&&typeof value._text==='string'){const text=value._text;delete value._text;return {text,...(attachment?{attachment}:{})};}
        return {report:value,...(attachment?{attachment}:{})};
      },output:{schema:{type:'object',additionalProperties:true},render:(_args,v)=>[{type:'text',text:v.text??JSON.stringify(v.report)},...(v.attachment?[{type:'image',attachment:v.attachment}]:[])]}
    }));
  }
  const session = exec => exec.agent.session.id;
  // The model reads the full document only through focus_help; status replies stay small.
  tool('focus_status','查看监工任务、采集状态与待处理报告；不唤醒空闲服务。detail=full 返回完整状态，默认紧凑事实。',{detail:{type:'string',enum:['compact','full']}},async(a,e)=>{const value=await state();delete value.delivery_errors;return {...value,delivery_error:deliveryErrors.get(session(e))??null};});
  tool('focus_help','读取大肥鱼监工的完整使用说明与 API 文档：每个 focus_* 接口的使用时机、参数、示例与限制。在用户确定要被监督、准备创建任务，或需要核对某个接口的准确用法时调用；不读取文档就不要直接创建任务。',{},()=>({_text:'大肥鱼监工 · 完整使用说明（全局设置，可用 focus_settings 修改；创建任务前请先读本说明）\n\n'+(configuredPrompts().instructions_full||defaults.instructions_full)}));
  tool('focus_plan','将已在本会话协商确定的任务挂上独立监工服务，并开启有任务期间的系统自启动。首次使用或不确定参数时先调用 focus_help 阅读完整说明。',agreement,async(a,e)=>{ dates(a); await ensureFullAccess(e.agent); await wake();return {...await request('/plan',{...a,task_id:'task_'+createHash('sha256').update(session(e)+':'+e.callId).digest('hex').slice(0,24),session_id:session(e)}),desktop_setup:await desktopStatus()};});
  tool('focus_revise','讨论后修订本会话的任务约定或延期；记录实际理由。',{...agreement,task_prompt:str('任务附加提示词；省略保留当前值',false),project_dir:str('旧任务补充项目目录；已有目录不迁移',false),task_id:str('任务编号'),reason:str('讨论与修订理由')},(a,e)=>request('/revise',{...dates(a),session_id:session(e)}));
  tool('focus_finish','根据约定和实际审核结果结束本会话任务，并记录判断依据。',{task_id:str('任务编号'),verdict:{type:'string',required:true,enum:['completed','cancelled','not_completed']},reason:str('实际审核证据、讨论结论或取消理由')},(a,e)=>request('/finish',{...a,session_id:session(e)}));
  tool('focus_check','获取此任务当前待处理报告，或立即创建检查报告（整屏直接返回）。',{task_id:str('任务编号'),detail:{type:'string',enum:['compact','full']}},(a,e)=>{const {detail,...requestArgs}=a;return request('/check',{...requestArgs,session_id:session(e)});});
  tool('focus_report','按需阅读冻结报告中的程序分支、文本、日志或单窗口截图。',{report_id:str('报告编号'),operation:{type:'string',required:true,enum:['get_overview','read_activity_changes','list_programs','read_program_report','inspect_evidence','read_evidence_text','view_screenshot','verify_files']},arguments_json:str('对应取证参数 JSON；program_id、reference、references、offset 等',false)},a=>request('/report',{...a,arguments:JSON.parse(a.arguments_json||'{}')}));
  tool('focus_observe','记录本轮观察结论，不执行提醒或关闭。',{report_id:str('报告编号'),decision:{type:'string',required:true,enum:['on_task','uncertain','suspect','returned','off_task']},presence:{type:'string',enum:['away','present','unknown'],description:'记录你观察到的情况，仅作证据，不触发待机（待机由插件按真实输入活动自动判定）；默认 unknown'},reason:str('证据、用户解释与本次判断'),target_ref:str('相关窗口证据编号',false)},(a,e)=>request('/observe',{...a,session_id:session(e)}));
  tool('focus_act','统一执行提醒或窗口动作，由你根据情境选择。动手前应先用 focus_check 获取最新窗口数据，并用它的 report_id 与 target_ref。minimize_window 把目标窗口最小化（只要求它尚未最小化；不结束进程、不丢数据，门禁与强杀一致）；force_close 按 target_kind 关闭进程、窗口或浏览器标签；精细关闭失败会结束相关进程树，目标已不在时视为已关闭，可能丢失未保存内容，仅作为持续分心的最后手段。remind 自动同时弹窗、提示音和系统通知；返回各通道的实际结果。',{task_id:str('任务编号'),action:{type:'string',required:true,enum:['remind','minimize_window','force_close']},target_kind:{type:'string',enum:['process','window','browser_tab'],description:'force_close 的目标类型，默认 process；精细关闭失败会升级结束相关进程'},message:str('要对用户说的话；remind 必填',false),image:{type:'string',enum:['question','gentle','warning','urgent','start','celebrate','sleep','scheduled','watching','checking']},report_id:str('窗口动作所依据的新报告',false),target_ref:str('报告中的窗口证据编号',false)},(a,e)=>request('/act',{...a,chat_url:`http://127.0.0.1:${ctx.webServer.port}/focus/open?session=${encodeURIComponent(session(e))}`,chat_registry:chatRegistry,session_id:session(e),action_id:createHash('sha256').update(session(e)+':'+e.callId).digest('hex')}));
  tool('focus_settings','读取设置，或修改提示词和形象大小。防任务中修改模式默认关闭，关闭时允许任务期间修改；开启时插件说明仅无任务可改、全局心跳仅无进行中任务可改，任务附加提示词仍在原会话修改。',{operation:{type:'string',required:true,enum:['get','update']},task_id:str('修改 task_prompt 时填写任务编号',false),patch_json:str('JSON 对象，可含 protect_task_changes（布尔值，默认false）、instructions、instructions_full、heartbeat_prompt、task_prompt、mascot_size、sampling（采集间隔、图片尺寸与正文/日志上限）、reporting（摘要及分页长度）；两组支持局部更新。away_heartbeats（连续无输入心跳上限，2–10）',false)},async(a,e)=>{if(a.operation==='get')return (await state()).settings||configuredPrompts();await wake();const result=await request('/settings/ai',{task_id:a.task_id,patch:JSON.parse(a.patch_json||'{}'),session_id:session(e)});return result;});
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/setup',async handler(req,res){
    const local=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    const send=(code,value)=>{res.writeHead(code,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value));};
    if(req.method!=='POST'||!local||req.headers['x-focus-token']!==uiToken)return send(403,{error:'需要本机页面令牌'});
    if(installState&&installState.state==='running')return send(200,{state:'running',started_at:installState.started_at});
    const payload=payloadStatus();
    if(!payload.present)return send(400,{error:'随包后端安装脚本不存在：'+(payload.reason||'缺少 backend/ 目录')});
    if(!payload.verified)return send(400,{error:'随包后端安装脚本校验失败（摘要与清单不一致），已拒绝提权'});
    const plan=elevationPlan();
    installState={state:'running',started_at:Date.now(),mode:plan.mode,command:plan.command,output:''};
    send(200,{state:'running',mode:plan.mode,command:plan.command});
    const result=await runInstall(plan);
    if(result.ok && windowsAutoConfig) {
      config=await installedWindowsConfig(config,windowsConfigPath);
      stateDirectory=config.stateDirectory||stateDirectory;
    }
    setupCache=null;setupCheckedAt=0;
    installState={state:result.ok?'ok':(result.cancelled?'cancelled':(result.manual?'manual':'failed')),started_at:installState.started_at,
      finished_at:Date.now(),mode:plan.mode,command:plan.command,output:result.output||'',code:result.code??null};
  }}));
  for(const asset of ['sleep','scheduled','watching','checking','start','celebrate','warning','question','gentle','urgent']) {
    ctx.effect(()=>ctx.webServer.register({kind:'exact',path:`/focus/mascot/${asset}.png`,async handler(req,res){
      try { const image=await readFile(new URL(`./assets/${asset}.png`,import.meta.url)); res.writeHead(200,{'content-type':'image/png','cache-control':'public, max-age=3600'});res.end(image); }
      catch {res.writeHead(404);res.end();}
    }}));
  }
  ctx.on('webserver/index-inject',table=>table.push({kind:'global',name:'__DAFEIYU__',value:{token:uiToken,samplingSchema}}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/status',async handler(req,res){
    const local=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    if(req.method!=='GET'||!local||req.headers['x-focus-token']!==uiToken){res.writeHead(403);res.end();return;}
    // Any page that reads the status is a page the reminder can switch instead of opening one.
    lastStatusPollAt=Date.now();notePage(req);
    try{res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(await state()));}
    catch(e){res.end(JSON.stringify({error:e.message}));}
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/finish',async handler(req,res){
    const local=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    if(req.method!=='POST'||!local||req.headers['x-focus-token']!==uiToken){res.writeHead(403);res.end();return;}
    try{let body='';for await(const chunk of req)body+=chunk;
      const {task_id}=JSON.parse(body);await wake();const task=await request('/finish/ui',{task_id});
      res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify({task}));
    }catch(e){res.writeHead(400,{'content-type':'application/json'});res.end(JSON.stringify({error:e.message}));}
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/settings',async handler(req,res){
    const local=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    if(req.method!=='POST'||!local||req.headers['x-focus-token']!==uiToken){res.writeHead(403);res.end();return;}
    try{let body='';for await(const chunk of req){body+=chunk;if(body.length>100000)throw Error('设置内容过长');}
      const input=JSON.parse(body);
      // Resetting restores the prompts shipped with this plugin package; a saved
      // custom value still wins on later writes.
      const patch=input?.resetSampling?samplingDefaults:input?.reset?{instructions:defaults.instructions,instructions_full:defaults.instructions_full,heartbeat_prompt:defaults.heartbeat_prompt}:(input?.patch??input);
      await wake();const result=await request('/settings/ui',{patch});
      res.writeHead(200,{'content-type':'application/json'});res.end(JSON.stringify(result));
    }catch(e){res.writeHead(400,{'content-type':'application/json'});res.end(JSON.stringify({error:e.message}));}
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/open',async handler(req,res){
    if(req.method!=='GET'||!['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress)){res.writeHead(403);res.end();return;}
    const sessionId=new URL(req.url,'http://localhost').searchParams.get('session');
    const focus=await focusTask(sessionId);
    if(!focus){res.writeHead(404);res.end('监工会话不存在');return;}
    // DSH's page is always the bare root (`/`): which Session is on screen is page state
    // owned by uiWorkspace.openSession(), never part of the URL. So this link carries no
    // session parameter at all. It arms a handoff, then lands on the real root; the page
    // that loads there claims the handoff and switches itself to the supervision Session.
    // This also keeps Chrome's tab reuse working, since the landing URL is the same one
    // every DSH tab already shows.
    const requestId=new URL(req.url,'http://localhost').searchParams.get('request');
    if(requestId){
      if(pendingOpen?.id!==requestId||pendingOpen.finished||pendingOpen.expires_at<Date.now()){res.writeHead(409);res.end('本次唤回已结束或被替代');return;}
      pendingOpen.expires_at=Date.now()+OPEN_DEEP_LINK_TTL_MS;
    }
    // Create a new handoff only after this landing document has replaced the
    // previous page. Its still-running long poll must not claim during navigation.
    // connection.authenticatedUrl() keeps only this process's launch token, and DSH's own
    // index hop exchanges it for a cookie and 303s to a clean `/`.
    const home=`http://127.0.0.1:${ctx.webServer.port}/`;
    const authenticate=JSON.stringify(ctx.connection.authenticatedUrl(home));
    res.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-store','referrer-policy':'no-referrer'});
    // Navigating on a failed authentication hop lands on DSH's minimal 401 page, i.e. a
    // blank tab. Verify the hop, retry briefly, and leave the user a visible way in.
    res.end('<!doctype html><meta charset="utf-8"><title>正在打开监工会话…</title>'
      +'<body style="font:14px system-ui,sans-serif;padding:24px;color:#3F4B6E">正在打开监工会话…'
      +'<p id="dafeiyu-hint" style="color:#7C89AC;font-size:12px"></p>'
      +'<p style="font-size:12px"><a id="dafeiyu-link" style="color:#5A67B8">点这里手动打开</a></p>'
      +'<script>var auth='+authenticate+',tries=0;var handoff='+
        (requestId?'Promise.resolve()':"fetch('/focus/open-request',{method:'POST',headers:{'content-type':'application/json'},body:"+JSON.stringify(JSON.stringify({session:sessionId}))+"}).then(function(r){if(!r.ok)throw new Error('会话唤回请求失败');return r.json();})")+';'
      +'function dafeiyuGo(){handoff.then(function(){return fetch(auth,{credentials:"same-origin",redirect:"follow",cache:"no-store"});}).then(function(r){'
      +'if(!r.ok)throw new Error("认证失败 "+r.status);location.replace(auth);'
      +'}).catch(function(error){tries+=1;if(tries<3){setTimeout(dafeiyuGo,400);return;}'
      +'document.getElementById("dafeiyu-hint").textContent="自动打开失败："+error.message+"；可点下面的链接。";'
      +'document.getElementById("dafeiyu-link").href=auth;});}dafeiyuGo();</script>');
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/open-request',async handler(req,res){
    if(!['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress)){res.writeHead(403);res.end();return;}
    const send=(code,value)=>{res.writeHead(code,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value));};
    if(req.method==='GET'){
      const id=new URL(req.url,'http://localhost').searchParams.get('id');
      const known=pendingOpen&&pendingOpen.id===id&&pendingOpen.expires_at>=Date.now();
      return send(200,{replaced:!!pendingOpen&&pendingOpen.id!==id,claimed:!!known&&pendingOpen.claimed,completed:!!known&&pendingOpen.completed,session_ready:!!known&&pendingOpen.session_ready,status:known?pendingOpen.status:null,marker:known?pendingOpen.marker:null,error:known?pendingOpen.error:null,expired:!known});
    }
    if(req.method!=='POST')return send(403,{error:'需要 POST'});
    try{
      let body='';for await(const chunk of req){body+=chunk;if(body.length>10000)throw Error('请求内容过长');}
      const sessionId=String(JSON.parse(body||'{}').session||'');
      const focus=await focusTask(sessionId);
      if(!focus)return send(404,{error:'监工会话不存在'});
      // The popup waits for explicit navigation completion before activating its tab.
      createOpenRequest(sessionId,focus.project_dir,OPEN_REQUEST_TTL_MS);
      return send(200,{id:pendingOpen.id,open_page:lastOpenRequest.open_page});
    }catch(e){return send(400,{error:e.message});}
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/claim-wait',async handler(req,res){
    const local=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    if(req.method!=='GET'||!local||req.headers['x-focus-token']!==uiToken){res.writeHead(403);res.end();return;}
    notePage(req);
    const send=value=>{try{res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value));}catch{}};
    const page=String(req.headers['x-focus-page']||'legacy');
    if(pendingOpen&&!pendingOpen.claimed&&pendingOpen.expires_at>Date.now())
      return send({id:pendingOpen.id,session:pendingOpen.session,project_dir:pendingOpen.project_dir});
    const old=claimWaiters.get(page);if(old){clearTimeout(old.timer);old.send({});}
    const waiter={send,closed:()=>res.destroyed||res.writableEnded,timer:null};
    waiter.timer=setTimeout(()=>{if(claimWaiters.get(page)===waiter)claimWaiters.delete(page);send({});},CLAIM_WAIT_HOLD_MS);
    claimWaiters.set(page,waiter);
    res.on?.('close',()=>{clearTimeout(waiter.timer);if(claimWaiters.get(page)===waiter)claimWaiters.delete(page);});
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/open-claim',async handler(req,res){
    const local=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    if(req.method!=='POST'||!local||req.headers['x-focus-token']!==uiToken){res.writeHead(403);res.end();return;}
    notePage(req);
    res.writeHead(200,{'content-type':'application/json','cache-control':'no-store'});
    // A waiting request is handed to exactly one page, so with several tabs open the
    // first one to ask switches and the others are left alone.
    let body='';for await(const chunk of req){body+=chunk;if(body.length>2000){res.end('{}');return;}}
    let offered;try{offered=JSON.parse(body||'{}').id;}catch{res.end('{}');return;}
    if(offered&&pendingOpen?.id!==offered){res.end('{}');return;}
    res.end(JSON.stringify(takePendingForClaim(String(req.headers['x-focus-page']||'legacy'))||{}));
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/open-complete',async handler(req,res){
    if(req.method!=='POST'||!['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress)||req.headers['x-focus-token']!==uiToken){res.writeHead(403);res.end();return;}
    let body='';for await(const chunk of req){body+=chunk;if(body.length>2000){res.writeHead(400);res.end();return;}}
    let data;try{data=JSON.parse(body);}catch{res.writeHead(400);res.end();return;}
    const valid=pendingOpen&&pendingOpen.id===data.id&&pendingOpen.page===String(req.headers['x-focus-page']||'legacy')&&!pendingOpen.finished&&!pendingOpen.session_ready&&pendingOpen.expires_at>Date.now();
    if(valid){pendingOpen.session_ready=!data.error;pendingOpen.status=data.error?'failed':'session_ready';pendingOpen.error=data.error?String(data.error).slice(0,240):null;pendingOpen.marker='[DSH-'+pendingOpen.id+']';lastOpenRequest.session_ready_at=Date.now();lastOpenRequest.status=pendingOpen.status;lastOpenRequest.error=pendingOpen.error;}
    res.writeHead(valid?200:409,{'content-type':'application/json'});res.end(JSON.stringify({session_ready:!!valid&&!data.error}));
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/open-result',async handler(req,res){
    const local=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    if(req.method!=='POST'||!local){res.writeHead(403);res.end();return;}
    let body='';for await(const chunk of req){body+=chunk;if(body.length>10000){res.writeHead(400);res.end();return;}}
    let data;try{data=JSON.parse(body);}catch{res.writeHead(400);res.end();return;}
    const valid=pendingOpen?.id===data.id&&pendingOpen.expires_at>Date.now()&&!pendingOpen.finished;
    if(valid){
      pendingOpen.finished=true;pendingOpen.completed=!!data.raised;pendingOpen.status=data.raised?'completed':'failed';pendingOpen.error=data.raised?null:String(data.reason||'窗口恢复失败');
      Object.assign(lastOpenRequest,{status:pendingOpen.status,completed_at:Date.now(),desktop_result:data});
      const waiter=claimWaiters.get(pendingOpen.page);
      if(waiter){claimWaiters.delete(pendingOpen.page);clearTimeout(waiter.timer);waiter.send({finished:pendingOpen.id});}
    }
    res.writeHead(valid?200:409,{'content-type':'application/json'});res.end(JSON.stringify({completed:!!valid&&pendingOpen.completed}));
  }}));
  ctx.effect(()=>ctx.webServer.register({kind:'exact',path:'/focus/open-release',async handler(req,res){
    const local=['127.0.0.1','::1','::ffff:127.0.0.1'].includes(req.socket.remoteAddress);
    if(req.method!=='POST'||!local||req.headers['x-focus-token']!==uiToken){res.writeHead(403);res.end();return;}
    const send=(code,value)=>{res.writeHead(code,{'content-type':'application/json','cache-control':'no-store'});res.end(JSON.stringify(value));};
    try{
      let body='';for await(const chunk of req){body+=chunk;if(body.length>2000)throw Error('请求内容过长');}
      const id=String(JSON.parse(body||'{}').id||'');
      // A page that claimed a request but could not open the session gives it back, so the
      // waiting popup can still fall back to opening a browser instead of doing nothing.
      if(pendingOpen&&pendingOpen.id===id&&pendingOpen.expires_at>=Date.now()&&!pendingOpen.finished&&!pendingOpen.session_ready){
        pendingOpen.claimed=false;
        if(lastOpenRequest)lastOpenRequest.released_at=Date.now();
        return send(200,{released:true});
      }
      return send(200,{released:false});
    }catch(e){return send(400,{error:e.message});}
  }}));
  async function poll() {
    if(disposed||polling)return; polling=true;
    try{
      await registerChatEndpoint();
      let current=await rawState();pollError=null;
      if(!current.running && (current.live||[]).length){await wake();current=await rawState();}
      for(const item of current.notices||[]){
        if(deliveredNotices.has(item.id)||Date.now()-(attempts.get(item.id)||0)<30000)continue;
        attempts.set(item.id,Date.now());
        try {
          await ensureFullAccess(item.session_id);
          const result=await ctx.sessionController.prompt({requestId:item.id,sessionId:item.session_id,mode:'queue',content:[{type:'text',text:`[大肥鱼任务状态：${item.kind}]\n任务：${item.agreement}\n${item.message}\n任务编号：${item.task_id}。这是程序记录的状态事件，不代表任务成果已经验收通过。`}],clientTimeZone:'Asia/Shanghai'},AbortSignal.any([lifetime.signal,AbortSignal.timeout(30000)]));
          if(!result.accepted)throw new Error(JSON.stringify(result));
          await rememberNotice(item.id);attempts.delete(item.id);deliveryErrors.delete(item.session_id);
        } catch(error) { deliveryErrors.set(item.session_id,error.message); }
      }
      if(!current.running)return;
      if((current.live||[]).length)await request('/ensure');
      for(const sessionId of new Set((current.live||[]).map(task=>task.session_id))){
        try{await ensureFullAccess(sessionId);}catch(error){deliveryErrors.set(sessionId,error.message);}
      }
      const due=await request('/due');
      for(const item of due) {
        if(disposed)break;
        if(Date.now()-(attempts.get(item.id)||0)<30000)continue;
        attempts.set(item.id,Date.now());
        try {
          const data=await request('/report',{report_id:item.id,operation:'get_overview'});
          const image=data._image_base64; delete data._image_base64;
          const content=[{type:'text',text:formatReport(data)}];
          if(image)content.push({type:'image',mediaType:'image/jpeg',data:image,name:'当前整屏'});
          const result=await ctx.sessionController.prompt({requestId:item.request_id,sessionId:item.session_id,mode:'queue',content,clientTimeZone:'Asia/Shanghai'},AbortSignal.any([lifetime.signal,AbortSignal.timeout(30000)]));
          if(!result.accepted)throw new Error(JSON.stringify(result));
          await request('/delivered',{report_id:item.id});
          attempts.delete(item.id);deliveryErrors.delete(item.session_id);
        }catch(error){deliveryErrors.set(item.session_id,error.message);}
      }
    }catch(e){if(!['ENOENT','ECONNREFUSED'].includes(e.code))pollError=e.message;}finally{polling=false;}
  }
  const timer=setInterval(()=>void poll(),5000);
  ctx.effect(()=>()=>{disposed=true;lifetime.abort();clearInterval(timer);for(const w of claimWaiters.values()){clearTimeout(w.timer);w.send({});}claimWaiters.clear();});
  void poll();
  console.info('[focus-supervisor] chat tools and floating-ball status ready');
}
