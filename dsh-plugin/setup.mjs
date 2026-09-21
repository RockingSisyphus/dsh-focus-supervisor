/**
 * First-run backend install: verify the payload shipped inside this package, then
 * elevate with pkexec → sudo askpass (zenity) → a copyable command, and run the
 * packaged installer. Nothing here downloads code: the installer is a local file
 * whose tree digest must match the manifest pinned at pack time.
 */
import {createHash} from 'node:crypto';
import {chmodSync, existsSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync} from 'node:fs';
import {execFile} from 'node:child_process';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {tmpdir, userInfo} from 'node:os';

export const PACKAGE_ROOT = dirname(fileURLToPath(import.meta.url));
export const PAYLOAD_DIR = join(PACKAGE_ROOT, 'backend');
export const SAFE_PATH = '/usr/sbin:/usr/bin:/sbin:/bin';
export const MAX_OUTPUT = 200_000;
export const INSTALL_TIMEOUT_MS = 900_000;

function sha256File(file) {
  return createHash('sha256').update(readFileSync(file)).digest('hex');
}

export function treeDigest(dir) {
  const files = [];
  const walk = (relative) => {
    for (const name of readdirSync(join(dir, relative)).sort()) {
      const child = relative ? relative + '/' + name : name;
      const full = join(dir, child);
      const info = statSync(full);
      if (info.isDirectory()) walk(child);
      else if (info.isFile() && child !== 'manifest.json') files.push([child, sha256File(full)]);
    }
  };
  walk('');
  const hash = createHash('sha256');
  for (const [name, digest] of files) hash.update(name + '\0' + digest + '\n');
  return {files, digest: hash.digest('hex')};
}

export function payloadStatus(dir = PAYLOAD_DIR) {
  try {
    const manifest = JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8'));
    const {files, digest} = treeDigest(dir);
    return {present: true, verified: digest === manifest.payload_sha256, digest, expected: manifest.payload_sha256, file_count: files.length};
  } catch (error) {
    return {present: false, verified: false, reason: String((error && error.message) || error)};
  }
}

export function installArtifacts(platform = process.platform) {
  if (platform === 'win32') {
    const root = join(process.env.ProgramData || 'C:/ProgramData', 'Dafeiyu');
    return {installed: existsSync(join(root, 'config.json')), path: root};
  }
  return {installed: existsSync('/opt/dafeiyu/deploy/chat_service.py'), path: '/opt/dafeiyu'};
}

function defaultWhich(name) {
  for (const dir of SAFE_PATH.split(':')) {
    const candidate = join(dir, name);
    if (existsSync(candidate)) return candidate;
  }
  return null;
}

export function installCommand(plan) {
  if (plan.mode === 'windows-uac') return `${plan.program} ${plan.args.map(value => /\s/.test(value) ? `"${value}"` : value).join(' ')}`;
  return `sudo bash "${plan.payload}" ${plan.user}`;
}

