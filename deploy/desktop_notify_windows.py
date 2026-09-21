"""Native Windows reminder; invoked by the same notification protocol as Linux."""
import json,sys,time,os
from pathlib import Path

INK='#3F4B6E';SUB='#7C89AC';WHITE='#FFFFFF'
TITLE_FONT=('Microsoft YaHei UI',13,'bold')
HINT_FONT=('Microsoft YaHei UI',9)
MSG_FONT=('Microsoft YaHei UI',11)
BTN_FONT=('Microsoft YaHei UI',11,'bold')
BTN_LABEL='知道了，我去监工聊天里解释 / 继续任务'
CARD_WIDTH=440
PAD_X=24;PAD_Y=22
BTN_PAD_X=22;BTN_PAD_Y=13
GAP_TITLE=30;GAP_MASCOT=14;GAP_BUBBLE=16;GAP_NOTE=34;GAP_BUTTON=62
MASCOT_STEPS=(280,200,150,0)

def rounded(canvas,x1,y1,x2,y2,radius,fill,outline=''):
    points=[x1+radius,y1,x2-radius,y1,x2,y1,x2,y1+radius,x2,y2-radius,x2,y2,x2-radius,y2,x1+radius,y2,x1,y2,x1,y2-radius,x1,y1+radius,x1,y1]
    return canvas.create_polygon(points,smooth=True,fill=fill,outline=outline)

def pastel_card(width,height):
    """Vertical pink→blue gradient with rounded corners, returned as a PhotoImage."""
    from PIL import Image,ImageDraw,ImageTk
    card=Image.new('RGB',(width,height))
    draw=ImageDraw.Draw(card)
    for y in range(height):
        t=y/max(1,height-1)
        draw.line([(0,y),(width,y)],fill=(int(255-23*t),int(233+10*t),int(244+11*t)))
    mask=Image.new('L',(width,height),0)
    ImageDraw.Draw(mask).rounded_rectangle([0,0,width-1,height-1],radius=26,fill=255)
    card.putalpha(mask)
    return ImageTk.PhotoImage(card)

def measure(canvas,width,max_height,source,mascot_h,message):
    """Lay the popup out on a scratch canvas; None means this combination does not fit."""
    from PIL import Image,ImageTk
    canvas.delete('all')
    photo=None
    if mascot_h:
        image=source.copy();image.thumbnail((mascot_h,mascot_h));photo=ImageTk.PhotoImage(image)
    y=26+GAP_TITLE
    if photo is not None:y+=mascot_h+GAP_MASCOT
    text=canvas.create_text(PAD_X+22,y+GAP_BUBBLE,anchor='nw',text=message,width=width-2*(PAD_X+22),fill=INK,font=MSG_FONT,justify='left')
    box=canvas.bbox(text)
    if box is None:return None
    probe=canvas.create_text(0,0,anchor='nw',text=BTN_LABEL,fill=WHITE,font=BTN_FONT)
    pbox=canvas.bbox(probe)
    total=box[3]+GAP_NOTE+GAP_BUTTON-14+(pbox[3]-pbox[1])+2*BTN_PAD_Y+PAD_Y
    canvas.delete('all')
    if total>max_height:return None
    return {'photo':photo,'mascot_h':mascot_h,'message':message,'total':total}

def fit(canvas,width,max_height,source,message):
    """Shrink the mascot, then trim the model-written text, until the card fits the screen."""
    for mascot in MASCOT_STEPS:
        layout=measure(canvas,width,max_height,source,mascot,message)
        if layout is not None:return layout
    trimmed=message
    while len(trimmed)>24:
        trimmed=trimmed[:max(24,int(len(trimmed)*0.8))].rstrip()+'…'
        for mascot in MASCOT_STEPS:
            layout=measure(canvas,width,max_height,source,mascot,trimmed)
            if layout is not None:return layout
    return None

