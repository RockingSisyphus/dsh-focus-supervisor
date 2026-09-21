"""一次批量读取系统无障碍树；不编写应用专用适配、不操作控件、不记录按键。"""
import json  # 输出有来源的结构化结果。
import sys  # 系统后端选择。
import time  # 控制节点遍历预算。
from .sampling_settings import DEFAULTS
TEXT_CHARS=DEFAULTS["sampling"]["text_chars"]
TEXT_NODES=DEFAULTS["sampling"]["text_nodes"]
from collections import deque  # 有界广度优先遍历。


def overlap(a, b):  # 功能：比较系统窗口和无障碍窗口的几何，不以程序名称选择适配器。
    x = max(a[0], b[0]); y = max(a[1], b[1])  # 计算相交区域起点。
    area = max(0, min(a[0]+a[2], b[0]+b[2])-x)*max(0, min(a[1]+a[3], b[1]+b[3])-y)  # 计算交集。
    return area / max(1, a[2]*a[3]+b[2]*b[3]-area)  # 返回交并比，避免同 PID 多窗口串线。


def match_window(window, candidates):
    """候选已限定同 PID；先匹配屏幕几何，再处理 Wayland 的局部原点。"""
    rect = window.get('rect') or [0, 0, 0, 0]
    matches = sorted(((overlap(rect, c['rect']), i, c) for i, c in enumerate(candidates)), reverse=True)
    matches = [row for row in matches if row[0] > .55]
    if matches:
        if len(matches) > 1 and matches[0][0] - matches[1][0] < .1:
            return None
        return dict(matches[0][2], association='同 PID 与唯一屏幕几何匹配。')
    # GTK/Wayland 可以只提供窗口局部坐标；必须同时匹配标题和尺寸。
    matches = [c for c in candidates if c['rect'][:2] == [0, 0]
               and window.get('title') and c.get('title') == window['title']
               and all(abs(a-b) <= 2 for a, b in zip(rect[2:], c['rect'][2:]))]
    if len(matches) == 1:
        return dict(matches[0], association='同 PID、唯一标题与窗口尺寸匹配；辅助功能仅提供窗口局部坐标。')
    return None


def match_windows(windows, candidates):
    """Associate a process's native/accessibility windows as a one-to-one batch.

    Wayland may report surface-local coordinates, including shadows. Use the
    compositor buffer size there; never treat that local origin
    as a screen position or resolve duplicate titles by enumeration order.
    """
    choices={}
    for window in windows:
        rect=window.get('buffer_rect') or window.get('rect') or [0,0,0,0]
        eligible=[]
        for index,candidate in enumerate(candidates):
            if list(candidate['rect'][:2])==[0,0]:
                if any(abs(a-b)>2 for a,b in zip(rect[2:],candidate['rect'][2:])):continue
                eligible.append(index)
        if len(eligible)>1:
            titled=[index for index in eligible if window.get('title') and candidates[index].get('title')==window['title']]
            if titled:eligible=titled
        screen=[c for c in candidates if list(c['rect'][:2])!=[0,0]]
        match=match_window(window,screen)
        if match is not None:
            eligible=[i for i,c in enumerate(candidates) if c['node']==match['node']]
        choices[window['id']]=set(eligible)
    resolved={}
    while choices:
        singles=[(key,next(iter(options))) for key,options in choices.items() if len(options)==1]
        unique=[(key,index) for key,index in singles if sum(index in options for other,options in choices.items() if other!=key)==0]
        if not unique:break
        for key,index in unique:
            resolved[key]=dict(candidates[index],association='同 PID 的批量一一关联：屏幕几何或 Wayland 缓冲区尺寸与标题。')
            del choices[key]
            for options in choices.values():options.discard(index)
    # Wayland toolkits can expose identical local rectangles with no native ID.
    # Keep the readable process group instead of guessing a one-to-one mapping.
    # By user choice, this ambiguous group may include hidden-window content.
    grouped={key:options for key,options in choices.items() if options}
    if grouped:
        indexes=sorted(set().union(*grouped.values()))
        group={'nodes':[candidates[index]['node'] for index in indexes],
               'window_ids':list(grouped), 'association':'同进程窗口组：系统未提供可逐窗关联的身份；正文可能包含隐藏窗口，请结合截图自行判断归属。'}
        for key in grouped:resolved[key]=group
    return resolved


def linux_batch(windows):
    """Linux 统一使用标准 AT-SPI D-Bus，避免安装 Python 绑定后换一套采集逻辑。"""
    from .atspi_dbus import linux_batch as dbus_batch
    return dbus_batch(windows, TEXT_CHARS, TEXT_NODES)


