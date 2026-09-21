"""Read real native accessibility text without activating or changing the window."""
import json,os,subprocess,sys

def read_window(window):
    if os.name=='nt':
        from pywinauto import Desktop
        control=Desktop(backend='uia').window(handle=int(window['id'].split(':')[1]))
        return '\n'.join(c.window_text() for c in control.descendants())
    result=subprocess.run(['/usr/bin/python3',__file__],input=json.dumps(window),capture_output=True,text=True,timeout=15)
    if result.returncode:raise RuntimeError(result.stderr[-1000:])
    return result.stdout

if __name__=='__main__':
    import gi,time
    gi.require_version('Atspi','2.0')
    from gi.repository import Atspi
    window=json.load(sys.stdin);desktop=Atspi.get_desktop(0);queue=[];texts=[];deadline=time.monotonic()+10
    for i in range(desktop.get_child_count()):
        app=desktop.get_child_at_index(i)
        if app is None:continue
        frames=[app.get_child_at_index(j) for j in range(app.get_child_count())]
        matches=[frame for frame in frames if frame is not None and frame.get_name()==window.get('title')]
        if matches:queue.extend(matches)
        elif app.get_process_id()==window['pid'] and app.get_name()!='gnome-shell':queue.append(app)
    while queue and time.monotonic()<deadline:
        node=queue.pop(0)
        if node is None:continue
        try:
            texts.append(node.get_name())
            text=node.get_text_iface()
            if text:texts.append(Atspi.Text.get_text(text,0,-1))
            queue.extend(node.get_child_at_index(i) for i in range(node.get_child_count()))
        except Exception:pass
    print('\n'.join(texts))