def notify(request):
    import tkinter as tk
    from PIL import Image,ImageTk
    import winsound,win32gui,win32con,win32api
    root=tk.Tk();root.withdraw();root.title('大肥鱼监工提醒')
    result={'pid':os.getpid(),'popup':False,'notification':False,'sound':False,'errors':[]}
    assets=Path(__file__).resolve().parents[1]/'assets'
    if not assets.is_dir():assets=Path(__file__).resolve().parents[1]/'dsh-plugin/assets'
    if request.get('popup'):
        try:
            root.overrideredirect(True);root.attributes('-topmost',True);root.configure(bg='#FBF7FF')
            canvas=tk.Canvas(root,width=CARD_WIDTH,height=200,highlightthickness=0,bd=0,bg='#FBF7FF')
            canvas.pack()
            screen_w,screen_h=root.winfo_screenwidth(),root.winfo_screenheight()
            width=min(CARD_WIDTH,max(360,screen_w-80))
            max_height=int(screen_h*0.78)
            source=Image.open(assets/(request['image']+'.png'))
            layout=fit(canvas,width,max_height,source,request['message'])
            if layout is None:raise RuntimeError('提醒内容过长，无法排版')
            photo,mascot_h,message,total=layout['photo'],layout['mascot_h'],layout['message'],layout['total']
            canvas.delete('all');canvas.configure(height=total)
            card=pastel_card(width,total)
            canvas.tag_lower(canvas.create_image(0,0,anchor='nw',image=card))
            canvas.create_text(PAD_X,26,anchor='nw',text='🐟 大肥鱼监工',fill=INK,font=TITLE_FONT)
            canvas.create_text(width-PAD_X,28,anchor='ne',text='温柔提醒',fill=SUB,font=HINT_FONT)
            y=26+GAP_TITLE
            if photo is not None:
                canvas.create_image(width//2,y+mascot_h//2,image=photo);y+=mascot_h+GAP_MASCOT
            text=canvas.create_text(PAD_X+22,y+GAP_BUBBLE,anchor='nw',text=message,width=width-2*(PAD_X+22),fill=INK,font=MSG_FONT,justify='left')
            x1,y1,x2,y2=canvas.bbox(text)
            bubble=rounded(canvas,PAD_X+8,y1-16,width-PAD_X-8,y2+16,18,WHITE);canvas.tag_lower(bubble,text)
            canvas.create_text(width//2,y2+GAP_NOTE,text='解释、修改约定和完成验收都在监工聊天里进行',fill=SUB,font=HINT_FONT)
            probe=canvas.create_text(0,0,anchor='nw',text=BTN_LABEL,fill=WHITE,font=BTN_FONT)
            pbox=canvas.bbox(probe);canvas.delete(probe)
            button_w=(pbox[2]-pbox[0])+2*BTN_PAD_X;button_h=(pbox[3]-pbox[1])+2*BTN_PAD_Y
            button_left=(width-button_w)//2;button_top=y2+GAP_BUTTON;button_bottom=button_top+button_h
            button=rounded(canvas,button_left,button_top,button_left+button_w,button_bottom,16,'#A9CEFF')
            button_text=canvas.create_text(width//2,(button_top+button_bottom)//2,text=BTN_LABEL,fill=WHITE,font=BTN_FONT)
            def return_to_chat(_event=None):
                print(json.dumps({'event':'reminder_button','pid':os.getpid(),'at':time.time(),
                                  'input':{key:getattr(_event,key,None) for key in ('type','serial','time','state','num','x_root','y_root')}},default=str),file=sys.stderr,flush=True)
                from open_chat import FocusSuperseded,open_chat
                for item in (button,button_text):canvas.tag_unbind(item,'<Button-1>')
                root.withdraw()
                def finish(error):
                    if error:
                        root.deiconify()
                        from tkinter import messagebox
                        messagebox.showerror('无法打开监工聊天',str(error))
                        for item in (button,button_text):canvas.tag_bind(item,'<Button-1>',return_to_chat)
                    else:root.destroy()
                def work():
                    try:open_chat(request['chat_url'],request.get('chat_registry'));error=None
                    except FocusSuperseded:error=None
                    except Exception as caught:error=caught
                    root.after(0,finish,error)
                import threading
                threading.Thread(target=work,daemon=True).start()
            for item in (button,button_text):canvas.tag_bind(item,'<Button-1>',return_to_chat)
            if '--test-auto-close' in sys.argv:
                # Test-only: the button sits above the window's bottom padding, so a guessed
                # coordinate misses it; report the real centre for the harness.
                result['button_center']=[width//2,(button_top+button_bottom)//2]
            drag={}
            def start_drag(event):drag.update(x=event.x,y=event.y)
            def move_drag(event):root.geometry(f'+{event.x_root-drag["x"]}+{event.y_root-drag["y"]}')
            canvas.bind('<Button-1>',start_drag);canvas.bind('<B1-Motion>',move_drag,add='+')
            root.update_idletasks()
            root.geometry(f'+{(screen_w-width)//2}+{max(0,(screen_h-total)//2)}')
            root.deiconify();root.update();result['popup']=True
        except Exception as error:result['errors'].append('弹窗：'+str(error))
    tray=None
    if request.get('notification'):
        try:
            wc=win32gui.WNDCLASS();wc.hInstance=win32api.GetModuleHandle(None);wc.lpszClassName='DafeiyuReminderTray';wc.lpfnWndProc=win32gui.DefWindowProc
            atom=win32gui.RegisterClass(wc);tray=win32gui.CreateWindow(atom,'大肥鱼监工',0,0,0,0,0,0,0,wc.hInstance,None)
            icon=win32gui.LoadIcon(0,win32con.IDI_INFORMATION)
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD,(tray,0,win32gui.NIF_ICON|win32gui.NIF_TIP,0,icon,'大肥鱼监工'))
            win32gui.Shell_NotifyIcon(win32gui.NIM_MODIFY,(tray,0,win32gui.NIF_INFO,0,icon,'大肥鱼监工',request['message'][:255],10000,'大肥鱼监工',win32gui.NIIF_INFO))
            result['notification']=True
            result['notification_scope']='shell_notification_submitted'
        except Exception as error:result['errors'].append('通知：'+str(error))
    if request.get('sound'):
        try:winsound.MessageBeep(winsound.MB_ICONEXCLAMATION);result['sound']=True
        except Exception as error:result['errors'].append('提示音：'+str(error))
    print(json.dumps(result,ensure_ascii=True),flush=True)
    print(json.dumps({'event':'reminder_ready','pid':os.getpid(),'at':time.time(),'popup':result['popup']}),file=sys.stderr,flush=True)
    if '--test-auto-close' in sys.argv or not result['popup']:
        root.after(8000 if '--test-auto-close' in sys.argv else 15000,root.destroy)
    root.mainloop()
    print(json.dumps({'event':'reminder_exit','pid':os.getpid(),'at':time.time()}),file=sys.stderr,flush=True)
    if tray:
        win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE,(tray,0));win32gui.DestroyWindow(tray)