def windows_batch(windows,emit=None):
    """UIA names, roles and state, without invoking or modifying controls."""
    sys.coinit_flags = 0  # UIA runs in this isolated MTA worker, as with pywinauto.
    from comtypes.client import GetModule, CreateObject
    from .ui_structure import describe_window, entry, ReadBudget
    api=GetModule('UIAutomationCore.dll')
    desktop=CreateObject(api.CUIAutomation,interface=api.IUIAutomation)
    condition=desktop.CreateTrueCondition()
    roles={getattr(api,name):name[4:-13].lower() for name in dir(api) if name.startswith('UIA_') and name.endswith('ControlTypeId')}
    def pattern(element,name):
        return element.GetCurrentPattern(getattr(api,'UIA_'+name+'PatternId')).QueryInterface(getattr(api,'IUIAutomation'+name+'Pattern'))
    results = {}
    budget = ReadBudget(windows[0].get('_read',{}) if windows else {})
    deadline = time.monotonic()+2.0
    for window in windows:
        result = {'text': '', 'scope': 'unavailable', 'notes': [
            'UIA 结构摘录；可能包含被遮挡/视口外文字，自绘内容请结合截图。']}
        results[window['id']] = result
        if time.monotonic()>=deadline:
            result['notes'].append('本轮无障碍时间预算已用完。')
            if emit:emit({window['id']:result})
            continue
        try:
            root = desktop.ElementFromHandle(int(window.get('native_id') or window['id'].split(':')[-1]))
            if root.CurrentProcessId != int(window['pid']): raise ValueError('HWND 所属进程改变')
            queue,nodes=deque([(root,None)]),[]
        except Exception as error:
            result['notes'].append('UIA 不可用：'+str(error)[:160])
            if emit:emit({window['id']:result})
            continue
        while queue and len(nodes)<TEXT_NODES and time.monotonic()<deadline:
            node, parent = queue.popleft()
            try:
                element = node
                if element.CurrentIsPassword or element.CurrentIsOffscreen: continue
                role = roles.get(element.CurrentControlType,'unknown')
                name = element.CurrentName or ''
                states = []
                if element.CurrentHasKeyboardFocus: states.append('focused')
                if not element.CurrentIsEnabled: states.append('disabled')
                # Read pattern state only; never call Select, Toggle, Expand, etc.
                if role in ('checkbox', 'radiobutton', 'togglebutton'):
                    try:
                        value = pattern(element,'Toggle').CurrentToggleState
                        states.append({0:'unchecked',1:'checked',2:'mixed'}[value])
                    except Exception: pass
                if role in ('tabitem', 'listitem', 'treeitem', 'radiobutton'):
                    try:
                        if pattern(element,'SelectionItem').CurrentIsSelected: states.append('selected')
                    except Exception: pass
                index = len(nodes)
                nodes.append(entry(index, parent, role, name, states=states))
                if role == 'document':
                    try:
                        uri = pattern(element, 'Value').CurrentValue
                        if uri and uri.startswith(('http:', 'https:', 'file:', 'about:', 'chrome:', 'edge:')):
                            nodes[index]['document_url'] = uri
                    except Exception:
                        pass
                readable = budget.enter(nodes[index],nodes[parent] if parent is not None else None)
                if nodes[index]['browser_document'] and not readable:continue
                try:
                    if not readable:raise ValueError('本轮仅观察窗口身份')
                    ranges = pattern(element,'Text').GetVisibleRanges()
                    chunks = [ranges.GetElement(i).GetText(3000) for i in range(min(ranges.Length, 20))]
                    body = '\n'.join(dict.fromkeys(chunks)).replace('\ufffc', '')
                    nodes[index]['text'] = body[:3000]
                    if len(body) >= 3000: nodes[index]['truncated'] = True
                    if ranges.Length > 20: result['notes'].append('文本范围超过读取上限。')
                except Exception: pass
                # Standard Win32 edits may expose ValuePattern without TextPattern;
                # Name is often the neighbouring label rather than the field value.
                if readable and role in ('edit', 'combobox', 'spinner') and not nodes[index].get('text'):
                    try:
                        body = pattern(element,'Value').CurrentValue or ''
                        nodes[index]['text'] = body[:3000]
                        if len(body) > 3000: nodes[index]['truncated'] = True
                    except Exception: pass
                collection=element.FindAll(api.TreeScope_Children,condition)
                children=[collection.GetElement(i) for i in range(min(collection.Length,101))]
                if len(children)>100: result['notes'].append('子控件超过读取上限。')
                queue.extend((child, index) for child in children[:100])
            except Exception:
                result['notes'].append('部分控件读取失败。')
        result.update(describe_window(nodes, truncated=bool(queue) or len(result['notes'])>1,limit=TEXT_CHARS))
        result['scope'] = 'accessibility_structure'
        result['notes'] = list(dict.fromkeys(result['notes']))
        if emit:emit({window['id']:result})
    return results



