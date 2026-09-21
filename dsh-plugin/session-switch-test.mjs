// 弹窗按钮切会话的校验逻辑必须随 DSH 版本自适应：0.1.6 把视图选择移出了 Session Controller
// （list.current 不再存在），公开判据是「主视图是否保留该会话」。这个测试直接取 client.js 里
// 真正发货的 sessionWatchers/focusSession 源码来跑，避免再出现「把成功报成失败」。
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const source = readFileSync(fileURLToPath(new URL('./client.js', import.meta.url)), 'utf8');
const start = source.indexOf('function sessionWatchers(');
const end = source.indexOf('function Ball(');
assert.ok(start > 0 && end > start, 'client.js 里应能找到 sessionWatchers 与 Ball 的位置');

function harness(sessions) {
  const opened = [];
  const ctx = { get: (name) => (name === 'sessions' ? sessions : undefined),
    uiWorkspace: { openSession: (id) => opened.push(id) } };
  const factory = new Function('ctx', `${source.slice(start, end)}; return focusSession;`);
  return { focusSession: factory(ctx), opened };
}

const retention = (count) => ({ getSnapshot: () => ({ retainedBy: { mainView: count } }) });

test('0.1.6：以主视图保留作为判据', async () => {
  let retained = 0;
  setTimeout(() => { retained = 1; }, 30);
  const { focusSession, opened } = harness({ retainInfo: () => retention(retained) });
  await focusSession('session-a');
  assert.deepEqual(opened, ['session-a']);
  assert.deepEqual(globalThis.__DAFEIYU__.switchVerifiers, ['main-view-retention']);
});

test('0.1.5 及更早：回退到 list.current', async () => {
  let current = 'session-other';
  setTimeout(() => { current = 'session-a'; }, 30);
  const { focusSession } = harness({ list: { getSnapshot: () => ({ current }) } });
  await focusSession('session-a');
  assert.deepEqual(globalThis.__DAFEIYU__.switchVerifiers, ['list-main-view', 'list-current']);
});

test('0.1.6 拿不到 retainInfo 时看列表行里主视图保留谁', async () => {
  const rows = { 'session-a': { id: 'session-a', retainedBy: { mainView: 0 } },
    'session-b': { id: 'session-b', retainedBy: { mainView: 1 } } };
  const { focusSession } = harness({ list: { getSnapshot: () => ({ byId: rows }) } });
  setTimeout(() => { rows['session-a'].retainedBy.mainView = 1; rows['session-b'].retainedBy.mainView = 0; }, 30);
  await focusSession('session-a');
});

test('别的会话占着主视图时不算切过去了', async () => {
  const rows = { 'session-a': { id: 'session-a', retainedBy: { mainView: 0 } },
    'session-b': { id: 'session-b', retainedBy: { mainView: 1 } } };
  const { focusSession } = harness({ list: { getSnapshot: () => ({ byId: rows, current: 'session-b' }) } });
  await assert.rejects(() => focusSession('session-a'), /未切换到指定监工会话/);
});

test('两个信号都观测不到时不谎报失败', async () => {
  const { focusSession, opened } = harness(undefined);
  await focusSession('session-a');
  assert.deepEqual(opened, ['session-a']);
  assert.deepEqual(globalThis.__DAFEIYU__.switchVerifiers, []);
});

test('真的没切过去时仍然报失败', async () => {
  const { focusSession } = harness({ retainInfo: () => retention(0) });
  await assert.rejects(() => focusSession('session-a'), /未切换到指定监工会话/);
});

test('主视图保留但另一个版本字段缺失也不能误判', async () => {
  const { focusSession } = harness({ retainInfo: () => ({ getSnapshot: () => ({}) }) });
  await assert.rejects(() => focusSession('session-a'), /未切换到指定监工会话/);
});

test('旧页面从当前同源 HTML 更新令牌，不执行返回的脚本', async () => {
  const a=source.indexOf('async function renewToken('),b=source.indexOf('// How the Session',a);
  const state={__DAFEIYU__:{token:'old'}};
  const fetch=async()=>({ok:true,text:async()=>'<script>globalThis["__DAFEIYU__"] = {"token":"new"}</script><script>throw Error("must not execute")</script>'});
  const renew=new Function('fetch','globalThis',source.slice(a,b)+';return renewToken;')(fetch,state);
  await renew(new AbortController().signal);
  assert.equal(state.__DAFEIYU__.token,'new');
});
