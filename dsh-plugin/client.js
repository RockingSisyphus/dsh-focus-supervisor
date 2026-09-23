window.__ModuleLoader__.load({
 id:'dsh-focus-supervisor',factory:(require)=>{
  const React=require('react'),h=React.createElement;
  // Blue-pink pastel palette shared with the native reminder popups.
  const CUTE={ink:'#3F4B6E',sub:'#7C89AC',faint:'#A9B4D0',line:'#E7EEFA',
   pink:'#FF9EC4',pinkSoft:'#FFE7F2',pinkDeep:'#F27CAE',blue:'#8FC6FF',blueSoft:'#E6F2FF',blueDeep:'#5FA8EE',
   card:'#FFFFFF',mint:'#6FD3B0',amber:'#E9A23B',rose:'#D9615C',
   gradient:'linear-gradient(150deg,#FFE9F4 0%,#F7F2FF 46%,#E8F3FF 100%)',
   buttonGradient:'linear-gradient(135deg,#FFA7CB 0%,#9CCBFF 100%)',
   shadow:'0 22px 60px rgba(122,142,196,.28)'};
  const font='"PingFang SC","Microsoft YaHei UI","Noto Sans CJK SC",system-ui,-apple-system,sans-serif';
  function CuteButton(props){
   const {label,onClick,disabled,tone='primary',style,ariaLabel,expanded,title,attrs}=props;
   const [hover,setHover]=React.useState(false);
   const base={border:0,borderRadius:14,padding:'9px 14px',cursor:disabled?'not-allowed':'pointer',font:'inherit',fontSize:13,fontWeight:600,
    transition:'transform .12s ease, box-shadow .12s ease',opacity:disabled?.55:1,transform:hover&&!disabled?'translateY(-1px)':'none'};
   const tones={primary:{background:CUTE.buttonGradient,color:'#FFFFFF',boxShadow:hover&&!disabled?'0 10px 22px rgba(150,170,220,.42)':'0 6px 16px rgba(150,170,220,.34)'},
    soft:{background:CUTE.card,color:CUTE.blueDeep,border:'1px solid '+CUTE.line,boxShadow:hover&&!disabled?'0 8px 18px rgba(150,170,220,.22)':'none'},
    ghost:{background:'rgba(255,255,255,.72)',color:CUTE.sub,border:'1px solid rgba(255,255,255,.9)'},
    pink:{background:CUTE.pinkSoft,color:CUTE.pinkDeep,border:'1px solid #FFD6E7'}};
   return h('button',{'aria-label':ariaLabel,title,disabled,'aria-expanded':expanded,onClick,
    onMouseEnter:()=>setHover(true),onMouseLeave:()=>setHover(false),style:{...base,...tones[tone],...style},...(attrs||{})},label);
  }
  return {inject:['slots','uiWorkspace'],apply(ctx){
   // Every page identifies itself and reports whether the user can actually see it. A
   // handoff taken by a hidden page switches a tab nobody is looking at, which looks
   // exactly like "the click did nothing", so the plugin has to be able to tell pages
   // apart instead of guessing.
   const pageId=(globalThis.crypto&&globalThis.crypto.randomUUID)?globalThis.crypto.randomUUID().slice(0,8):Math.random().toString(16).slice(2,10);
   const pageVisible=()=>{try{return document.visibilityState==='visible';}catch{return true;}};
   const pageHeaders=()=>({'x-focus-token':globalThis.__DAFEIYU__?.token||'','x-focus-page':pageId,'x-focus-visible':pageVisible()?'1':'0'});
   // A restored tab keeps the previous plugin process's token. Renew it from DSH's current
   // same-origin HTML without reloading the chat or evaluating scripts.
   async function renewToken(signal){
     const index=await fetch('/',{signal,cache:'no-store'});
     if(!index.ok)throw Error('DSH 登录已失效，请重新登录后重试。');
     const html=await index.text();
     const match=html.match(/globalThis\["__DAFEIYU__"\]\s*=\s*(\{[^<]*?\})\s*<\/script>/);
     if(!match)throw Error('监工插件尚未就绪，正在重连。');
     const bootstrap=JSON.parse(match[1]);
     if(typeof bootstrap.token!=='string')throw Error('监工连接信息不可用，正在重试。');
     globalThis.__DAFEIYU__=bootstrap;
   }
   // How the Session on screen can be observed depends on the DSH version, and claiming a
   // switch that never happened is worse than admitting we cannot check it. 0.1.6 moved the
   // view selection out of the Session Controller, so list.current is gone; what the UI itself
   // reads there is whether the main view retains the Session (retainedBy.mainView).
   function sessionWatchers(sessions,sessionId){
     const retained=()=>{
       try{
         const info=sessions?.retainInfo?.(sessionId);
         const snapshot=typeof info?.getSnapshot==='function'?info.getSnapshot():info;
         return (snapshot?.retainedBy?.mainView??0)>0;
       }catch{return false;}
     };
     // The same fact also reaches the list rows, and the UI's own fallback is to look for the
     // row the main view keeps (dsh-client-ui-session/client.js:283).
     const listedMainView=()=>{
       try{
         const rows=sessions?.list?.getSnapshot?.()?.byId;
         if(!rows)return false;
         return Object.values(rows).some((row)=>(row?.retainedBy?.mainView??0)>0&&row.id===sessionId);
       }catch{return false;}
     };
     const listedCurrent=()=>{
       try{return sessions?.list?.getSnapshot?.()?.current===sessionId;}catch{return false;}
     };
     // What was actually observed goes into the failure the page reports back, so a failed
     // switch can be diagnosed from the supervisor log alone.
     const observed=()=>{
       let retention='n/a',mainView='n/a',current='n/a';
       try{retention=JSON.stringify(sessions?.retainInfo?.(sessionId)?.getSnapshot?.()?.retainedBy??null);}catch{}
       try{
         const snapshot=sessions?.list?.getSnapshot?.()??{};
         mainView=Object.values(snapshot.byId||{}).filter((row)=>(row?.retainedBy?.mainView??0)>0).map((row)=>row.id).join(',')||'none';
         current=String(snapshot.current);
       }catch{}
       return `retain=${retention} mainView=${mainView} current=${current}`;
     };
     const watchers=[];
     if(typeof sessions?.retainInfo==='function')watchers.push(['main-view-retention',retained]);
     if(typeof sessions?.list?.getSnapshot==='function'){
       watchers.push(['list-main-view',listedMainView],['list-current',listedCurrent]);
     }
     return {watchers,titles:watchers.map(([title])=>title),observed};
   }
   async function focusSession(sessionId){
     const sessions=ctx.get('sessions');
     ctx.uiWorkspace.openSession(sessionId);
     const {watchers,titles,observed}=sessionWatchers(sessions,sessionId);
     // A profile that exposes neither signal cannot be observed: the selection stands on its
     // own instead of being reported as a failure we never measured.
     if(typeof globalThis!=='undefined')globalThis.__DAFEIYU__={...(globalThis.__DAFEIYU__||{}),switchVerifiers:titles};
     if(!watchers.length)return;
     // Connecting a Workspace loads its Sessions from the host, so the selection may lag.
     for(let attempt=0;attempt<30;attempt++){
       if(watchers.some(([,watch])=>watch()))return;
       await new Promise(resolve=>setTimeout(resolve,150));
     }
     let seen='';
     try{seen=observed();}catch{}
     throw Error(`DSH 未切换到指定监工会话（判据 ${titles.join('/')}；观测 ${seen}）`);
   }
   function Ball(){
    // DSH's URL is always the bare root; the Session on screen is page state. A reminder
    // therefore never arrives as a URL parameter: it arrives over the handoff channel and
    // is switched in place by takeSwitch() below.
    const [open,setOpen]=React.useState(false),[state,setState]=React.useState(null),[error,setError]=React.useState('');
    const [size,setSize]=React.useState(144),[settingsOpen,setSettingsOpen]=React.useState(false),[draft,setDraft]=React.useState(null),[saving,setSaving]=React.useState(false),[saveMessage,setSaveMessage]=React.useState(''),[popup,setPopup]=React.useState(null),[setupMessage,setSetupMessage]=React.useState(''),[setupBusy,setSetupBusy]=React.useState(false);
    const storage='dafeiyu-mascot-position-v1';
    const clamp=(p)=>({x:Math.max(4,Math.min(innerWidth-size-4,p.x)),y:Math.max(4,Math.min(innerHeight-size-4,p.y))});
    const [position,setPosition]=React.useState(()=>{try{const p=JSON.parse(localStorage.getItem(storage));if(Number.isFinite(p?.x)&&Number.isFinite(p?.y))return clamp(p);}catch{}return clamp({x:innerWidth-size-24,y:innerHeight-size-26});});
    const [notice,setNotice]=React.useState(null),[viewport,setViewport]=React.useState({width:innerWidth,height:innerHeight});
    const drag=React.useRef(null),skipClick=React.useRef(false),noticeTimer=React.useRef(null);
    const seen=React.useRef(null);
    if(!seen.current){try{seen.current=new Set(JSON.parse(localStorage.getItem('dafeiyu-mascot-seen')||'[]'));}catch{seen.current=new Set();}}
    React.useEffect(()=>{const resize=()=>{setViewport({width:innerWidth,height:innerHeight});setPosition(p=>clamp(p));};addEventListener('resize',resize);return()=>{removeEventListener('resize',resize);clearTimeout(noticeTimer.current);};},[size]);
    React.useEffect(()=>{setPosition(p=>clamp(p));},[size]);
    React.useEffect(()=>{const fresh=(state?.mascot?.notices||[]).filter(n=>!seen.current.has(n.id));if(!fresh.length)return;
      for(const n of fresh)seen.current.add(n.id);
      try{localStorage.setItem('dafeiyu-mascot-seen',JSON.stringify([...seen.current].slice(-200)));}catch{}
      const selected=fresh.at(-1);setNotice(selected);
      if(selected.popup&&!selected.delivery?.popup)setPopup(selected);
      clearTimeout(noticeTimer.current);noticeTimer.current=setTimeout(()=>setNotice(null),12000);
    },[state]);
    React.useEffect(()=>{if(state?.settings){const value=state.settings;setDraft({instructions:value.instructions,instructions_full:value.instructions_full,heartbeat_prompt:value.heartbeat_prompt,strict_heartbeat_prompt:value.strict_heartbeat_prompt,mascot_size:value.mascot_size,away_heartbeats:value.away_heartbeats??3,sampling:value.sampling,reporting:value.reporting});setSize(value.mascot_size);}},[state?.settings?.strict_heartbeat_prompt,state?.settings?.instructions,state?.settings?.instructions_full,state?.settings?.heartbeat_prompt,state?.settings?.mascot_size,state?.settings?.away_heartbeats,JSON.stringify(state?.settings?.sampling),JSON.stringify(state?.settings?.reporting)]);
    function samplingFields(){
      const schema=globalThis.__DAFEIYU__?.samplingSchema||{};
      return Object.entries(schema).map(([group,fields])=>h('details',{key:group,style:{marginTop:12}},
        h('summary',null,group==='sampling'?'采集设置':'模型输出'),
        h('p',{style:{fontSize:12}},group==='sampling'?'周期不是严格限流：窗口变化可能提前刷新；降频可能漏掉短时活动。':'仅控制插件摘要及分页，不限制模型工具次数或DSH文件读取。'),
        ...Object.entries(fields).map(([key,spec])=>h('label',{key,style:labelStyle},`${spec.label}（${spec.unit}；默认 ${spec.default??'不限'}）`,h('small',{style:{display:'block',fontWeight:'normal'}},spec.description),
          spec.nullable&&h('input',{type:'checkbox','aria-label':spec.label+'不限',checked:draft[group]?.[key]===null,disabled:state?.settings?.ui_locked||saving,onChange:e=>setDraft(d=>({...d,[group]:{...d[group],[key]:e.target.checked?null:1}}))}),
          h('input',{type:'number',step:spec.integer?1:'any','aria-label':spec.label,value:draft[group]?.[key]??'',disabled:state?.settings?.ui_locked||saving||(spec.nullable&&draft[group]?.[key]===null),style:fieldStyle,
            onChange:e=>{const value=e.target.value;setDraft(d=>({...d,[group]:{...d[group],[key]:value===''?'':Number(value)}}));}}))),
        h('button',{type:'button',disabled:state?.settings?.ui_locked||saving,onClick:()=>setDraft(d=>({...d,[group]:Object.fromEntries(Object.entries(fields).map(([key,spec])=>[key,spec.default]))}))},'恢复本组默认值')));
    }
    async function saveSettings(){setSaving(true);setSaveMessage('');try{
      const r=await fetch('/focus/settings',{method:'POST',headers:{'content-type':'application/json','x-focus-token':globalThis.__DAFEIYU__?.token||''},body:JSON.stringify(draft)});
      const result=await r.json();if(!r.ok||result.error)throw Error(result.error||'保存失败');setState(s=>({...s,settings:result.settings}));setSaveMessage('设置已保存。');
    }catch(e){setSaveMessage(e.message);}finally{setSaving(false);}}
    async function resetSettings(){setSaving(true);setSaveMessage('');try{
      const r=await fetch('/focus/settings',{method:'POST',headers:{'content-type':'application/json','x-focus-token':globalThis.__DAFEIYU__?.token||''},body:JSON.stringify({reset:true})});
      const result=await r.json();if(!r.ok||result.error)throw Error(result.error||'重置失败');
      const value=result.settings||{};
      setState(s=>({...s,settings:value}));
      setDraft(d=>({...d,instructions:value.instructions??d.instructions,instructions_full:value.instructions_full??d.instructions_full,heartbeat_prompt:value.heartbeat_prompt??d.heartbeat_prompt,strict_heartbeat_prompt:value.strict_heartbeat_prompt??d.strict_heartbeat_prompt}));
      setSaveMessage('已重置为插件当前默认提示词；之后保存的自定义内容仍优先。');
    }catch(e){setSaveMessage(e.message);}finally{setSaving(false);}}
    async function startBackendInstall(){setSetupBusy(true);setSetupMessage('');try{
      const r=await fetch('/focus/setup',{method:'POST',headers:{'content-type':'application/json','x-focus-token':globalThis.__DAFEIYU__?.token||''},body:'{}'});
      const result=await r.json();if(!r.ok||result.error)throw Error(result.error||'安装请求失败');
      setSetupMessage(result.state==='running'?'已请求管理员授权：请在系统弹窗里输入密码（无弹窗时请用下面的命令手动执行）。':'等待授权…');
    }catch(e){setSetupMessage(e.message);}finally{setSetupBusy(false);}}
    async function copyInstallCommand(command){try{await navigator.clipboard.writeText(command);setSetupMessage('命令已复制，请到终端粘贴执行。');}catch{setSetupMessage('复制失败，请手动选中命令复制。');}}
    function endDrag(e){if(!drag.current)return;skipClick.current=drag.current.moved;drag.current=null;try{e.currentTarget.releasePointerCapture(e.pointerId);}catch{}setPosition(p=>{try{localStorage.setItem(storage,JSON.stringify(p));}catch{}return p;});}
    const kind=notice?.kind||state?.mascot?.kind||'sleep';
    const connectionLabel=error?'连接中断，正在重试':!state?'正在连接监工':null;
    const captions={sleep:'休息中',scheduled:'等你开工',watching:'陪你专注',checking:'正在检查',start:'开工啦',celebrate:'完成啦',warning:'回来专注啦',question:'想听听你的解释',gentle:'温和提醒',urgent:'请注意监工提醒'};
    const panelWidth=Math.min(360,viewport.width-24),availableAbove=position.y-12;
    const panelLeft=position.x>=panelWidth+16?position.x-panelWidth-12:position.x+size+panelWidth+16<=viewport.width?position.x+size+12:Math.max(12,Math.min(viewport.width-panelWidth-12,position.x+size-panelWidth));
    const beside=panelLeft+panelWidth<=position.x||panelLeft>=position.x+size;
    const desiredHeight=settingsOpen?Math.min(780,viewport.height-24):400;
    const panelStyle=beside?{top:Math.max(12,Math.min(position.y,viewport.height-desiredHeight)),maxHeight:Math.max(100,viewport.height-Math.max(12,Math.min(position.y,viewport.height-desiredHeight))-12)}:availableAbove>=160?{bottom:viewport.height-position.y+12,maxHeight:availableAbove-12}:{top:position.y+size+8,maxHeight:Math.max(80,viewport.height-position.y-size-20)};
    React.useEffect(()=>{let mounted=true;const controller=new AbortController();
     async function refresh(){try{
      const getStatus=()=>fetch('/focus/status',{headers:pageHeaders(),signal:controller.signal,cache:'no-store'});
      let r=await getStatus();
      if(r.status===403){await renewToken(controller.signal);r=await getStatus();}
      if(!r.ok)throw Error(`监工状态连接失败（${r.status}），正在重试。`);
      const s=await r.json();if(s.error)throw Error(s.error);
      if(!Array.isArray(s.live))throw Error('监工状态响应不完整，正在重试。');
      if(mounted){setState(s);setError('');}
      // A reminder popup hands its "back to the supervision chat" click to an already open
      // page instead of opening another tab. This quick claim covers the page polling right
      // now, so it stays with a page the user can see: a hidden page polling in the
      // background must not swallow a handoff that then happens where nobody is looking.
      // The held channel below is what reaches a page whose timers the browser throttles,
      // and there the plugin itself picks the page, preferring a visible one.
      try{
       if(pageVisible()){
        const claim=await fetch('/focus/open-claim',{method:'POST',headers:pageHeaders(),signal:controller.signal,cache:'no-store'});
        if(claim.ok)await takeSwitch(await claim.json());
       }
      }catch(claimError){/* a missed switch must not paint the panel red */}
     }catch(e){if(mounted)setError(e.message);}}

     let markerCleanup=null,activeSwitch=null;
     async function takeSwitch(job){
      if(job?.finished){markerCleanup?.(job.finished);return false;}
      if(!job?.session)return false;
      if(!job.accepted){
       const claim=await fetch('/focus/open-claim',{method:'POST',headers:{'content-type':'application/json',...pageHeaders()},body:JSON.stringify({id:job.id}),signal:controller.signal});
       if(!claim.ok)return false;
       job=await claim.json();
       if(!job?.accepted)return false;
      }
      activeSwitch=job.id;markerCleanup?.();
      const marker='[DSH-'+job.id+']';
      let failure=null;
      try{
       await focusSession(job.session);
       if(activeSwitch!==job.id)return false;
       const current=await fetch('/focus/open-request?id='+job.id,{signal:controller.signal}).then(r=>r.json());
       if(current.expired)return false;
       // Native foregrounding belongs to the one popup operation, not page timers.
       // The native helper selects this exact tab by this marker, including a hidden tab,
       // and verifies that the window really came forward.
       markerCleanup?.();
       const tag=()=>{if(!document.title.includes(marker))document.title=document.title+' '+marker;};
       tag();
       const title=document.querySelector('title');
       const observer=title?new MutationObserver(tag):null;
       observer?.observe(title,{childList:true,subtree:true,characterData:true});
       const cleanup=(id)=>{if(id&&id!==job.id)return;observer?.disconnect();document.title=document.title.replace(' '+marker,'');if(markerCleanup===cleanup)markerCleanup=null;};
       markerCleanup=cleanup;setTimeout(()=>cleanup(),Math.max(0,(job.expires_at||Date.now()+20000)-Date.now()));
       globalThis.__DAFEIYU__={...globalThis.__DAFEIYU__,focusedSession:job.session,claimError:null,page:pageId,switchLanded:true};
      }catch(e){failure=String(e.message||e);globalThis.__DAFEIYU__={...globalThis.__DAFEIYU__,claimError:failure};}
      await fetch('/focus/open-complete',{method:'POST',headers:{'content-type':'application/json',...pageHeaders()},body:JSON.stringify({id:job.id,error:failure}),signal:controller.signal});
      return !failure;
     }
     async function holdSwitchChannel(){
      // One held request per page and no more: several DSH pages each wait on their own
      // channel, the plugin hands the switch to a visible one first, and a page whose
      // fetch is cut off by the browser simply comes back to wait again.
      while(mounted){
       try{
        const response=await fetch('/focus/claim-wait',{headers:pageHeaders(),signal:controller.signal,cache:'no-store'});
        if(response.status===403){await renewToken(controller.signal);continue;}
        if(!response.ok)throw Error('监工切换通道不可用');
        await takeSwitch(await response.json());
       }catch(e){if(!mounted)return;await new Promise(resolve=>setTimeout(resolve,2000));}
      }
     }
     refresh();
     holdSwitchChannel();
     const timer=setInterval(refresh,5000);return()=>{mounted=false;controller.abort();markerCleanup?.();clearInterval(timer);};},[]);
    const live=state?.live||[], seriesMap=Object.fromEntries((state?.series||[]).map(s=>[s.id,s])), labels={scheduled:'已预约',active:'监督中',verified_waiting:'已通过 · 等待约定结束'};
    const activeTasks=live.filter(t=>t.status!=='scheduled');
    const scheduledTasks=live.filter(t=>t.status==='scheduled').slice().sort((a,b)=>(a.start_at??0)-(b.start_at??0));
    const [taskOpen,setTaskOpen]=React.useState({});
    const isTaskOpen=t=>taskOpen[t.id]??(t.status!=='scheduled');
    const toggleTask=t=>setTaskOpen(m=>({...m,[t.id]:!(m[t.id]??(t.status!=='scheduled'))}));
    const statusTone={scheduled:['#FFF3E0','#B4791F'],active:['#E9F7EF','#2F8F68'],awaiting_extension:['#FDECEF','#C2555F'],verified_waiting:['#EDF1FF','#5A67B8']};
    const chip=(tone,text)=>{const pair=tone||['#EDF1FF',CUTE.blueDeep];
     return h('span',{style:{display:'inline-block',padding:'3px 10px',borderRadius:999,background:pair[0],color:pair[1],fontSize:11.5,fontWeight:700,lineHeight:1.6}},text);};
    const cardStyle={background:CUTE.card,border:'1px solid '+CUTE.line,borderRadius:18,padding:'12px 14px',marginTop:10,boxShadow:'0 8px 20px rgba(140,160,210,.10)'};
    const fieldStyle={display:'block',boxSizing:'border-box',width:'100%',marginTop:6,padding:'9px 11px',border:'1px solid '+CUTE.line,borderRadius:12,resize:'vertical',color:CUTE.ink,background:'#FCFDFF',font:'inherit',fontSize:12.5,lineHeight:1.6};
    const labelStyle={display:'block',marginTop:12,color:CUTE.sub,fontSize:12,fontWeight:600};
    const fieldLabels={instructions:'插件使用说明（全局）',heartbeat_prompt:'每次心跳的监工要求（全局）',strict_heartbeat_prompt:'严苛任务附加要求',instructions_full:'完整 API 文档（focus_help 返回，全局）'};
    const fieldTitles=[['instructions','📝 插件使用说明（全局）'],['instructions_full','📚 完整 API 文档（focus_help 返回，全局）'],['heartbeat_prompt','💓 每次心跳的监工要求（全局）'],['strict_heartbeat_prompt','🔒 严苛任务附加要求']];
    const fieldHints={instructions:'⚠️ 这份说明会随系统提示词发给每一个 AI 会话并一直占用上下文，请保持简短；详细用法写进下面的完整 API 文档。',
     instructions_full:'📖 只在 AI 调用 focus_help 时读取，不占常驻上下文，可以写详细。',
     heartbeat_prompt:'💓 只在监督任务的心跳消息里下发，平时不占上下文。',strict_heartbeat_prompt:'🔒 仅严苛任务附加；正常任务不受影响。'};
    const hintStyle={margin:'6px 0 0',color:CUTE.faint,fontSize:11,lineHeight:1.6};
    const setupCard=()=>{
     const setup=state?.setup,install=state?.setup_install;
     if(!setup||!setup.required)return null;
     const verified=!!setup.payload?.verified;
     return h('div',{'data-dafeiyu-setup':verified?'required':'hash-mismatch',
      style:{...cardStyle,borderLeft:'4px solid '+(verified?CUTE.amber:CUTE.rose),background:'#FFFDF6'}},
      h('p',{style:{margin:0,fontWeight:700,fontSize:13}},'🧩 还差一步：安装受保护后台'),
      h('p',{style:{margin:'6px 0 0',color:CUTE.sub,fontSize:11.5,lineHeight:1.7}},'插件本体已经装好。采集证据、心跳和关闭分心窗口需要一次性管理员授权安装后台服务（systemd + 桌面采集）。'),
      !verified
       ? h('p',{style:{margin:'8px 0 0',color:CUTE.rose,fontSize:11.5,lineHeight:1.7}},'⚠️ 随包安装脚本校验失败：'+(setup.payload?.reason||'摘要与清单不一致')+'。请重新安装插件后再试，已拒绝提权。')
       : h('div',null,
          h('p',{style:{margin:'8px 0 0',color:CUTE.faint,fontSize:11,lineHeight:1.6,wordBreak:'break-all'}},'将执行：'+setup.installer),
          h('p',{style:{margin:'2px 0 0',color:CUTE.faint,fontSize:11,lineHeight:1.6}},'载荷摘要 '+String(setup.payload?.digest||'').slice(0,16)+'… 已校验通过（'+setup.payload?.file_count+' 个文件）'),
          h('div',{style:{display:'flex',gap:8,flexWrap:'wrap',marginTop:10,alignItems:'center'}},
           h(CuteButton,{label:setupBusy||install?.state==='running'?'正在安装…':'用管理员权限安装',tone:'primary',
            disabled:setupBusy||install?.state==='running',attrs:{'data-dafeiyu-setup-install':'1'},onClick:startBackendInstall}),
           h(CuteButton,{label:'复制命令',tone:'soft',onClick:()=>copyInstallCommand(setup.command)})),
          install&&install.state!=='running'&&h('p',{role:'status',style:{margin:'8px 0 0',fontSize:11.5,lineHeight:1.7,color:install.state==='ok'?CUTE.mint:(install.state==='cancelled'?CUTE.sub:CUTE.rose)}},
           install.state==='ok'?'✅ 后台已安装：刷新页面后即可开始监督。'
            :install.state==='cancelled'?'已取消授权（没有安装任何东西），可以再点一次。'
            :install.state==='manual'?'没有可用的图形授权工具：请用「复制命令」在终端执行。'
            :'❌ 安装失败：'+String(install.output||'').slice(-400)),
          h('p',{style:{margin:'8px 0 0',color:CUTE.faint,fontSize:11,lineHeight:1.6,wordBreak:'break-all'}},'命令：'+setup.command),
          setupMessage&&h('p',{role:'status',style:{margin:'6px 0 0',fontSize:11.5,color:CUTE.blueDeep}},'💡 '+setupMessage)));
    };
    const taskCard=t=>{
     const openTask=isTaskOpen(t), tone=statusTone[t.status]||['#EDF1FF',CUTE.blueDeep];
     const series=seriesMap[t.series_id];
     const repeat=series?.repeat;
     const repeatLabel=repeat?(repeat.frequency==='daily'?'每天':'每周 '+(repeat.weekdays||[]).map(n=>['','一','二','三','四','五','六','日'][n]).join('、'))+' · '+(repeat.count?`共 ${repeat.count} 次`:repeat.until?`至 ${repeat.until}`:'一直重复'):'';
     return h('article',{key:t.id,'data-task-id':t.id,'data-expanded':openTask?'1':'0','data-start-at':String(t.start_at??''),
      style:{...cardStyle,marginTop:8,borderLeft:'4px solid '+tone[0]}},
      h('div',{style:{display:'flex',alignItems:'center',justifyContent:'space-between',gap:8}},
       h('div',{style:{display:'flex',alignItems:'center',gap:8,minWidth:0}},chip(tone,labels[t.status]||t.status),
        h('span',{style:{color:CUTE.sub,fontSize:11.5,whiteSpace:'nowrap',overflow:'hidden',textOverflow:'ellipsis'}},'🗓 '+new Date(t.start_at*1000).toLocaleString())),
       h(CuteButton,{label:openTask?'收起':'展开',tone:'ghost',style:{padding:'4px 10px',flex:'0 0 auto'},attrs:{'data-dafeiyu-toggle':'1'},onClick:()=>toggleTask(t)})),
      openTask&&h('div',null,
       h('p',{style:{whiteSpace:'pre-wrap',lineHeight:1.7,margin:'8px 0 0'}},t.agreement),
       h('p',{style:{color:CUTE.sub,fontSize:12}},t.strictness==='strict'?'🔒 严苛任务':'🌿 普通任务',series&&` · ${repeatLabel} · 已经过 ${series.consumed||0} 轮${series.missed?`（错过 ${series.missed} 轮）`:''} · 第 ${t.occurrence_index+1} 轮`),
       h('p',{style:{color:CUTE.faint,fontSize:11.5,margin:'8px 0 0'}},'🗓 '+new Date(t.start_at*1000).toLocaleString()+' → '+new Date(t.end_at*1000).toLocaleString()),
       h('details',{style:{marginTop:8}},h('summary',{style:{cursor:'pointer',color:CUTE.blueDeep,fontWeight:600}},'本任务心跳附加提示词'),
        h('p',{style:{whiteSpace:'pre-wrap',color:CUTE.sub,lineHeight:1.7}},t.task_prompt||'旧任务沿用已有约定，可请监工 AI 补充。')),
       h('p',{style:{margin:'8px 0 0',color:CUTE.sub,fontSize:12}},'⏱ 常规检查间隔：'+`${t.check_interval_seconds??state.interval??600} 秒`),
       h('p',{style:{margin:'4px 0 0',color:CUTE.sub,fontSize:12}},(t.allow_early_finish?'✅ 允许提前完成':'⏳ 按约定时间结束')+' · 到时结束监督'),
       h(CuteButton,{label:'回到监工聊天',tone:'soft',style:{marginTop:10},onClick:()=>{ctx.uiWorkspace.openSession(t.session_id);setOpen(false);}}),
       t.strictness!=='strict'&&series?.template?.strictness!=='strict'&&(
         series?h('div',{style:{display:'flex',gap:8,flexWrap:'wrap',marginTop:10}},
           h(CuteButton,{label:t.status==='scheduled'?'跳过下一轮':'结束本轮',tone:'pink',onClick:()=>finishTask(t,'current_only')}),
           h(CuteButton,{label:'结束整个循环',tone:'pink',onClick:()=>finishTask(t,'entire_series')})):
         h(CuteButton,{label:'手动结束任务',tone:'pink',style:{marginTop:10},onClick:()=>finishTask(t)}))));
    };
    async function finishTask(task,scope) {
      try {
        const response=await fetch('/focus/finish',{method:'POST',headers:{'content-type':'application/json','x-focus-token':globalThis.__DAFEIYU__?.token||''},body:JSON.stringify({task_id:task.id,scope})});
        const result=await response.json();if(!response.ok||result.error)throw Error(result.error||'结束失败');
        setState(s=>({...s,live:s.live.filter(t=>t.id!==task.id)}));
      } catch(error) {setError(error.message);}
    }
    const settingsFields=()=>fieldTitles.map(([key,title])=>h('div',{key},
     h('label',{style:labelStyle},title,
      h('textarea',{'aria-label':fieldLabels[key],title,value:draft[key]??'',readOnly:!!state?.settings?.ui_locked,rows:key==='instructions_full'?10:7,
       style:{...fieldStyle,background:state?.settings?.ui_locked?'#F1F4F9':'#FCFDFF'},
       onChange:e=>setDraft(d=>({...d,[key]:e.target.value}))})),
     h('p',{style:hintStyle},fieldHints[key])));
    return h('aside',{'aria-label':'大肥鱼监工',style:{position:'fixed',left:position.x,top:position.y,width:size,height:size,zIndex:90,fontFamily:font,fontSize:13,color:CUTE.ink,pointerEvents:'auto'}},
     open&&h('section',{style:{position:'fixed',left:panelLeft,width:panelWidth,boxSizing:'border-box',...panelStyle,overflowY:'auto',background:CUTE.gradient,border:'1px solid rgba(255,255,255,.9)',borderRadius:26,padding:18,boxShadow:CUTE.shadow}},
      h('div',{style:{display:'flex',alignItems:'center',gap:10}},
       h('span',{style:{flex:'0 0 auto',width:42,height:42,borderRadius:16,background:'linear-gradient(135deg,#FFE3F1,#DDEEFF)',display:'flex',alignItems:'center',justifyContent:'center',fontSize:20,boxShadow:'inset 0 0 0 1px rgba(255,255,255,.8)'}},'🐟'),
       h('span',{style:{flex:'1 1 auto',minWidth:0}},
        h('strong',{style:{display:'block',fontSize:16,letterSpacing:.2}},'大肥鱼监工'),
        h('span',{style:{display:'block',fontSize:11,color:CUTE.sub,marginTop:1}},'陪你专注 · 到点验收')),
       h(CuteButton,{label:'收起',ariaLabel:'收起监工',tone:'ghost',onClick:()=>setOpen(false)})),
      h('div',{style:{marginTop:12,display:'flex',alignItems:'center',gap:8}},
       chip(['#FFFFFF',CUTE.blueDeep],connectionLabel||captions[kind]),
       live.length>0&&chip(['#FFFFFF',CUTE.pinkDeep],`${live.length} 个约定`)),
      setupCard(),
      h(CuteButton,{label:settingsOpen?'收起设置':'设置 · 采集与提示词',tone:'soft',expanded:settingsOpen,
       style:{display:'block',width:'100%',marginTop:12,textAlign:'center'},onClick:()=>setSettingsOpen(v=>!v)}),
      settingsOpen&&draft&&h('div',{style:cardStyle},
       state?.settings?.ui_locked&&h('p',{role:'status',style:{margin:'0 0 10px',padding:'9px 11px',borderRadius:12,background:'#FFF6E6',color:'#A97818',lineHeight:1.6}},'🔒 有严苛任务或循环预约，界面设置已锁定。可在监工聊天中商量修改。'),
       h('label',{style:{...labelStyle,marginTop:0}},`🎚 形象大小：${size} px`,
        h('input',{type:'range',min:80,max:320,step:8,value:size,disabled:state?.settings?.ui_locked||saving,'aria-label':'形象大小',
         style:{width:'100%',accentColor:CUTE.pink,marginTop:6},
         onChange:e=>{const n=Number(e.target.value);setSize(n);setDraft(d=>({...d,mascot_size:n}));}})),
       h('label',{style:labelStyle},`🛌 离席判定：连续 ${draft.away_heartbeats??3} 次心跳没有鼠标或键盘输入就进入待机`,
        h('input',{type:'number',min:2,max:10,step:1,value:draft.away_heartbeats??3,disabled:state?.settings?.ui_locked||saving,'aria-label':'离席判定次数',
         style:{...fieldStyle,width:80,marginTop:8,textAlign:'center',fontWeight:700},
         onChange:e=>setDraft(d=>({...d,away_heartbeats:Math.min(10,Math.max(2,Math.trunc(Number(e.target.value))||3))}))})),
       ...settingsFields(),
       ...samplingFields(),
       h('div',{style:{display:'flex',gap:8,flexWrap:'wrap',marginTop:14,alignItems:'center'}},
        h(CuteButton,{label:saving?'保存中…':'保存设置',tone:'primary',disabled:state?.settings?.ui_locked||saving,onClick:saveSettings}),
        h(CuteButton,{label:'重置为默认提示词',tone:'pink',disabled:state?.settings?.ui_locked||saving,onClick:resetSettings})),
       h('p',{style:{color:CUTE.faint,lineHeight:1.6,marginTop:8,marginBottom:0,fontSize:11.5}},'自定义内容优先于插件默认值；重置只恢复提示词，不改形象大小与离席判定。'),
       saveMessage&&h('p',{role:'status',style:{marginTop:8,marginBottom:0,padding:'8px 10px',borderRadius:12,background:'#F2F8FF',color:CUTE.blueDeep,lineHeight:1.6}},saveMessage)),
      h('p',{style:{color:CUTE.sub,lineHeight:1.65,marginTop:12,marginBottom:0}},error?'⚠️ 暂时无法读取最新状态，正在重连。':!state?'⏳ 正在连接监工后台…':live.length?`${live.length} 个约定 · ${state.running?({collecting:'正在采集',scheduled:'等待预约',away:'离席待机',verified_waiting:'等待约定结束',idle:'等待退出'}[state.capture_state]||'后台运行'):'后台正在恢复'}`:'😴 目前没有任务，监工后台休息中。'),
      state&&!error&&!live.length&&h('p',{style:{lineHeight:1.85,marginTop:8,marginBottom:0}},'直接在聊天里告诉 AI 你想做什么、何时开始和结束，并商量提前完成及延期的安排。'),
      live.length>0&&h('div',{style:{marginTop:12}},
       activeTasks.length>0&&h('div',{'data-dafeiyu-group':'active'},
        h('p',{style:{margin:0,color:CUTE.pinkDeep,fontWeight:700,fontSize:12}},'🩷 进行中 · '+activeTasks.length),
        ...activeTasks.map(taskCard)),
       scheduledTasks.length>0&&h('div',{'data-dafeiyu-group':'scheduled',style:{marginTop:12}},
        h('p',{style:{margin:0,color:CUTE.blueDeep,fontWeight:700,fontSize:12}},'💙 已预约 · '+scheduledTasks.length+'（按开始时间排序，默认收起）'),
        ...scheduledTasks.map(taskCard))),
      state?.desktop_setup&&h('p',{role:'status',style:{marginTop:10,marginBottom:0,color:(state.desktop_setup.code==='bridge_running'||state.desktop_setup.screenshot_verified)?CUTE.mint:CUTE.amber,lineHeight:1.6}},'🖥 桌面接口：'+state.desktop_setup.message),
      live.length>0&&state?.capture_error&&h('p',{role:'status',style:{marginTop:8,marginBottom:0,color:CUTE.amber,lineHeight:1.6}},'📷 采集提示：'+state.capture_error),
      (error||state?.delivery_error)&&h('p',{role:'alert',style:{marginTop:8,marginBottom:0,color:CUTE.rose,lineHeight:1.6}},'⚠️ '+(error||state.delivery_error)),
      h('p',{style:{fontSize:11.5,color:CUTE.faint,marginTop:12,marginBottom:0,lineHeight:1.6}},'解释、修改约定和完成验收都在聊天中进行。')),
     popup&&h('section',{role:'dialog','aria-label':'监工提醒','aria-modal':true,style:{position:'fixed',left:'50%',top:'50%',transform:'translate(-50%,-50%)',zIndex:120,width:'min(440px, calc(100vw - 32px))',maxHeight:'90vh',overflowY:'auto',boxSizing:'border-box',padding:24,borderRadius:28,background:CUTE.gradient,border:'1px solid rgba(255,255,255,.9)',boxShadow:'0 20px 90px rgba(23,32,73,.40)',textAlign:'center',fontFamily:font,color:CUTE.ink}},
      h('span',{style:{display:'inline-block',padding:'4px 12px',borderRadius:999,background:'#FFFFFF',color:CUTE.pinkDeep,fontSize:12,fontWeight:700,boxShadow:'0 6px 16px rgba(150,170,220,.22)'}},'🩷 大肥鱼提醒'),
      h('img',{src:`/focus/mascot/${popup.kind}.png`,alt:'',style:{display:'block',width:'min(320px,100%)',margin:'10px auto 0',filter:'drop-shadow(0 10px 18px rgba(120,140,190,.28))'}}),
      h('p',{style:{fontSize:16,whiteSpace:'pre-wrap',lineHeight:1.75,margin:'6px auto 0',padding:'12px 14px',borderRadius:18,background:'rgba(255,255,255,.86)',boxShadow:'0 8px 20px rgba(140,160,210,.14)'}},popup.text),
      h('div',{style:{display:'flex',gap:8,justifyContent:'center',flexWrap:'wrap',marginTop:16}},
       h(CuteButton,{label:'回到监工聊天',tone:'primary',onClick:()=>{if(popup.session_id)ctx.uiWorkspace.openSession(popup.session_id);setPopup(null);}}),
       h(CuteButton,{label:'知道了',tone:'soft',onClick:()=>setPopup(null)}))),
     notice&&h('div',{role:'status',style:{position:'absolute',bottom:size+8,right:0,width:210,boxSizing:'border-box',padding:'10px 14px',borderRadius:18,background:'linear-gradient(135deg,#FFE7F2,#E6F2FF)',color:CUTE.ink,border:'1px solid rgba(255,255,255,.9)',boxShadow:'0 10px 24px rgba(140,160,210,.26)',pointerEvents:'none',fontSize:12.5,lineHeight:1.6}},notice.text),
     h('button',{'aria-label':`大肥鱼监工：${connectionLabel||captions[kind]}，点击展开，拖动移动`,title:`${connectionLabel||captions[kind]} · 点击查看 · 拖动移动`,'aria-expanded':open,
      onPointerDown:e=>{if(e.button!==0)return;skipClick.current=false;drag.current={x:e.clientX,y:e.clientY,origin:position,moved:false};e.currentTarget.setPointerCapture(e.pointerId);},
      onPointerMove:e=>{const d=drag.current;if(!d)return;const dx=e.clientX-d.x,dy=e.clientY-d.y;if(Math.hypot(dx,dy)>5)d.moved=true;if(d.moved)setPosition(clamp({x:d.origin.x+dx,y:d.origin.y+dy}));},
      onPointerUp:endDrag,onPointerCancel:endDrag,
      onClick:e=>{if(skipClick.current&&e.detail!==0){skipClick.current=false;return;}setOpen(o=>!o);},
      onKeyDown:e=>{if(e.key==='Escape')setOpen(false);},
      style:{display:'block',position:'relative',width:size,height:size,border:0,padding:0,background:'transparent',cursor:'grab',touchAction:'none',userSelect:'none',borderRadius:24,
       filter:open?'drop-shadow(0 10px 22px rgba(150,170,220,.45))':'drop-shadow(0 6px 14px rgba(150,170,220,.32))'}},
      state&&h('span',{'aria-hidden':'true',style:{position:'absolute',inset:'12%',borderRadius:'50%',background:'radial-gradient(circle at 35% 30%,rgba(255,214,232,.85),rgba(196,226,255,.55) 60%,rgba(255,255,255,0) 72%)',zIndex:0,pointerEvents:'none'}}),
      state?h('img',{src:`/focus/mascot/${kind}.png`,alt:captions[kind],draggable:false,style:{position:'relative',zIndex:1,width:'100%',height:'100%',objectFit:'contain',pointerEvents:'none'}}):h('span',{style:{display:'inline-block',padding:14,borderRadius:18,background:'linear-gradient(135deg,#FFE7F2,#E6F2FF)',color:CUTE.sub,fontSize:13,border:'1px solid rgba(255,255,255,.9)'}},connectionLabel)));
   }
   ctx.slots.inject('shell.overlay',()=>ctx.slots.register({name:'shell.overlay',id:'dafeiyu-floating-ball',order:90},Ball));
  }};
 }
});