def mac_batch(windows):  # 功能：macOS 通过 AX API 读取；没有按应用类型分支。
    import ApplicationServices as ax  # 需要 pyobjc-framework-ApplicationServices 和辅助功能授权。
    def value(node, name):  # 读取属性失败则返回空，不操作 UI。
        error, item = ax.AXUIElementCopyAttributeValue(node, name, None)  # 系统只读查询。
        return item if error == 0 else None  # 不把错误码当数据。
    results = {}; deadline = time.monotonic()+1.0  # 全批次预算。
    for window in windows:  # 所有原生应用采用相同树结构。
        app = ax.AXUIElementCreateApplication(int(window['pid']))  # 按 PID 获取 AX 应用。
        roots = value(app, 'AXWindows') or []  # 读取可访问窗口目录。
        matches = [r for r in roots if value(r, 'AXTitle') == window.get('title')]  # PID 内标题唯一才匹配，歧义时不猜。
        if len(matches) != 1:  # 保留当前原型不能唯一匹配的缺口。
            results[window['id']] = {'text':'', 'scope':'unavailable', 'notes':['AX 在该 PID 内没有唯一窗口匹配；未附加其他窗口文字。']}  # 不合并同应用正文。
            continue  # 下一个窗口。
        output = []; queue = deque(matches); count = 0  # 有界遍历。
        while queue and count<TEXT_NODES and time.monotonic()<deadline:  # 不阻塞整轮巡检。
            node = queue.popleft(); count += 1  # 取出当前节点。
            if value(node, 'AXSubrole') == 'AXSecureTextField': continue  # 不读取密码。
            if value(node, 'AXHidden') is not True:  # 隐藏节点不读取文字。
                for name in ('AXTitle', 'AXDescription', 'AXValue'):  # 只读常见字符串属性。
                    text = value(node, name)  # 非文本属性不能随意序列化。
                    if isinstance(text, str): output.append(text[:3000])  # 可能是文档摘录，说明范围。
            queue.extend((value(node, 'AXChildren') or [])[:100])  # 限制扇出。
        results[window['id']] = {'text':'\n'.join(dict.fromkeys(output))[:12000], 'scope':'accessibility_excerpt', 'notes':['AX 摘录可能包括视口外内容；原型未在 macOS 实测，未用未授权私有接口。']}  # 不能据此证明已阅读。
    return results  # 与其他系统接口同形。


def main():  # 功能：由父进程设置硬超时，发生故障时结构化返回。
    global TEXT_CHARS,TEXT_NODES
    if "--chars" in sys.argv:TEXT_CHARS=int(sys.argv[sys.argv.index("--chars")+1])
    if "--nodes" in sys.argv:TEXT_NODES=int(sys.argv[sys.argv.index("--nodes")+1])
    batch = len(sys.argv)>1 and sys.argv[1]=='--batch'  # 保留旧单窗口入口兼容。
    windows = json.loads(sys.stdin.read(100000)) if batch else [{'id':sys.argv[2], 'native_id':int(sys.argv[2]), 'pid':int(sys.argv[1]), 'rect':[0,0,0,0], 'title':''}]  # 输入只包含窗口元数据。
    emit=(lambda result:print(json.dumps(result,ensure_ascii=True),flush=True)) if '--stream' in sys.argv else None
    try:  # 系统依赖不存在时返回覆盖缺口。
        if sys.platform.startswith('linux'): result = linux_batch(windows)  # Linux 通用 AT-SPI。
        elif sys.platform=='win32': result = windows_batch(windows,emit)  # Completed windows survive another window blocking in UIA.
        elif sys.platform=='darwin': result = mac_batch(windows)  # macOS 通用 AX。
        else: raise ValueError('此系统暂无无障碍适配器')  # 不冒充已支持。
    except Exception as error:  # 单个系统探针失败不崩溃主进程。
        result = {w['id']:{'text':'','scope':'unavailable','notes':['系统无障碍接口不可用：'+str(error)[:160]]} for w in windows}  # 明确失败。
    print(json.dumps(result if batch else next(iter(result.values())), ensure_ascii=True))  # ASCII JSON 协议不依赖 Windows 的 GBK/系统代码页，解码后保留全部 Unicode。


if __name__ == '__main__':  # 父进程单次启动此模块。
    main()  # 读取后退出，不常驻监听键盘。
