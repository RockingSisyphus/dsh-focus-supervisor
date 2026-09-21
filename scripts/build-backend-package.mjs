/**
 * Stage the supervisor backend inside the plugin package so a marketplace install
 * can finish itself after one admin authorization.
 *
 *   node scripts/build-backend-package.mjs        # 生成 dsh-plugin/backend + manifest.json
 *
 * install-chat.sh resolves its source tree as "<dir>/..", so the staged copy
 * mirrors the repository shape: backend/{focus_demo,deploy,gnome-extension,
 * requirements.txt,dsh-plugin/assets}. manifest.json pins the tree digest and is
 * excluded from that digest (it cannot contain its own hash).
 */
import {createHash} from 'node:crypto';
import {cpSync, existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {dirname, join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const PLUGIN = join(ROOT, 'dsh-plugin');
const TARGET = join(PLUGIN, 'backend');
// windows_service.py 是 Windows 计划任务真正执行的那个文件，漏掉它会让装好的
// 后台永远起不来（Linux 侧对应 chat_service.py）。
const DEPLOY_FILES = ['chat_service.py', 'chat_sensor.py', 'windows_service.py', 'desktop_setup.py', 'desktop_notify.py', 'desktop_notify_windows.py',
  'retire_legacy.py', 'open_chat.py', 'focus_window.py', 'install-chat.sh', 'upgrade-chat.sh', 'install-windows.ps1'];
const IGNORE = /(^|[/\\])(__pycache__|node_modules|\.venv|\.pytest_cache)([/\\]|$)|\.pyc$/;

export function treeDigest(dir) {
  const files = [];
  const walk = (current) => {
    for (const name of readdirSync(current).sort()) {
      const full = join(current, name);
      const rel = relative(dir, full).split('\\').join('/');
      if (IGNORE.test(full)) continue;
      const info = statSync(full);
      if (info.isDirectory()) walk(full);
      else if (info.isFile() && rel !== 'manifest.json') files.push([rel, createHash('sha256').update(readFileSync(full)).digest('hex')]);
    }
  };
  walk(dir);
  const hash = createHash('sha256');
  for (const [name, digest] of files) hash.update(name + '\0' + digest + '\n');
  return {files, digest: hash.digest('hex')};
}

export function build() {
  rmSync(TARGET, {recursive: true, force: true, maxRetries: 10, retryDelay: 200});
  mkdirSync(join(TARGET, 'deploy'), {recursive: true});
  cpSync(join(ROOT, 'focus_demo'), join(TARGET, 'focus_demo'), {recursive: true, filter: source => !IGNORE.test(source)});
  mkdirSync(join(TARGET, 'dsh-plugin'), {recursive: true});
  cpSync(join(PLUGIN, 'default-prompts.json'), join(TARGET, 'dsh-plugin', 'default-prompts.json'));
  for (const name of DEPLOY_FILES) {
    const source = join(ROOT, 'deploy', name);
    if (existsSync(source)) cpSync(source, join(TARGET, 'deploy', name));
  }
  // GNOME 采集扩展只在 Linux 需要；缺少时照常打包（Windows 安装器不使用它）。
  if (existsSync(join(ROOT, 'gnome-extension'))) {
    cpSync(join(ROOT, 'gnome-extension'), join(TARGET, 'gnome-extension'), {recursive: true, filter: source => !IGNORE.test(source)});
  }
  cpSync(join(ROOT, 'requirements.txt'), join(TARGET, 'requirements.txt'));
  // 插件包根目录已经有 assets/，嵌入的安装脚本改为引用它，避免包体重复 17MB。
  // Windows 安装器用反斜杠，且缺少这条重写会让它在 backend\dsh-plugin\assets 找不到资源。
  for (const [name, marker, replacement] of [
    ['install-chat.sh', '"$source_dir/dsh-plugin/assets"', '"$source_dir/../assets"'],
    ['upgrade-chat.sh', '"$source_dir/dsh-plugin/assets"', '"$source_dir/../assets"'],
    ['install-windows.ps1', '"$source\\dsh-plugin\\assets"', '"$source\\..\\assets"'],
  ]) {
    const staged = join(TARGET, 'deploy', name);
    if (!existsSync(staged)) continue;
    const text = readFileSync(staged, 'utf8');
    if (!text.includes(marker)) throw new Error(`${name} 中未找到资源复制行，打包脚本需要同步更新`);
    writeFileSync(staged, text.split(marker).join(replacement));
  }
  // Windows PowerShell 5.1 把无 BOM 的 .ps1 当 ANSI 读，中文诊断会被解成乱码并直接
  // 解析失败（安装器一个字都没执行）。这里统一补 BOM，避免改文件的人忘了它。
  for (const name of readdirSync(join(TARGET, 'deploy'))) {
    if (!name.endsWith('.ps1')) continue;
    const staged = join(TARGET, 'deploy', name);
    const text = readFileSync(staged, 'utf8').replace(/^\uFEFF/, '');
    writeFileSync(staged, '\uFEFF' + text);
  }
  const {files, digest} = treeDigest(TARGET);
  writeFileSync(join(TARGET, 'manifest.json'), JSON.stringify({
    payload_sha256: digest,
    files: files.map(([name]) => name),
    note: '构建时由 scripts/build-backend-package.mjs 生成；树摘要不含本清单自身。',
  }, null, 2) + '\n');
  rmSync(join(TARGET, 'deploy', 'install-chat.sh.bak'), {force: true});
  return {digest, files: files.length, bytes: files.reduce((total, [name]) => total + statSync(join(TARGET, name)).size, 0)};
}

const invokedDirectly = (() => {
  try { return !!process.argv[1] && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url); }
  catch { return false; }
})();
if (invokedDirectly) {
  try {
    const {digest, files, bytes} = build();
    console.log(`后端载荷已就绪：${files} 个文件，${(bytes / 1024).toFixed(0)} KB，摘要 ${digest.slice(0, 16)}…`);
    console.log(`目录：${TARGET}`);
  } catch (error) {
    console.error('后端载荷打包失败：' + String((error && error.stack) || error));
    process.exitCode = 1;
  }
}
