"""Read-only native/Chromium title timeline, independent of the UI runner."""
import json,sys,time,urllib.request
import psutil
from pathlib import Path
from dsh_test_harness.entities import Entities

output=Path(sys.argv[1]);duration=float(sys.argv[2]);endpoint=sys.argv[3]
desktop=Entities(None)
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
deadline=time.monotonic()+duration
with output.open('w',encoding='utf-8') as log:
    while time.monotonic()<deadline:
        row={'at':time.time(),'helpers':[]}
        for process in psutil.process_iter(['pid','name','cmdline']):
            args=process.info.get('cmdline') or []
            kind=next((arg for arg in args if arg in ('focus_demo.ui_probe','focus_demo.window_probe','focus_demo.browser_targets','--select-tab')),None)
            if kind:row['helpers'].append({'pid':process.info['pid'],'kind':kind})
        try:
            row['desktop']=desktop.snapshot()
        except Exception as error:row['desktop_error']=str(error)
        try:
            with opener.open(endpoint+'/json/list',timeout=.3) as response:tabs=json.load(response)
            row['tabs']=[{k:t.get(k) for k in ('id','type','title')} for t in tabs]
        except Exception as error:row['browser_error']=str(error)
        log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
        time.sleep(.1)
