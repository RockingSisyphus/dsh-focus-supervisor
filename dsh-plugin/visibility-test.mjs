import test from 'node:test';
import assert from 'node:assert/strict';
import {visibleIds} from '../gnome-extension/visibility.js';
test('partial windows are visible, fully covered and hidden windows are excluded',()=>{
 const windows=[{id:'covered',mapped:true,rect:[10,10,10,10]},
  {id:'partial',mapped:true,rect:[0,0,30,30]},
  {id:'other-workspace',mapped:false,rect:[0,0,100,100]},
  {id:'front',mapped:true,rect:[10,10,30,30]}];
 assert.deepEqual([...visibleIds(windows,[0,0,100,100])],['front','partial']);
});
test('an offscreen mapped window does not become visible from focus',()=>{
 assert.equal(visibleIds([{id:'off',mapped:true,focused:true,rect:[101,0,30,30]}],[0,0,100,100]).size,0);
});
