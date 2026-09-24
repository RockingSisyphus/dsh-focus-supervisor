"""Browser document observations from the shared system accessibility reader."""
import time


def snapshots(desktop, options):
    records = []
    seen_groups = set()
    for window in desktop.get('windows', []):
        if window.get('visible') is False or window.get('mapped') is False or window.get('minimized'):
            continue
        for document in window.get('browser_documents', []):
            captured = document['captured_at']
            if time.time()-captured > max(30, document.get('capture_interval_seconds',10)*3):
                continue
            grouped=document.get('association')=='ambiguous_process_group'
            group_key=(window.get('pid'),captured,document.get('document_index'))
            if grouped and group_key in seen_groups:continue
            if grouped:seen_groups.add(group_key)
            records.append({'native_window_id':None if grouped else window['id'], 'app':window.get('app'),
                            'process':window.get('process', {}),
                            'a11y_root':document.get('a11y_root'),
                            **({'native_window_ids':document['window_ids'],'association':'ambiguous_process_group','may_include_hidden':True,'document_index':document['document_index']} if grouped else {}),
                            'pid':window.get('pid'), 'browser_instance_id':window.get('process',{}).get('identity'),
                            'title':document['title'], 'url':document['url'], 'selected':document['selected'],
                            'focused':None if grouped else window.get('focused',False), 'visible':None if grouped else window.get('visible'),
                            'visibility_class':window.get('visibility_class'),
                            'captured_at':captured, 'connection_kind':'system_accessibility',
                            'source':'system-accessibility', 'snapshot':document})
    return {'available':bool(records), 'snapshots':records,
            'limitations':['系统无障碍正文可能包含视口外文字；不枚举后台标签。',*(['同进程歧义窗口组可能包含隐藏内容，须结合截图判断归属。'] if seen_groups else [])]}
