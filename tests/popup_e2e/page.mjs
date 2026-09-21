/** 在 node 里跑一遍"页面半"：加载夹具 host 提供的同一份页面代码（桩 + 真实 client.js + 引导）。
 *
 * 用法：node tests/popup_e2e/page.mjs --origin http://127.0.0.1:PORT --session session-x --shape modern
 * 启动后按行打印 `PAGE {json}`，驱动据此判定会话是否切换、标记是否打上。
 */
const option = (name, fallback) => {
  const index = process.argv.indexOf('--' + name);
  return index === -1 ? fallback : process.argv[index + 1];
};

const origin = option('origin');
const session = option('session', 'session-target');
const shape = option('shape', 'modern');
const pageId = option('page-id', 'node-page');
if (!origin) throw new Error('缺少 --origin');

globalThis.__HARNESS__ = {origin, session, shape, pageId};
// 浏览器会自动把相对地址解析到当前 origin；node 的 fetch 不会，这里补上，其余一律照旧。
// 同时把每次请求的结局记下来：页面里出问题时，驱动看得到是哪一步 403 还是抛错。
const rawFetch = globalThis.fetch;
globalThis.fetch = async (input, init) => {
  const url = typeof input === 'string' && input.startsWith('/') ? origin + input : input;
  try {
    const response = await rawFetch(url, init);
    console.log('FETCH ' + JSON.stringify({url: String(url), status: response.status}));
    return response;
  } catch (error) {
    console.log('FETCH ' + JSON.stringify({url: String(url), error: String((error && error.message) || error)}));
    throw error;
  }
};

const source = await rawFetch(origin + '/harness/page.bundle.js').then((response) => {
  if (!response.ok) throw new Error('取页面代码失败：' + response.status);
  return response.text();
});
(0, eval)(source);

// 页面半自己带 setInterval 的轮询与常驻通道，这里只需要保持进程活着。
setInterval(() => {}, 1000);
