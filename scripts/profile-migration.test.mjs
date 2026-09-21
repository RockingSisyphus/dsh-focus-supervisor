import test from 'node:test';
import assert from 'node:assert/strict';
import { migrateEntries } from './profile-migration.mjs';

test('legacy registration preserves custom settings and unrelated plugins', () => {
  const original = [{ insert: [
    { id: 'other', name: 'other-plugin' },
    { id: 'focus-supervisor-chat', name: 'file:///old/plugin.mjs', config: { instructions: '用户自定义' }, disabled: false },
  ] }];
  const expected = [
    { id: 'focus-supervisor-chat', config: { instructions: '用户自定义' }, disabled: false },
    { insert: [{ id: 'other', name: 'other-plugin' }] },
  ];
  assert.deepEqual(migrateEntries(original), expected);
  assert.deepEqual(migrateEntries(expected), expected);
});

test('bare legacy registration is removed; direct overrides retain settings', () => {
  assert.deepEqual(migrateEntries([{ insert: [{ id: 'focus-supervisor-chat', name: 'dsh-focus-supervisor' }] }]), []);
  assert.deepEqual(migrateEntries([{ id: 'focus-supervisor-chat', name: '/old/plugin.mjs', config: { instructions: 'custom' } }]), [
    { id: 'focus-supervisor-chat', config: { instructions: 'custom' } },
  ]);
});
