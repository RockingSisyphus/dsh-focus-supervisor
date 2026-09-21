import test from 'node:test';
import assert from 'node:assert/strict';
import {mascotState} from './mascot-state.mjs';
const t={id:'t',status:'active',start_at:10};
test('idle, appointment, watching, real pending review',()=>{
 assert.equal(mascotState({}).kind,'sleep');
 assert.equal(mascotState({live:[{...t,status:'scheduled'}]}).kind,'scheduled');
 assert.equal(mascotState({live:[t]}).kind,'watching');
 assert.equal(mascotState({live:[t],reports:[{task_id:'t',status:'delivered'}]}).kind,'checking');
 assert.equal(mascotState({live:[t],reports:[{task_id:'other',status:'delivered'}]}).kind,'watching');
});
test('suspicions are not confirmed warnings; returning clears warning',()=>{
 const event=(id,decision)=>({id,event:'agent_observation',ts:id,body:{task_id:'t',decision}});
 assert.equal(mascotState({live:[t],events:[event(1,'suspect')]}).kind,'watching');
 assert.equal(mascotState({live:[t],events:[event(2,'off_task')]}).kind,'warning');
 assert.equal(mascotState({live:[t],events:[event(3,'returned'),event(2,'off_task')]}).kind,'watching');
});
test('only explicit AI reminders produce popups or one-time notices',()=>{
 assert.equal(mascotState({live:[t]},15).notices.length,0);
 const state={alerts:[{id:'a',image:'question',message:'解释一下？',created_at:20,popup:true}]};
 assert.equal(mascotState(state,25).notices[0].kind,'question');
 assert.equal(mascotState(state,150).notices.length,0);
});
