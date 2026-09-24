"""Linux AT-SPI 的标准 D-Bus 读取器；不依赖 PyGObject，使用系统 GIO 公共接口。"""
import os  # 读取当前桌面已经授权的辅助功能总线地址。
import time  # 为整批读取设置截止时间。
from .ui_structure import describe_window, entry, ReadBudget
from collections import deque  # 有界遍历控件树。


ACCESSIBLE = 'org.a11y.atspi.Accessible'  # 标准辅助功能接口。
MAX_NODES_PER_WINDOW = 1600  # 保留同一总时间预算，容纳复杂界面的正文节点。
ROOT = '/org/a11y/atspi/accessible/root'  # 标准应用可访问根路径。


class Bus:  # 功能：复用标准 GIO 连接，并限制整批实际读取时间。
    def __init__(self, seconds=2.5):  # 功能：从当前桌面取得真实辅助功能总线。
        from .native_dbus import NativeBus  # 只依赖标准库和系统 GLib/GIO 动态库。
        self.deadline = time.monotonic() + seconds  # 所有控件共用有限预算。
        address = os.environ.get('AT_SPI_BUS_ADDRESS', '')  # 优先采用用户会话已经提供的地址。
        if not address:  # 普通桌面通过标准服务查询。
            session = NativeBus()  # 连接当前用户会话，不枚举其他用户桌面。
            try:  # 地址查询也有单次超时。
                address = session.call('org.a11y.Bus', '/org/a11y/bus', 'org.a11y.Bus', 'GetAddress', '', (), 250)  # 标准辅助功能服务。
            finally:  # 不保留不必要的会话连接。
                session.close()  # 释放查询连接。
        self.connection = NativeBus(address)  # 复用一条辅助功能连接。

    def call(self, name, path, interface, method, signature='', *values):  # 功能：对标准本机接口发起有界读取。
        remaining = self.deadline - time.monotonic()  # 计算剩余总预算。
        if remaining <= 0:  # 到期不再读下一个控件。
            raise TimeoutError('AT-SPI 整批读取预算耗尽')  # 保留已获得的文字。
        return self.connection.call(name, path, interface, method, signature, values, max(1, min(200, int(remaining * 1000))))  # 每个系统调用同样有超时。

    def close(self):  # 功能：结束本批总线读取。
        self.connection.close()  # 不操作远端 GUI。


