// Display state comes from supervisor evidence, never from an independent check timer.
export function mascotState(state, now=Date.now()/1000) {
 const live=state.live||[], tasks=state.tasks||live, events=state.events||[];
 const active=live.filter(t=>t.status!=='scheduled');
 const observations=events.filter(e=>e.event==='agent_observation');
 const warning=observations.find(e=>active.some(t=>t.id===e.body?.task_id)&&e.body?.decision==='off_task' && !observations.some(n=>n.id>e.id&&n.body?.task_id===e.body.task_id&&['on_task','returned'].includes(n.body?.decision)));
 const checking=(state.reports||[]).some(r=>active.some(t=>t.id===r.task_id)&&['pending','delivered'].includes(r.status));
 const notices=(state.alerts||[]).filter(a=>now-a.created_at<120).map(a=>({id:a.id,kind:a.image,text:a.message,at:a.created_at,popup:a.popup,delivery:a.delivery,session_id:a.session_id}));
 return {kind:warning?'warning':checking?'checking':active.length?'watching':live.length?'scheduled':'sleep',notices:notices.sort((a,b)=>a.at-b.at)};
}
