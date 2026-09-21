/** 页面引导：注册真实客户端半、跑一次组件、把关键事实报给驱动。
 *
 * 报出来的事实就是判定依据：页面自己回报的会话、是否真的打上交接标记、
 * 用的是哪几条切换判据、失败原因。驱动（pytest 或来宾脚本）只读这些，不猜。
 */
(function () {
  const harness = globalThis.__HARNESS_STATE__;
  const config = harness.config || {};
  const emit = (event) => {
    harness.events.push(event);
    if (typeof process !== 'undefined' && process.stdout) console.log('PAGE ' + JSON.stringify(event));
  };
  if (!harness.registration) { emit({event: 'no-registration'}); return; }

  let component = null;
  const sessions = harness.makeSessions();
  const ctx = {
    get: (name) => (name === 'sessions' ? sessions : undefined),
    slots: {
      inject: (_slot, fn) => { try { fn(); } catch (error) { emit({event: 'inject-error', error: String((error && error.message) || error)}); } },
      register: (_meta, registered) => { component = registered; },
    },
    uiWorkspace: {openSession: (id) => { emit({event: 'open-session', session: id}); sessions.land(id); }},
  };
  let exported = null;
  try {
    exported = harness.registration.factory((name) => {
      if (name === 'react') return harness.React;
      throw new Error('页面桩没有准备这个依赖：' + name);
    });
  } catch (error) { emit({event: 'factory-error', error: String((error && error.message) || error)}); return; }
  try { exported.apply(ctx); } catch (error) { emit({event: 'apply-error', error: String((error && error.message) || error)}); }
  if (!component) { emit({event: 'no-component'}); return; }
  try { component(); } catch (error) { emit({event: 'render-error', error: String((error && error.message) || error)}); }
  emit({event: 'booted', shape: config.shape || 'modern', session: config.session});

  // 每次现读 __DAFEIYU__：客户端每步都会整体替换这个对象，抓早了的引用是旧的。
  globalThis.__HARNESS_REPORT__ = () => {
    const state = globalThis.__DAFEIYU__ || {};
    return {
      event: 'page',
      title: String(globalThis.document.title),
      verifiers: state.switchVerifiers || null,
      landed: state.switchLanded === true,
      focusedSession: state.focusedSession || null,
      claimError: state.claimError || null,
    };
  };
  if (typeof process !== 'undefined' && process.stdout) {
    const timer = setInterval(() => console.log('PAGE ' + JSON.stringify(globalThis.__HARNESS_REPORT__())), 250);
    if (timer.unref) timer.unref();
  }
})();