export function elevationPlan(options = {}) {
  const platform = options.platform || process.platform;
  const payloadDir = options.payloadDir || PAYLOAD_DIR;
  const which = options.which || defaultWhich;
  const user = options.user || (userInfo().username || '');
  const finish = (plan) => ({...plan, platform, user, command: installCommand({...plan, user})});
  if (platform === 'win32') {
    const payload = join(payloadDir, 'deploy', 'install-windows.ps1');
    return finish({mode: 'windows-uac', program: 'powershell.exe', args: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', payload], payload});
  }
  const payload = join(payloadDir, 'deploy', 'install-chat.sh');
  const pkexec = which('pkexec');
  if (pkexec) return finish({mode: 'pkexec', program: pkexec, args: ['/bin/bash', payload, user], payload});
  const sudo = which('sudo');
  const zenity = which('zenity');
  if (sudo && zenity) return finish({mode: 'sudo-askpass', program: sudo, args: ['-A', '/bin/bash', payload, user], payload, askpass: zenity});
  return finish({mode: 'manual', program: null, args: [], payload});
}

function askpassHelper(zenity) {
  const dir = mkdtempSync(join(tmpdir(), 'dafeiyu-askpass-'));
  const helper = join(dir, 'askpass.sh');
  writeFileSync(helper, `#!/bin/sh\nexec "${zenity}" --password --title="大肥鱼监工需要管理员权限"\n`, {mode: 0o700});
  chmodSync(helper, 0o700);
  return helper;
}

function defaultSpawn(program, args, options = {}) {
  return new Promise(resolve => {
    const env = options.env || spawnEnv({platform: options.platform, mode: options.mode, askpass: options.askpass});
    const child = execFile(program, args, {env, timeout: options.timeoutMs || INSTALL_TIMEOUT_MS, maxBuffer: MAX_OUTPUT, windowsHide: true}, (error, stdout, stderr) => {
      const output = String(stdout || '') + String(stderr || '');
      if (error && (error.killed || error.signal)) return resolve({timeout: true, output});
      if (!error) return resolve({code: 0, output});
      resolve({code: typeof error.code === 'number' ? error.code : 1, output});
    });
    child.on('error', error => resolve({code: 127, output: String(error.message || error)}));
  });
}

export function runnerPath(platform = process.platform, base = process.env) {
  if (platform === 'win32') {
    const root = base.SystemRoot || 'C:\\Windows';
    return `${root}\\System32;${root}\\System32\\WindowsPowerShell\\v1.0`;
  }
  return SAFE_PATH;
}

/**
 * Linux deliberately replaces the environment with a minimal PATH before elevating,
 * so the root installer never inherits a poisoned PATH or loader. Windows cannot do
 * that: an installer needs its own TEMP, USERPROFILE, ProgramData and user PATH
 * (that is where python.exe normally lives). There we only prepend the system dirs.
 */
export function spawnEnv(plan, base = process.env) {
  if (plan.platform !== 'win32') return {PATH: SAFE_PATH};
  // A host started by a service or scheduled task may carry only a minimal environment.
  // Windows installers cannot run without these, and a missing ProgramData silently
  // installs the service at the drive root instead of %ProgramData%\Dafeiyu.
  const root = base.SystemRoot || base.windir || 'C:\\Windows';
  const env = {...base,
    PATH: [runnerPath('win32', base), base.PATH].filter(Boolean).join(';'),
    SystemRoot: root,
    ProgramData: base.ProgramData || 'C:\\ProgramData',
    ComSpec: base.ComSpec || `${root}\\System32\\cmd.exe`,
    PATHEXT: base.PATHEXT || '.COM;.EXE;.BAT;.CMD'};
  if (plan.mode === 'sudo-askpass' && plan.askpass) {
    try { env.SUDO_ASKPASS = askpassHelper(plan.askpass); } catch { /* sudo will fall back to its terminal prompt */ }
  }
  return env;
}

export async function runInstall(plan, options = {}) {
  const spawn = options.spawn || defaultSpawn;
  if (!plan.program) return {ok: false, cancelled: false, manual: true, output: '', command: plan.command};
  const env = options.env || spawnEnv(plan, options.baseEnv || process.env);
  const result = await spawn(plan.program, plan.args, {env, timeoutMs: options.timeoutMs || INSTALL_TIMEOUT_MS, platform: plan.platform, mode: plan.mode, askpass: plan.askpass});
  const output = String((result && result.output) || '').slice(-MAX_OUTPUT);
  if (result && result.timeout) return {ok: false, cancelled: false, timeout: true, output, command: plan.command};
  const code = result && typeof result.code === 'number' ? result.code : 1;
  if (code === 0) return {ok: true, code: 0, output};
  if (code === 126 || code === 127) return {ok: false, cancelled: true, code, output, command: plan.command};
  return {ok: false, cancelled: false, code, output, command: plan.command};
}

export function setupStatus(options = {}) {
  const platform = options.platform || process.platform;
  const payload = payloadStatus(options.payloadDir || PAYLOAD_DIR);
  const artifacts = installArtifacts(platform);
  const plan = elevationPlan({platform, payloadDir: options.payloadDir || PAYLOAD_DIR, which: options.which, user: options.user});
  const reachable = options.reachable === true;
  const present = options.force === true ? false : (artifacts.installed || reachable);
  return {
    installed: present,
    required: !present,
    install_path: artifacts.path,
    payload: {present: payload.present, verified: payload.verified, digest: payload.digest || null, expected: payload.expected || null,
      file_count: payload.file_count || 0, reason: payload.reason || null},
    elevation: plan.mode,
    installer: plan.payload,
    command: plan.command || installCommand(plan),
  };
}
