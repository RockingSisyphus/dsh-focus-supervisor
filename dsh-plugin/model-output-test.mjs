import test from 'node:test';
import assert from 'node:assert/strict';
import {compactResult,taskContext} from './model-output.mjs';
test('compact projection preserves results while full remains untouched',()=>{
 const value={task:{id:'t',status:'active',task_prompt:'long'},report_id:'r',overview:{programs:[]},_image_base64:'image'};
 const compact=compactResult('focus_check',value);
 assert.equal(compact.task.id,'t');assert.equal(compact.task.task_prompt,undefined);
 assert.equal(compact._image_base64,'image');assert.equal(value.task.task_prompt,'long');
 assert.equal(compactResult('focus_check',value,{detail:'full'}),value);
});
test('current context isolates sessions and preserves exact custom instructions',()=>{
 const state={live:[{id:'t',session_id:'a',agreement:'Do A',task_prompt:'keep\n exact'},
  {id:'u',session_id:'b',agreement:'SECRET B'}]};
 const text=taskContext(state,'a',{heartbeat_prompt:'custom\nrequirements'});
 assert.ok(text.includes('Do A'));assert.ok(!text.includes('SECRET B'));
 assert.ok(text.includes('custom\nrequirements'));
 assert.equal(taskContext({live:[]},'a',{}),'');
});
test('settings update reports only submitted fields; query remains full',()=>{
 const value={settings:{sampling:{browser_chars:100,text_chars:200},instructions:'long'}};
 assert.deepEqual(compactResult('focus_settings',value,{operation:'update',patch_json:'{"sampling":{"browser_chars":100}}'}),
  {status:'updated',changed:{sampling:{browser_chars:100}}});
 assert.equal(compactResult('focus_settings',value,{operation:'get'}),value);
});
test('strict context is confined to its session and includes only the current series',()=>{
 const state={live:[{id:'one',session_id:'a',series_id:'series_a',strictness:'strict',agreement:'Read',task_prompt:'check'},
                    {id:'two',session_id:'b',strictness:'normal',agreement:'Write'}],
  series:[{id:'series_a',session_id:'a',consumed:2,repeat:{frequency:'daily',count:5},next_start_at:100},
          {id:'series_b',session_id:'b',consumed:0}]};
 const prompts={heartbeat_prompt:'general',strict_heartbeat_prompt:'firm custom requirement'};
 const strict=taskContext(state,'a',prompts),normal=taskContext(state,'b',prompts);
 assert.ok(strict.includes('firm custom requirement')&&strict.includes('series_a'));
 assert.ok(!strict.includes('series_b')&&!normal.includes('firm custom requirement')&&!normal.includes('series_a'));
});
