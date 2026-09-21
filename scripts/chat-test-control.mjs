// Test-only duration edits and release use the same daemon reports DSH receives.
import {request} from '../dsh-plugin/chat-host.mjs';
const [op,id,json]=process.argv.slice(2);
const state=await request('/state');
if(op==='state') console.log(JSON.stringify(state,null,2));
else if(!state.test_mode)throw new Error('请先按 docs/usage.md 的开发诊断说明 开启测试模式；正式采集不可改写');
else if(op==='segments')console.log(JSON.stringify(await request('/test/preview',{report_id:id}),null,2));
else if(op==='overview')console.log(JSON.stringify(await request('/report',{report_id:id,operation:'get_overview'}),null,2));
else if(op==='patch')console.log(await request('/test/time',{report_id:id,patch:JSON.parse(json)}));
else if(op==='send')console.log(await request('/test/release',{report_id:id}));
else throw new Error('用法：node scripts/chat-test-control.mjs state | overview 报告编号 | segments 报告编号 | patch 报告编号 JSON | send 报告编号');
