/** 弹窗按钮端到端夹具的 host 半。
 *
 * 这里跑的是插件**真实的** host 半（`dsh-plugin/chat-host.mjs` 的 `/focus/*` 路由），只把
 * DSH 宿主换成桩：状态来自一个假后端 unix socket，页面入口由本进程提供。这样弹窗按钮出问题
 * 时，测试打的是发货代码，不是复制品。
 *
 * 用法：node tests/popup_e2e/host.mjs --session session-target
 * 启动后打印一行 `HOST {"port":…,"token":…}`，供驱动读取。
 */
import http from 'node:http';
import {mkdtemp, readFile, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {apply} from '../../dsh-plugin/chat-host.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const CLIENT = path.join(HERE, '..', '..', 'dsh-plugin', 'client.js');

function option(name, fallback) {
  const index = process.argv.indexOf('--' + name);
  return index === -1 ? fallback : process.argv[index + 1];
}

const session = option('session', 'session-target');
const projectDir = option('project', '/tmp/project');
// 夹具跑的是真实 host 半，它会往 DSH_HOME 写 dafeiyu-chat-endpoint.json。不隔离就会把真机
// 的"弹窗该找哪个地址"改成夹具的随机端口，而真插件只在端口变化时才写一次、不会自己改回来——
// 2026-09-19 就是这样让用户点开工提醒时弹窗去问一个死地址的。这里一律指向临时目录。
const dshHome = await mkdtemp(path.join(os.tmpdir(), 'dafeiyu-popup-home-'));
process.env.DSH_HOME = dshHome;
const state = {
  running: false, interval: 600, live: [], notices: [], alerts: [], events: [], reports: [],
  tasks: [{id: 'task-1', session_id: session, project_dir: projectDir, status: 'active'}],
  settings: {id: 'global', instructions: '# 摘要', heartbeat_prompt: '心跳', mascot_size: 144},
  desktop_setup: null, presence: {available: false},
};

const dir = await mkdtemp(path.join(os.tmpdir(), 'dafeiyu-popup-'));
const sock = path.join(dir, 'agent.sock');
const backend = http.createServer((req, res) => {
  let body = '';
  req.on('data', (chunk) => { body += chunk; });
  req.on('end', () => {
    res.writeHead(200, {'content-type': 'application/json'});
    res.end(JSON.stringify(req.url === '/state' ? state : {ok: true}));
  });
});
await new Promise((resolve) => backend.listen(sock, resolve));

const routes = new Map();
const inject = [];
const disposers = [];
const context = {
  effect: (fn) => { const dispose = fn(); if (dispose) disposers.push(dispose); },
  systemPrompt: {section: () => () => {}},
  tools: {register: () => {}},
  on: (name, fn) => { if (name === 'webserver/index-inject') inject.push(fn); },
  webServer: {port: 0, register: (route) => { routes.set(route.path, route.handler); return () => {}; }},
  sessionController: {resolveAgent: async () => ({agent: {session: {id: 'chat'}}}), prompt: async () => ({accepted: true})},
  connection: {authenticatedUrl: (base) => base + '?token=launch-token'},
};

const clientSource = await readFile(CLIENT, 'utf8');
const stub = await readFile(path.join(HERE, 'stub.js'), 'utf8');
const boot = await readFile(path.join(HERE, 'boot.js'), 'utf8');
// 页面半（桩 + 真实 client.js + 引导）拼成一份：node 与来宾浏览器加载的是同一份代码。
const bundle = [stub, clientSource, boot].join('\n;\n');
const page = () => '<!doctype html><meta charset="utf-8"><title>DSH 页面夹具</title>'
  + '<script>globalThis.__HARNESS__ = Object.assign({origin: location.origin},'
  + '(new URLSearchParams(location.search).get("config")'
  + ' ? JSON.parse(atob(new URLSearchParams(location.search).get("config"))) : {}));</script>'
  + '<script src="/harness/page.bundle.js"></script>';

let token = '';
// 真实的 DSH index 就是"令牌 + 应用"：这里也必须两个都给。只注入令牌的话，浏览器打开的页面
// 根本不会加载客户端半，插件看到的就是"没有页面在轮询"（来宾里踩过：pages 一直为空）。
// 令牌格式要和客户端 renewToken() 的正则对得上，否则页面拿不到令牌、/focus/* 全部 403。
const index = () => '<!doctype html><meta charset="utf-8"><title>DSH 页面夹具</title>'
  + '<script>globalThis["__DAFEIYU__"] = ' + JSON.stringify({token}) + '</script>'
  + '<script>globalThis.__HARNESS__ = Object.assign({origin: location.origin},'
  + '(new URLSearchParams(location.search).get("config")'
  + ' ? JSON.parse(atob(new URLSearchParams(location.search).get("config"))) : {}));</script>'
  + '<script src="/harness/page.bundle.js"></script>';

const started = Date.now();
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  // 每个请求留一行：页面在来宾浏览器里没登记时，这是唯一能分清"没请求"还是"请求被拒"的证据。
  res.on('finish', () => console.log('REQ ' + JSON.stringify({at: Date.now() - started,
    method: req.method, path: url.pathname, status: res.statusCode, page: req.headers['x-focus-page'] || null})));
  if (url.pathname === '/') {
    res.writeHead(200, {'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store'});
    res.end(index());
    return;
  }
  if (url.pathname === '/harness/page.html') {
    res.writeHead(200, {'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store'});
    res.end(page());
    return;
  }
  if (url.pathname === '/harness/page.bundle.js') {
    res.writeHead(200, {'content-type': 'text/javascript; charset=utf-8', 'cache-control': 'no-store'});
    res.end(bundle);
    return;
  }
  const handler = routes.get(url.pathname);
  if (!handler) {
    res.writeHead(404, {'content-type': 'application/json'});
    res.end(JSON.stringify({error: 'no route ' + url.pathname}));
    return;
  }
  Promise.resolve(handler(req, res)).catch((error) => {
    if (!res.writableEnded) {
      res.writeHead(500, {'content-type': 'application/json'});
      res.end(JSON.stringify({error: String((error && error.message) || error)}));
    }
  });
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
context.webServer.port = server.address().port;

try {
  await apply(context, {socketPath: sock, stateDirectory: path.join(dshHome, 'state')});
} catch (error) {
  console.error('HOST_ERROR ' + JSON.stringify({error: String((error && error.message) || error)}));
  process.exit(1);
}
const table = [];
for (const fn of inject) fn(table);
token = table.find((item) => item.name === '__DAFEIYU__')?.value?.token;
if (!token) throw new Error('页面拿不到插件令牌：index 注入没有生效');

console.log('HOST ' + JSON.stringify({port: context.webServer.port, token, session,
  origin: 'http://127.0.0.1:' + context.webServer.port}));

const shutdown = async () => {
  for (const dispose of disposers.reverse()) try { dispose(); } catch {}
  server.close(); backend.close();
  await rm(dir, {recursive: true, force: true});
  process.exit(0);
};
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
