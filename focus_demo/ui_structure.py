"""Read-only UI descriptions shared by native accessibility adapters.

No action references or application-specific rules. Parent links describe the
observed tree; unknown/unreadable content remains a coverage gap.
"""
import json

CONTAINERS = {'panel', 'pane', 'generic', 'filler', 'unknown', 'custom', 'group', 'section'}
TEXT_ROLES = {'text', 'static text', 'static', 'label', 'statictext', 'inline text box', 'inlinetextbox'}


class ReadBudget:
    """One batch's body budget, shared across native windows and document frames."""
    def __init__(self, options):
        self.options = options
        self.pages = 0

    def enter(self, node, parent=None):
        browser = bool(node.get('document_url')) or bool(parent and parent.get('browser_document'))
        node['browser_document'] = browser
        if parent and parent.get('browser_document'):
            allowed = parent['read_body']
        elif browser:
            maximum = self.options.get('browser_pages')
            allowed = self.options.get('browser_due',True) and (maximum is None or self.pages < maximum)
            if allowed:self.pages += 1
        else:
            allowed = self.options.get('native_due',True)
        node['read_body'] = allowed
        return allowed


def describe(nodes, truncated=False, limit=12000):
    """Render a bounded tree; elide only empty layout nodes, not repeated controls."""
    children = {}
    for node in nodes:
        children.setdefault(node['parent'], []).append(node)
    lines = ['[界面结构摘录；控件可见不代表未被遮挡，不能据此证明用户已阅读]']
    used = len(lines[0]) + 1
    omitted = 0
    stack = [(n, 0, '', '') for n in reversed(children.get(None, []))]
    while stack:
        node, depth, parent_name, parent_text = stack.pop()
        role = node['role']
        name = node.get('name', '').strip()
        text = node.get('text', '')
        states = node.get('states', [])
        descendants = children.get(node['id'], [])
        empty_layout = not name and not text and not states and role in CONTAINERS
        content = text or name
        duplicate_label = (not states and role in TEXT_ROLES and bool(content)
                           and (content == parent_name or
                                bool(parent_text) and content in parent_text))
        empty_leaf = not descendants and not name and not text and not states and role in ('label', 'text', 'static', 'static text', 'image')
        if not empty_layout and not duplicate_label and not empty_leaf:
            label = role
            if name: label += ' ' + json.dumps(name, ensure_ascii=False)
            if states: label += ' [' + ', '.join(states) + ']'
            if text and text != name: label += ' — ' + json.dumps(text, ensure_ascii=False)
            line = '  '*min(depth, 12) + label
            if used + len(line) + 100 > limit:
                omitted += 1
                # Keep trying smaller nodes; never output a half-quoted value.
            else:
                lines.append(line); used += len(line)+1
        child_depth = depth if empty_layout or duplicate_label else depth+1
        stack.extend((child, child_depth, text or name or parent_name, text or parent_text) for child in reversed(descendants))
    truncated = truncated or bool(omitted) or any(node.get('truncated') for node in nodes)
    if truncated: lines.append('[摘录未完整：采集或输出预算已到，缺失内容请结合截图]')
    text = '\n'.join(lines)
    if len(text) > limit:
        # Tiny legal budgets cannot fit the explanatory header. The structured
        # truncation flag still reports the loss; never silently exceed the budget.
        text = text[:limit]
        truncated = True
    return {'text': text, 'structure': {'format': 'native-ui-tree-v1',
            'captured_nodes': len(nodes), 'rendered_lines': len(lines)-1,
            'truncated': truncated, 'omitted_nodes': omitted}}


def entry(index, parent, role, name='', text='', states=()):
    role = role.lower().replace('_', ' ')
    aliases = {'push button':'button','check box':'checkbox','radio button':'radiobutton',
               'document web':'document','page tab':'tab','tabitem':'tab',
               'static text':'text','statictext':'text','table cell':'cell','table row':'row'}
    return {'id': index, 'parent': parent, 'role': aliases.get(role,role), 'source_role':role,
            'name': str(name)[:1200], 'text': str(text).replace('\ufffc', '')[:3000],
            'states': list(states), 'truncated': len(str(name)) > 1200 or len(str(text)) > 3000}


def describe_window(nodes, truncated=False, limit=12000):
    """Keep document boundaries from the provider, including nested frame content.

    A document with a URI is browser content. Other application documents remain
    in the native tree. IDs here are sample-local tree nodes, never browser tab IDs.
    """
    by_id = {node['id']: node for node in nodes}
    roots = []
    for node in nodes:
        if not node.get('document_url') or not node.get('read_body',True):
            continue
        parent = node.get('parent')
        while parent in by_id and parent not in roots:
            parent = by_id[parent].get('parent')
        if parent not in roots:
            roots.append(node['id'])
    branches = {root: [] for root in roots}
    native = []
    for node in nodes:
        owner = node['id']
        while owner in by_id and owner not in branches:
            owner = by_id[owner].get('parent')
        if owner in branches:
            branches[owner].append({**node, 'parent': None if node['id'] == owner else node['parent']})
        else:
            native.append(node)
    result = describe(native, truncated, limit)
    result['documents'] = [dict(describe(branch, truncated, limit),
                                title=by_id[root].get('name', ''),
                                url=by_id[root]['document_url'],
                                selected=True, source='system-accessibility')
                           for root, branch in branches.items()]
    return result
