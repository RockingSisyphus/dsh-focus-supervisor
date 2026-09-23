// Model projections only. The service, settings UI, and exported evidence keep
// their full data; an explicit full read is never projected.
const pick=(value,keys)=>Object.fromEntries(keys.filter(k=>value?.[k]!==undefined).map(k=>[k,value[k]]));
const taskKeys=['id','series_id','occurrence_index','strictness','status','session_id','start_at','end_at','revision','check_interval_seconds'];
export const taskSummary=value=>pick(value,taskKeys);
export function compactResult(name,value,args={}) {
  if(!value||typeof value!=='object'||args.detail==='full')return value;
  if(name==='focus_status')return {...pick(value,['running','shutting_down','last_sample_at','presence','capture_error','delivery_error','poll_error']),
    live:(value.live||[]).map(taskSummary),series:(value.series||[]).map(s=>pick(s,['id','status','consumed','missed','next_start_at','current_task_id','repeat'])),reports:(value.reports||[]).map(r=>pick(r,['id','task_id','phase','status','created_at','delivered']))};
  if(name==='focus_check')return {...pick(value,['id','report_id','task_id','phase','status','presence','window_start','window_end','input_activity','overview','capture_error','evidence_export','_image_base64']),
    ...(value.task?{task:taskSummary(value.task)}:{})};
  if(['focus_plan','focus_revise','focus_finish'].includes(name))return {...taskSummary(value),...pick(value,['action','desktop_setup'])};
  if(name==='focus_observe')return {report_id:args.report_id,task:taskSummary(value.task),action:value.action};
  if(name==='focus_settings'&&args.operation==='update') {
    const patch=JSON.parse(args.patch_json||'{}');
    const changed=Object.fromEntries(Object.keys(patch).map(key=>[key,key==='task_prompt'?value.task?.task_prompt:
      (patch[key]&&typeof patch[key]==='object'?pick(value.settings?.[key],Object.keys(patch[key])):value.settings?.[key])]));
    return {status:'updated',changed,...(value.task?{task:taskSummary(value.task)}:{})};
  }
  return value;
}

export function taskContext(state,sessionId,prompts) {
  const tasks=(state.live||[]).filter(t=>t.session_id===sessionId);
  if(!tasks.length)return '';
  const series=(state.series||[]).filter(s=>s.session_id===sessionId);
  return '[大肥鱼当前任务约定]\n'+tasks.map(task=>JSON.stringify(pick(task,
    [...taskKeys,'agreement','task_prompt','allow_early_finish','deadline_policy']))).join('\n')+
    (series.length?'\n[循环进度]\n'+series.map(s=>JSON.stringify(pick(s,['id','repeat','consumed','missed','next_start_at','current_task_id']))).join('\n'):'')+
    '\n[用户心跳要求]\n'+prompts.heartbeat_prompt+
    (tasks.some(t=>t.strictness==='strict')?'\n[严苛任务附加要求]\n'+prompts.strict_heartbeat_prompt:'');
}
