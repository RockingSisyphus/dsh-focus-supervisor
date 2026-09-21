import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, mkdir, writeFile, rm, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {treeDigest, payloadStatus, elevationPlan, runInstall, installCommand, runnerPath, spawnEnv, SAFE_PATH} from './setup.mjs';

async function fixture() {
  const dir = await mkdtemp(path.join(tmpdir(), 'dafeiyu-payload-'));
  await mkdir(path.join(dir, 'deploy'), {recursive: true});
  await mkdir(path.join(dir, 'focus_demo'), {recursive: true});
  await writeFile(path.join(dir, 'deploy', 'install-chat.sh'), '#!/bin/bash\nexit 0\n');
  await writeFile(path.join(dir, 'focus_demo', 'control.py'), 'VALUE = 1\n');
  const {files, digest} = treeDigest(dir);
  await writeFile(path.join(dir, 'manifest.json'), JSON.stringify({payload_sha256: digest, files: files.map(f => f[0])}));
  return {dir, digest};
}

test('payload digest accepts the pinned tree and rejects a tampered file', async () => {
  const {dir, digest} = await fixture();
  try {
    const good = payloadStatus(dir);
    assert.equal(good.present, true);
    assert.equal(good.verified, true, good.reason || '');
    assert.equal(good.digest, digest);
    assert.ok(good.file_count >= 2);
    await writeFile(path.join(dir, 'focus_demo', 'control.py'), 'VALUE = 2\n');
    const bad = payloadStatus(dir);
    assert.equal(bad.verified, false, 'tampering must fail verification before any elevation');
    assert.equal(bad.expected, digest);
    assert.notEqual(bad.digest, digest);
  } finally { await rm(dir, {recursive: true, force: true}); }
});

test('missing manifest or payload is reported instead of assumed trustworthy', async () => {
  const empty = await mkdtemp(path.join(tmpdir(), 'dafeiyu-empty-'));
  try {
    const status = payloadStatus(empty);
    assert.equal(status.present, false);
    assert.equal(status.verified, false);
    assert.ok(status.reason);
  } finally { await rm(empty, {recursive: true, force: true}); }
});

test('elevation prefers pkexec, then a zenity askpass for sudo, then a copyable command', () => {
  const args = {platform: 'linux', payloadDir: '/pkg/backend', user: 'alice'};
  const withPkexec = elevationPlan({...args, which: name => name === 'pkexec' ? '/usr/bin/pkexec' : null});
  assert.equal(withPkexec.mode, 'pkexec');
  assert.equal(withPkexec.program, '/usr/bin/pkexec');
  assert.deepEqual(withPkexec.args.slice(0, 2), ['/bin/bash', path.join(args.payloadDir,'deploy/install-chat.sh')]);
  assert.equal(withPkexec.args.at(-1), 'alice');
  const withSudo = elevationPlan({...args, which: name => ({sudo: '/usr/bin/sudo', zenity: '/usr/bin/zenity'})[name] || null});
  assert.equal(withSudo.mode, 'sudo-askpass');
  assert.equal(withSudo.program, '/usr/bin/sudo');
  assert.deepEqual(withSudo.args.slice(0, 1), ['-A']);
  assert.match(withSudo.command, /install-chat\.sh/);
  const manual = elevationPlan({...args, which: () => null});
  assert.equal(manual.mode, 'manual');
  assert.equal(manual.program, null);
  assert.equal(manual.command, 'sudo bash "'+path.join(args.payloadDir,'deploy/install-chat.sh')+'" alice');
});

test('windows elevation uses the packaged powershell installer and never a shell string', () => {
  const plan = elevationPlan({platform: 'win32', payloadDir: 'C:\\pkg\\backend', user: 'alice'});
  assert.equal(plan.mode, 'windows-uac');
  assert.equal(plan.program, 'powershell.exe');
  assert.ok(plan.args.includes('-File'));
  assert.ok(plan.args.some(value => value.endsWith('install-windows.ps1')));
  assert.match(installCommand(plan), /install-windows\.ps1/);
});

test('install runs the fixed plan and classifies cancel, timeout, success and failure', async () => {
  const plan = elevationPlan({platform: 'linux', payloadDir: '/pkg/backend', user: 'alice', which: () => '/usr/bin/pkexec'});
  const calls = [];
  const spawn = (program, args, options) => { calls.push({program, args, options}); return {code: 0, output: 'installed\n'}; };
  const ok = await runInstall(plan, {spawn});
  assert.equal(ok.ok, true);
  assert.equal(calls[0].program, '/usr/bin/pkexec');
  assert.equal(calls[0].options.env.PATH, '/usr/sbin:/usr/bin:/sbin:/bin');

  const cancelled = await runInstall(plan, {spawn: () => ({code: 126, output: ''})});
  assert.equal(cancelled.ok, false);
  assert.equal(cancelled.cancelled, true);

  const failed = await runInstall(plan, {spawn: () => ({code: 1, output: 'apt-get failed'})});
  assert.equal(failed.ok, false);
  assert.equal(failed.cancelled, false);
  assert.match(failed.output, /apt-get failed/);

  const timedOut = await runInstall(plan, {spawn: () => ({timeout: true, output: 'partial'})});
  assert.equal(timedOut.ok, false);
  assert.equal(timedOut.timeout, true);
  assert.match(timedOut.output, /partial/);
});

