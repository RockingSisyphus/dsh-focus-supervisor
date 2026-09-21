// 功能：采集真实窗口元数据；只有收到短时截图授权请求时才抓取桌面像素。
import GLib from 'gi://GLib'; // 读取时钟和私有缓存路径。
import Gio from 'gi://Gio'; // 使用本地文件与输出流。
import Shell from 'gi://Shell'; // 读取应用身份和原生截图接口。
import * as Main from 'resource:///org/gnome/shell/ui/main.js'; // 由合成器激活窗口需要它。
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js'; // GNOME 45+ 扩展入口。
import {visibleIds} from './visibility.js';

const CODE_VERSION = 'dafeiyu-10'; // 实际加载版本供正式更新验收。
const REQUEST_TTL_MAX = 3; // 一次性请求只接受 3 秒内有效的。

export default class FocusDemoObserver extends Extension { // 原生 GNOME 采集适配器，仍需对应版本实机验证。
    enable() { // 功能：注册窗口采样，不默认截图。
        this.directory = GLib.build_filenamev([GLib.get_user_cache_dir(), 'focus-demo']); // 仅使用固定私有目录。
        GLib.mkdir_with_parents(this.directory, 0o700); // 禁止其他普通用户访问缓存。
        this.file = Gio.File.new_for_path(this.directory+'/gnome-snapshot.json'); // 主窗口快照路径。
        this.screenFiles = []; this.nativeImages = {}; this.windowCursor = 0; this.nativeFiles = new Set(); // 轮转窗口截图，缓存只用于本次授权。
        this.lastMinimizeId = null; // 每个最小化请求最多执行一次。
        this.lastFocusId = null; // 每个置前请求最多执行一次。
        this.busy = false; this.lastShot = 0; this.shotWindows = ''; this.image = null; this.stopped = false; // 截图单飞并记录实际时刻。
        this.enabledAt = Date.now()/1000; // 供自证文件报告"这一版跑了多久"。
        this.writeState(null); // 启用即留痕：调用方据此确认 Shell 里跑的是哪一版代码。
        this.timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, () => { // 半秒观察一次真实窗口。
            try { this.capture(); } catch (error) { console.error('FocusDemo: '+error.message); } // 错误不崩溃整个桌面。
            return GLib.SOURCE_CONTINUE; // 保持低频采样。
        }); // 注册完成。
    } // 结束启动。
    writeJson(name, value) { // 功能：把自证/动作记录写到固定私有目录，失败只记录不抛出。
        try {
            Gio.File.new_for_path(this.directory+'/'+name).replace_contents(new TextEncoder().encode(JSON.stringify(value)),null,false,Gio.FileCreateFlags.PRIVATE,null);
        } catch (error) { console.error('FocusDemo write '+name+': '+error.message); }
    } // 结束写文件。
    writeState(lastError) { // 功能：扩展是否在跑、跑的哪一版、有没有出错——调用方唯一的判据。
        this.writeJson('extension-state.json', {at:Date.now()/1000,code_version:CODE_VERSION,enabled_at:this.enabledAt,last_error:lastError});
    } // 结束自证。

    readRequest() { // 功能：截图必须由当前运行的采集器显式请求。
        try { // 缺少请求或过期时不采集像素。
            const [ok, bytes] = Gio.File.new_for_path(this.directory+'/capture-request.json').load_contents(null); // 只读取固定请求文件。
            const request = ok ? JSON.parse(new TextDecoder().decode(bytes)) : {}; // 解析有限请求数据。
            this.screenshotInterval=request.sampling?.native_screenshot_interval_seconds ?? 5;
            return request.screenshots === true && request.expires_at > Date.now()/1000; // 不能因历史授权永久截图。
        } catch (_) { return false; } // 失败时不截图。
    } // 结束授权检查。
    processMinimize() { // 功能：固定窗口最小化请求，不接受任意 JavaScript 或 Shell。
        try { // 缺少授权请求时不操作任何窗口。
            const file=Gio.File.new_for_path(this.directory+'/minimize-request.json'); // 只读固定缓存位置。
            const [ok,bytes]=file.load_contents(null); if(!ok || bytes.length>8192) return; // 有界输入。
            const request=JSON.parse(new TextDecoder().decode(bytes)); // 数据不是代码。
            if(typeof request.id!=='string' || request.id===this.lastMinimizeId || request.expires_at<Date.now()/1000 || request.expires_at>Date.now()/1000+3) return; // 拒绝重放或异常期限。
            this.lastMinimizeId=request.id; // 先消费编号，不在失败后重复执行。
            const window=global.get_window_actors().map(a=>a.meta_window).find(w=>'gnome:'+w.get_stable_sequence()===request.window_id); // 精确窗口定位。
            const checks={found:!!window,pid_match:!!window && window.get_pid()===request.pid,already_minimized:!!window && window.minimized}; // 逐项留痕，便于事后判断为什么没最小化。
            const refused=!window?'窗口已不存在':(!checks.pid_match?'进程号已变':'已经处于最小化状态'); // 只在真正拒绝时给理由。
            if(!window || !checks.pid_match) { this.writeJson('minimize-result.json',{request_id:request.id,code_version:CODE_VERSION,at:Date.now()/1000,window_id:request.window_id,acted:false,reason:refused,...checks}); return; } // 身份仍是最低门禁；可见性与标题不再作为条件。
            if(checks.already_minimized) { this.writeJson('minimize-result.json',{request_id:request.id,code_version:CODE_VERSION,at:Date.now()/1000,window_id:request.window_id,acted:false,already_minimized:true,reason:refused,...checks}); return; } // 只要求目标尚未最小化。
            this.writeJson('minimize-result.json',{request_id:request.id,code_version:CODE_VERSION,at:Date.now()/1000,window_id:request.window_id,acted:true,reason:'已请求最小化',...checks}); // 无论成败都留痕。
            window.minimize(); // 只最小化窗口：不动进程、不丢数据。
        } catch (_) {} // 失败保持原状，由采集器复查窗口是否已最小化。
    } // 结束最小化处理。
    processClose() {
        const file=Gio.File.new_for_path(this.directory+'/close-request.json');
        if(!file.query_exists(null)) return;
        const [ok,bytes]=file.load_contents(null);
        if(!ok || bytes.length>8192) return;
        const request=JSON.parse(new TextDecoder().decode(bytes)), now=Date.now()/1000;
        if(typeof request.id!=='string' || request.id===this.lastCloseId || request.expires_at<now || request.expires_at>now+3) return;
        this.lastCloseId=request.id;
        const window=global.get_window_actors().map(a=>a.meta_window).find(w=>'gnome:'+w.get_stable_sequence()===request.window_id);
        const matched=!!window && window.get_pid()===request.pid;
        if(matched) window.delete(global.get_current_time());
        this.writeJson('close-result.json',{request_id:request.id,window_id:request.window_id,requested:matched,already_closed:!window,at:now});
    }
    processFocus() { // 功能：固定窗口置前请求，不接受任意 JavaScript 或 Shell。
        try { // 缺少请求时不操作任何窗口。
            const file=Gio.File.new_for_path(this.directory+'/focus-request.json'); // 只读固定缓存位置。
            const [ok,bytes]=file.load_contents(null); if(!ok || bytes.length>8192) return; // 有界输入。
            const request=JSON.parse(new TextDecoder().decode(bytes)); // 数据不是代码。
            if(typeof request.id!=='string' || request.id===this.lastFocusId) return; // 拒绝重放。
            const now=Date.now()/1000; // 与写入方同一时钟。
            if(!(request.expires_at>now && request.expires_at<=now+REQUEST_TTL_MAX)) return; // 只接受短时有效请求。
            if(typeof request.marker!=='string' || request.marker.length<3 || request.marker.length>120) return; // 只接受受控标记。
            this.lastFocusId=request.id; // 先消费编号，失败后不重复执行。
            const actors=global.get_window_actors().map(a=>a.meta_window); // 本轮真实窗口。
            let window=actors.find(w=>'gnome:'+w.get_stable_sequence()===request.window_id); // 先按稳定窗口编号精确定位。
            let locatedBy=window?'window_id':null; // 记录定位依据，供事后核对。
            if(!window && request.pid) // 标题不跟随页面的浏览器（或目标页在后台标签页）只能靠进程号认窗口。
                for(const candidate of actors) if(candidate.get_pid()===request.pid){window=candidate;locatedBy='pid';break;}
            const markerMatch=!!window && (window.get_title()||'').includes(request.marker); // 标题里的标记是最强证据。
            const pidMatch=!!window && !!request.pid && window.get_pid()===request.pid; // 进程号命中同样授权：调用方已经用它定位过窗口。
            const record={request_id:request.id,code_version:CODE_VERSION,at:now,window_id:request.window_id,pid:request.pid||null,located_by:locatedBy,found:!!window,marker_match:markerMatch,pid_match:pidMatch,acted:false,reason:''}; // 无论成败都留痕。
            if(!window) record.reason='window-not-found'; // 找不到窗口。
            else if(!markerMatch && !pidMatch) record.reason='marker-mismatch'; // 同句柄换成了别的窗口：不置前。
            else {
                try { // 合成器接口差异必须如实记录。
                    if(window.minimized) window.unminimize(); // 最小化窗口先还原。
                    Main.activateWindow(window); // 交由合成器激活；是否立刻置前仍服从 GNOME 的防抢焦点策略。
                    record.acted=true; record.reason='activateWindow'; // 只声明"我调用了"，成功与否由调用方读快照验证。
                } catch (error) { record.reason='error: '+error.message; } // 失败原因可见。
            }
            this.writeJson('last-focus.json', record); // 调用方据此区分"扩展没跑"与"扩展跑了但合成器拒绝"。
        } catch (_) {} // 失败保持窗口不动。
    } // 结束置前处理。
    capture() { // 功能：读取实际窗口列表、应用和焦点。
        try { this.processClose(); } catch(error) { console.error('FocusDemo close: '+error.message); }
        try { this.processMinimize(); } catch (error) { console.error('FocusDemo minimize: '+error.message); } // 一件出错不影响整轮采样。
        try { this.processFocus(); } catch (error) { console.error('FocusDemo focus: '+error.message); } // 只处理一次性置前请求。
        const workspace = global.workspace_manager.get_active_workspace(); // 当前工作区。
        const tracker = Shell.WindowTracker.get_default(); // 获取 GNOME 应用映射。
        const actors = global.get_window_actors();
        const windows = global.display.sort_windows_by_stacking(actors.map(a => a.meta_window)).map(window => {
            const actor = actors.find(a => a.meta_window === window); // 不使用标题推断实际进程。
            const rect = window.get_frame_rect(); // 读取原生窗口与外框。
            const mapped = !window.minimized && window.located_on_workspace(workspace) && window.showing_on_its_workspace(); // 排除后台工作区。
            return {id:'gnome:'+window.get_stable_sequence(),app:tracker.get_window_app(window)?.get_id() || window.get_wm_class() || 'unknown',title:window.get_title() || '',pid:window.get_pid(),focused:global.display.focus_window===window,mapped,minimized:window.minimized,visible:mapped && actor.visible,visible_fraction_estimate:null,rect:[rect.x,rect.y,rect.width,rect.height],buffer_rect:(r=>[r.x,r.y,r.width,r.height])(window.get_buffer_rect()),native_capture:this.nativeImages['gnome:'+window.get_stable_sequence()] || null}; // 可见性仅为候选，不假装精确遮挡。
        }); // 得到本轮元数据。
        const screen = [0,0,global.stage.width,global.stage.height]; // 截图使用逻辑桌面坐标映射。
        const visible=visibleIds(windows,screen);
        this.visibleWindows=visible;
        const snapshot = {ts:Date.now()/1000,backend:'gnome',stacking_order:'bottom_to_top',windows,screen,screen_capture:this.image,limitations:['GNOME 可见性是候选；截图异步且可能包含遮挡窗口；该版本适配尚须实机核验。']}; // 始终标注缺口。
        this.writeState(null); // 每轮心跳一次自证：调用方据此判断扩展是否真的还在跑（锁屏会让 Shell 停掉扩展）。
        this.file.replace_contents(new TextEncoder().encode(JSON.stringify(snapshot)),null,false,Gio.FileCreateFlags.PRIVATE,null); // 原子保存窗口快照。
        const windowSet = JSON.stringify(windows.filter(w => w.mapped).map(w => [w.id,w.pid,w.title,w.rect]).sort((a,b) => a[0].localeCompare(b[0])));
        // Capture identity changes promptly; unchanged desktops keep the periodic cadence.
        if (this.readRequest() && !this.busy && (windowSet !== this.shotWindows || Date.now()-this.lastShot > this.screenshotInterval*1000)) {
            this.shotWindows = windowSet;
            this.takeScreenshot(windows,screen);
        }
    } // 结束观察。
    async takeScreenshot(windows,screen) { // 功能：使用 GNOME 原生接口，不依赖 XWayland 局部画面。
        this.busy = true; this.lastShot = Date.now(); // 防止重叠请求。
        const filename = 'screen-'+this.lastShot+'.png'; // 使用唯一名称，避免旧元数据读到被覆盖的新画面。
        const target = Gio.File.new_for_path(this.directory+'/'+filename); // 固定目录与文件名。
        let stream = null; // 在 finally 中释放输出流。
        try { // 不同 Shell 版本可能不兼容，必须报告而非伪造截图。
            stream = target.replace(null,false,Gio.FileCreateFlags.PRIVATE,null); // 创建私有 PNG 输出流。
            const shooter = new Shell.Screenshot(); // 原生截图服务对象。
            const result = shooter.screenshot(false,stream); // 当前 Shell 对此异步方法通常已经提供 Promise 包装。
            if (!result || typeof result.then !== 'function') throw new Error('当前 Shell 未提供预期的截图 Promise 接口'); // 不假报不兼容版本已成功。
            await result; // 等待实际像素写入。
            await this.takeWindows(); // 同轮补取原生窗口画面，不切换焦点。
            stream.close(null); stream=null; // 写入完成后才公开元数据。
            if (!this.stopped) { this.image = {file:filename,captured_at:this.lastShot/1000,windows,screen}; this.screenFiles.push(filename); while(this.screenFiles.length>3) try { Gio.File.new_for_path(this.directory+'/'+this.screenFiles.shift()).delete(null); } catch (_) {} } // 绑定截图启动时的窗口状态。
        } catch (error) { // 权限、版本、文件错误都可见。
            this.image = null; console.error('FocusDemo screenshot: '+error.message); // 明确不可用状态。
        } finally { // 不让失败导致截图永远忙碌。
            if (stream) try { stream.close(null); } catch (_) {} // 关闭未完成输出流。
            this.busy=false; // 允许下一轮重试。
        } // 结束截图。
    } // 结束截图方法。
    async takeWindows() { // 功能：每批轮转四个映射窗口；没有逐个应用的专门逻辑。
        const actors = global.get_window_actors().filter(a => !a.meta_window.minimized && this.visibleWindows?.has('gnome:'+a.meta_window.get_stable_sequence()));
        const alive = new Set(actors.map(a => 'gnome:'+a.meta_window.get_stable_sequence())); // 清理已关闭窗口的临时截图。
        for (const key of Object.keys(this.nativeImages)) if (!alive.has(key)) { // 不留无限增长的历史文件。
            const prefix = 'window-'+key.slice('gnome:'.length)+'-';
            for (const file of this.nativeFiles) if (file.startsWith(prefix)) {
                try { Gio.File.new_for_path(this.directory+'/'+file).delete(null); } catch (_) {}
                this.nativeFiles.delete(file);
            }
            delete this.nativeImages[key]; // 移除失效索引。
        } // 结束清理。
        for (let n=0;n<Math.min(4,actors.length);n++) { // 只在每轮预算内取证。
            const actor = actors[(this.windowCursor+n)%actors.length]; const window = actor.meta_window; // 原生窗口定位。
            const id = 'gnome:'+window.get_stable_sequence(); const rect = window.get_frame_rect(); // 绑定窗口身份和位置。
            const filename = 'window-'+window.get_stable_sequence()+'-'+Date.now()+'.png'; let stream=null; // 一个窗口一个覆盖式缓存。
            try { // 接口版本差异不能使 Shell 崩溃。
                const content=actor.paint_to_content(null); const texture=content.get_texture(); // 读取窗口自身纹理，不裁剪桌面遮挡。
                stream=Gio.File.new_for_path(this.directory+'/'+filename).replace(null,false,Gio.FileCreateFlags.PRIVATE,null); // 私有输出。
                const result=Shell.Screenshot.composite_to_stream(texture,0,0,-1,-1,1,null,0,0,1,stream); // 将纹理导出 PNG。
                if (!result || typeof result.then !== 'function') throw new Error('窗口截图 Promise 接口不可用'); // 不假报成功。
                await result; stream.close(null);stream=null; // 完整写入后发布。
                if (!this.stopped) this.nativeImages[id]={file:filename,window_id:id,pid:window.get_pid(),title:window.get_title() || '',rect:[rect.x,rect.y,rect.width,rect.height],captured_at:Date.now()/1000}; // 数据与实际采集时刻绑定。
                this.nativeFiles.add(filename);
                // Keep preceding frames until metadata readers have consumed them.
                const history = [...this.nativeFiles].filter(file => file.startsWith('window-'+window.get_stable_sequence()+'-'));
                for (const file of history.slice(0,-3)) {
                    try { Gio.File.new_for_path(this.directory+'/'+file).delete(null); } catch (_) {}
                    this.nativeFiles.delete(file);
                }
            } catch (error) { delete this.nativeImages[id];console.error('FocusDemo window: '+error.message); } // 失败由上层明确回退。
            finally { if(stream) try { stream.close(null); } catch (_) {} } // 释放输出流。
        } // 结束有限批次。
        this.windowCursor=(this.windowCursor+4)%Math.max(1,actors.length); // 多窗口公平覆盖，不固定只读前几个。
    } // 结束窗口采集。
    disable() { // 功能：立即停止观察，锁屏/禁用时不留下可误用的快照。
        this.stopped=true; // 异步截图完成后也不得再发布。
        this.writeJson('extension-disabled.json', {at:Date.now()/1000,code_version:CODE_VERSION,uptime_seconds:Math.round(Date.now()/1000-(this.enabledAt||Date.now()/1000))}); // 留一条"谁停的、跑了多久"：锁屏会走到这里。
        if(this.timer){GLib.source_remove(this.timer);this.timer=null;} // 取消定时器。
        for(const name of ['gnome-snapshot.json',...this.screenFiles,...this.nativeFiles]) try { Gio.File.new_for_path(this.directory+'/'+name).delete(null); } catch (_) {} // 清除陈旧快照。
        this.file=null;this.image=null; // 释放本地状态。
    } // 结束停用。
} // 结束扩展。
