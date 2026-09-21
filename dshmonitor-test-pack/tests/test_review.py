"""Headed mode changes presentation and end-of-run lifetime, not the scenario."""
import importlib.util,json
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('review_mode',Path(__file__).resolve().parents[1]/'runtime/review.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def test_browser_display_and_binary(tmp_path,monkeypatch):
    from dsh_test_harness.desktop import Desktop
    monkeypatch.setattr(Desktop,'browser_options',lambda self,visible,env:{'headless':False,'env':env})
    env={'WAYLAND_DISPLAY':'wayland-0'}
    assert module.browser_options(tmp_path,True,env)==module.browser_options(tmp_path,False,env)=={'headless':False,'env':env}

class Page:
    def __init__(self,interrupt=False):self.closed=False;self.ticks=0;self.interrupt=interrupt
    def screenshot(self,path):Path(path).write_bytes(b'fixture')
    def expose_binding(self,name,fn):self.binding=fn
    def add_init_script(self,script):pass
    def evaluate(self,script):pass
    def on(self,event,fn):pass
    def is_closed(self):return self.closed
    def wait_for_timeout(self,ms):
        self.ticks+=1
        if self.interrupt:raise KeyboardInterrupt()
        self.binding(None,{'type':'click','tag':'BUTTON','role':None})
        self.closed=True

def test_free_inspection_finishes_only_on_page_close(tmp_path):
    page=Page();module.inspect_until_closed(page,tmp_path)
    record=json.loads((tmp_path/'human-review.json').read_text())
    assert page.ticks==1 and record['status']=='closed'
    assert record['automated_actions_finished'] and len(record['interactions'])==1

def test_interruption_is_not_review_completion(tmp_path):
    with pytest.raises(KeyboardInterrupt):module.inspect_until_closed(Page(True),tmp_path)
    assert json.loads((tmp_path/'human-review.json').read_text())['status']=='interrupted'
