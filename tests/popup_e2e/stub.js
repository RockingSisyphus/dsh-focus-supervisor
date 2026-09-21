/** 页面桩：让真实的 `dsh-plugin/client.js` 在 node 与来宾浏览器里都能跑起来。
 *
 * 只替换 DSH 提供的宿主能力（React、会话服务、document），产品逻辑一行都不改：这样
 * 「弹窗按钮」坏掉时，测试挂的是发货代码本身。会话服务提供三种形态，对应这次踩过的坑：
 *   modern —— 0.1.6：视图选择不在会话列表里，只有 retainInfo(id).retainedBy.mainView 能看
 *   legacy —— 0.1.5 及更早：会话列表里有 current
 *   stuck  —— 切换请求发出去了，但主视图始终没有保留目标会话（必须如实报失败）
 */
(function () {
  const config = globalThis.__HARNESS__ || {};
  globalThis.window = globalThis;
  const harness = {config, events: [], cleanups: [], renders: 0};
  globalThis.__HARNESS_STATE__ = harness;

  const React = {
    useState(initial) { const value = typeof initial === 'function' ? initial() : initial; return [value, function () {}]; },
    useEffect(fn) {
      try { const cleanup = fn(); if (typeof cleanup === 'function') harness.cleanups.push(cleanup); }
      catch (error) { harness.events.push({event: 'effect-error', error: String((error && error.message) || error)}); }
    },
    useRef(initial) { return {current: initial}; },
    useMemo(fn) { return fn(); },
    useCallback(fn) { return fn; },
    createElement: (type, props, ...children) => ({type, props, children}),
    createContext: () => ({Provider: null}),
    Fragment: '#fragment',
  };
  harness.React = React;

  harness.makeSessions = function () {
    const target = config.session || 'session-target';
    const shape = config.shape || 'modern';
    let retainedId = null;
    const rows = {byId: {}, current: shape === 'legacy' ? 'session-other' : undefined};
    const sessions = {
      // 页面调用 uiWorkspace.openSession() 之后，DSH 的视图层会去"保留"目标会话。
      land(id) {
        if (id !== target) return;
        if (shape === 'legacy') { rows.current = id; return; }
        if (shape === 'stuck') return;                 // 请求发出去了，视图永远不落地
        setTimeout(() => { retainedId = id; }, 60);     // 主视图渲染有一点点延迟
      },
      list: {getSnapshot: () => rows},
    };
    if (shape !== 'legacy') {
      sessions.retainInfo = (id) => ({getSnapshot: () => ({retainedBy: {mainView: retainedId === id ? 1 : 0}})});
    }
    return sessions;
  };

  if (typeof globalThis.document === 'undefined') {
    const element = {style: {}, setAttribute() {}, appendChild() {}};
    globalThis.document = {visibilityState: 'visible', title: 'DSH 会话页夹具',
      querySelector: () => null, getElementById: () => null, createElement: () => element,
      addEventListener() {}, removeEventListener() {}, body: element};
  }
  if (typeof globalThis.MutationObserver === 'undefined') {
    globalThis.MutationObserver = class { observe() {} disconnect() {} takeRecords() { return []; } };
  }
  if (typeof globalThis.localStorage === 'undefined') {
    globalThis.localStorage = {getItem: () => null, setItem() {}, removeItem() {}};
  }
  // 组件按浏览器尺寸排版；node 里补上这几个浏览器全局，浏览器里本来就有。
  if (typeof globalThis.innerWidth === 'undefined') {
    globalThis.innerWidth = 1920;
    globalThis.innerHeight = 1080;
    globalThis.devicePixelRatio = 1;
  }
  if (typeof globalThis.addEventListener !== 'function') {
    globalThis.addEventListener = () => {};
    globalThis.removeEventListener = () => {};
  }
  globalThis.__ModuleLoader__ = {load(registration) { harness.registration = registration; }};
})();