test('windows runs with the system PATH so powershell.exe resolves at all', async () => {
  const plan = elevationPlan({platform: 'win32', payloadDir: 'C:\\pkg\\backend', user: 'alice'});
  const calls = [];
  const baseEnv = {SystemRoot: 'C:\\Windows', PATH: 'C:\\Users\\alice\\AppData\\Local\\Programs\\Python\\Python313;C:\\Users\\alice\\bin',
    TEMP: 'C:\\Users\\alice\\AppData\\Local\\Temp', USERPROFILE: 'C:\\Users\\alice', ProgramData: 'C:\\ProgramData'};
  await runInstall(plan, {spawn: (program, args, options) => { calls.push({program, options}); return {code: 0, output: ''}; }, baseEnv});
  assert.equal(calls[0].program, 'powershell.exe');
  assert.match(calls[0].options.env.PATH, /System32/, 'a POSIX PATH would make powershell unresolvable');
  assert.doesNotMatch(calls[0].options.env.PATH, /^\/usr/);
  assert.match(calls[0].options.env.PATH, /Python313/, 'the user PATH is where python.exe lives; replacing it breaks the installer');
  assert.equal(calls[0].options.env.TEMP, baseEnv.TEMP, 'installers need TEMP/USERPROFILE/ProgramData, so Windows keeps the base environment');
  assert.equal(calls[0].options.env.USERPROFILE, baseEnv.USERPROFILE);
  assert.equal(runnerPath('linux'), SAFE_PATH);
});

test('linux elevation still replaces the environment instead of inheriting it', async () => {
  const plan = elevationPlan({platform: 'linux', payloadDir: '/pkg/backend', user: 'alice', which: () => '/usr/bin/pkexec'});
  const calls = [];
  await runInstall(plan, {spawn: (program, args, options) => { calls.push({options}); return {code: 0, output: ''}; },
    baseEnv: {PATH: '/tmp/evil:/usr/bin', HOME: '/home/alice', LD_PRELOAD: '/tmp/evil.so'}});
  assert.deepEqual(calls[0].options.env, {PATH: SAFE_PATH}, 'a poisoned PATH or loader must not reach the root installer');
});

test('the shipped Windows installer keeps its UTF-8 BOM', async () => {
  // Windows PowerShell 5.1 reads a BOM-less .ps1 as ANSI, which turns the installer's
  // Chinese diagnostics into a parse error and stops the install before it starts.
  const raw = await readFile(new URL('../deploy/install-windows.ps1', import.meta.url));
  assert.ok(raw.subarray(0, 3).equals(Buffer.from([0xef, 0xbb, 0xbf])),
    'deploy/install-windows.ps1 lost its UTF-8 BOM; re-add it (editors strip it)');
});

test('a bare host environment still yields a usable Windows installer environment', () => {
  const plan = elevationPlan({platform: 'win32', payloadDir: 'C:\\pkg\\backend', user: 'alice'});
  const env = spawnEnv(plan, {});
  assert.equal(env.ProgramData, 'C:\\ProgramData', 'a missing ProgramData installs the service at the drive root');
  assert.equal(env.SystemRoot, 'C:\\Windows');
  assert.equal(env.ComSpec, 'C:\\Windows\\System32\\cmd.exe');
  assert.equal(env.PATHEXT, '.COM;.EXE;.BAT;.CMD');
  assert.match(env.PATH, /System32/);
  assert.equal(spawnEnv({platform: 'linux'}, {PATH: '/tmp/evil', LD_PRELOAD: '/tmp/evil.so'}).PATH, SAFE_PATH);
});

test('the real spawn path runs the chosen program and returns its output', {skip: process.platform === 'win32'}, async () => {
  const plan = elevationPlan({payloadDir: '/pkg/backend', user: 'tester', which: name => name === 'pkexec' ? '/bin/echo' : null});
  const result = await runInstall(plan);
  assert.equal(result.ok, true, JSON.stringify(result));
  assert.match(result.output, /install-chat\.sh/, 'the packaged installer path reaches the elevated program');
  assert.match(result.output, /tester/);
});