def linux_batch(windows, text_chars=12000, max_nodes=MAX_NODES_PER_WINDOW):  # 功能：按真实 PID 和顶层矩形绑定所有程序的 AT-SPI 窗口。
    from .ui_probe import match_windows  # 复用同一个窗口关联规则。
    bus = Bus()  # 一次批量读取共享总线与预算。
    notes = ['通过标准 AT-SPI D-Bus 接口读取；未进行应用专用适配。', '文字是有界辅助功能摘录，可能包含视口外内容；SHOWING 不等于未被遮挡。']  # 明确范围。
    results = {w['id']: {'text': '', 'scope': 'unavailable', 'notes': notes + ['未找到唯一 PID/窗口几何匹配。']} for w in windows}  # 所有窗口都有明确状态。
    wanted = {int(w.get('pid') or 0) for w in windows} - {0}  # 只检查本次真实窗口所属进程。
    role_names = {}
    budget = ReadBudget(windows[0].get('_read',{}) if windows else {})
    selected = []
    groups = {}
    applications = {}  # 保存目标进程实际拥有的总线连接。
    try:  # 发现失败不能误算为用户没有活动。
        names = bus.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'ListNames')  # 枚举当前辅助功能总线。
        for name in names:  # 只检查唯一连接名，避免别名重复。
            if not name.startswith(':'):  # 众所周知名称只是连接别名。
                continue  # 跳过重复项。
            try:  # 刚列出的临时连接可能已经断开。
                pid = bus.call('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus', 'GetConnectionUnixProcessID', 's', name)  # PID 来自总线而非标题。
            except RuntimeError:  # 跳过消失的连接，不中止整个桌面读取。
                continue  # 下一条真实连接。
            if pid in wanted:  # 不遍历其他进程的私人控件树。
                applications.setdefault(pid, []).append(name)  # 同 PID 可以拥有多个真实连接。
        roots = {}  # 只枚举目标程序的顶层控件。
        for pid, owners in applications.items():  # 不按程序名称分支。
            roots[pid] = []  # 该进程的真实候选窗口。
            for owner in owners:  # 查询每个目标连接。
                try:  # 不提供 AT-SPI 的连接可以跳过。
                    children = bus.call(owner, ROOT, ACCESSIBLE, 'GetChildren')  # 获取程序可访问顶层窗口。
                    for name, path in children[:64]:  # 限制单应用候选数量。
                        rect = bus.call(name, path, 'org.a11y.atspi.Component', 'GetExtents', 'u', 0)  # 读取屏幕坐标。
                        props = bus.call(name, path, 'org.freedesktop.DBus.Properties', 'GetAll', 's', ACCESSIBLE)
                        state = bus.call(name, path, ACCESSIBLE, 'GetState')
                        roots[pid].append({'node': (name, path), 'rect': rect, 'title': props.get('Name', {}).get('data', ''), 'active': bool(state and state[0] & 2)})  # 保存实际接口返回的几何。
                except RuntimeError:  # 不支持的接口不合成内容。
                    continue  # 继续其他有效连接。
        associations={}
        for pid,candidates in roots.items():
            associations.update(match_windows([w for w in windows if int(w.get('pid') or 0)==pid],candidates))
        selected = []  # 为各窗口独立建立读取队列。
        for window in windows:  # 复用统一的 PID/几何匹配规则。
            match = associations.get(window['id'])
            if match is None:
                continue
            if 'nodes' in match:
                key=match['window_ids'][0]
                if key in groups:continue
                groups[key]=match['window_ids']
                nodes=match['nodes']
                offset=budget.options.get('browser_offset',0)%len(nodes)
                nodes=nodes[offset:]+nodes[:offset]
            else:key=window['id'];nodes=[match['node']]
            selected.append((key, deque([(name, path, None, (name, path)) for name,path in nodes]), [], set()))
            results[key] = {'text': '', 'scope': 'accessibility_excerpt', 'notes': list(notes) + [match['association']]}
        counts = {key: 0 for key, *_ in selected}  # 每个窗口单独限制节点数。
        for key, queue, output, seen in selected:  # 窗口顺序由调度器轮换，正文名额不由节点深度争抢。
            while queue and counts[key] < max_nodes:
                if not queue or counts[key] >= max_nodes:  # 已完成或达到节点预算。
                    continue  # 处理其他窗口。
                name, path, parent, root = queue.popleft()  # 读取实际存在的节点。
                if (name, path) in seen:  # 防止异常循环树。
                    continue  # 不重复请求。
                seen.add((name, path)); counts[key] += 1  # 记录已访问节点。
                try:  # 界面更新可能使节点立即失效。
                    role = bus.call(name, path, ACCESSIBLE, 'GetRole')  # 先判断角色，避免先读出密码内容。
                    if role == 40:  # 标准 ATSPI_ROLE_PASSWORD_TEXT 枚举值。
                        continue  # 密码节点及子树都不查询名称或正文。
                    state = bus.call(name, path, ACCESSIBLE, 'GetState')  # 查询标准状态位集合。
                    showing=bool(state and state[0] & (1 << 25))
                    if not showing and key not in groups:
                        continue
                    props = bus.call(name, path, 'org.freedesktop.DBus.Properties', 'GetAll', 's', ACCESSIBLE)  # 读取可访问名称。
                    label = props.get('Name', {}).get('data', '')  # 不拼入非文本属性。
                    if isinstance(label, str) and label:  # 控件名可能已包含可见文字。
                        pass  # Label is retained with its role and parent below.  # 限制单控件输出量。
                    text = ''
                    index = len(output)
                    if role not in role_names:
                        role_names[role] = bus.call(name, path, ACCESSIBLE, 'GetRoleName')
                    flags = state[0] if state else 0
                    states = [label for bit, label in ((4,'checked'), (10,'expanded'), (12,'focused'), (23,'selected')) if flags & (1 << bit)]
                    output.append(entry(index, parent, role_names[role], label, states=states))
                    if 'document' in role_names[role]:
                        try:
                            attrs = bus.call(name, path, 'org.a11y.atspi.Document', 'GetAttributes')
                            uri = attrs.get('DocURL') or attrs.get('URI') or attrs.get('uri')
                            if uri:
                                output[index]['document_url'] = uri
                                output[index]['a11y_root'] = {'owner': root[0], 'path': root[1]}
                        except RuntimeError:
                            pass
                    readable = budget.enter(output[index], output[parent] if parent is not None else None)
                    if output[index]['browser_document'] and not readable:
                        continue
                    try:  # 通用 Text 接口并非所有控件都支持。
                        if not readable:raise RuntimeError('本轮仅观察窗口身份')
                        interfaces = bus.call(name, path, ACCESSIBLE, 'GetInterfaces')
                        if 'org.a11y.atspi.Text' not in interfaces:
                            raise RuntimeError('控件未声明 Text 接口')
                        count = bus.call(name, path, 'org.freedesktop.DBus.Properties', 'Get', 'ss', 'org.a11y.atspi.Text', 'CharacterCount')['data']
                        text = bus.call(name, path, 'org.a11y.atspi.Text', 'GetText', 'ii', 0, min(3000, max(0, int(count))))
                        if int(count) > 3000: output[index]['truncated'] = True
                        text = text.replace('\ufffc', '')
                        if text:  # 不发送重复空项。
                            output[index]['text'] = text  # Preserve text under its actual control.
                    except RuntimeError:  # 仅名称可读时仍保留已有证据。
                        pass  # 截图可以继续补充。
                    children = bus.call(name, path, ACCESSIBLE, 'GetChildren')
                    if len(children) > 100: results[key]['notes'].append('子控件超过本次读取上限。')
                    queue.extend((child[0], child[1], index, root) for child in children[:100])  # 有界遍历子控件。
                except RuntimeError:  # 失效对象不阻断其他窗口。
                    continue  # 保留其他已成功读取的证据。
                finally:  # 即使最后一个接口超时，也保留此前实际文字。
                    pass  # Render once after collection, including on timeout.  # 每个窗口独立保存正文。
    except TimeoutError as error:  # 严格遵守整批硬预算。
        for result in results.values():  # 不丢弃已经成功读取的部分。
            result['notes'].append('本批 AT-SPI 读取达到时间上限，内容可能不完整。')  # 明示覆盖缺口。
    except Exception as error:  # 总线或接口整体不可用。
        for result in results.values():  # 所有窗口收到可诊断信息。
            result['notes'].append('AT-SPI D-Bus 不可用：' + str(error)[:180])  # 不伪造正文。
    finally:  # 不保留超时批次的连接引用。
        for key, queue, output, _ in selected:
            partial = bool(queue) or any('上限' in note for note in results[key]['notes'])
            results[key].update(describe_window(output, truncated=partial, limit=text_chars))
            results[key]['scope'] = 'accessibility_structure'
            if key in groups:
                result=results[key]
                result['scope']='process_window_group'
                result['structure'].update(window_ids=groups[key],association='ambiguous_process_group',may_include_hidden=True)
                for index,document in enumerate(result.get('documents',[])):
                    document.update(association='ambiguous_process_group',window_ids=groups[key],may_include_hidden=True,selected=None,captured_at=time.time(),document_index=index)
                for text_result in [result,*result.get('documents',[])]:
                    body=text_result['text'].partition('\n')[2]
                    text_result['text']=('[同进程窗口组；可能含隐藏内容，请结合截图判断归属。]\n'+body)[:text_chars]
                for identifier in groups[key]:results[identifier]=result
        bus.close()  # 释放本客户端连接，不改变应用内容。
    return results  # 与原接口保持相同结构。
