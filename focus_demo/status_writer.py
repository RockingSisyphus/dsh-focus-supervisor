"""Publish replaceable status outside the task-control lock; keep only the latest."""
import copy,threading
from .common import write_json

class StatusWriter:
    def __init__(self):
        self.condition=threading.Condition();self.pending={};self.stopping=False;self.errors={}
        self.thread=threading.Thread(target=self.run,name='status-writer',daemon=True);self.thread.start()
    @property
    def error(self):
        with self.condition:
            return '; '.join(f'{path.name}: {message}' for path,message in self.errors.items()) or None
    def submit(self,path,value,gid=None):
        with self.condition:
            self.pending[path]=(copy.deepcopy(value),gid)
            self.condition.notify()
    def run(self):
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.pending or self.stopping)
                if not self.pending:return
                path=next(iter(self.pending));value,gid=self.pending.pop(path)
            try:
                if gid is None:write_json(path,value)
                else:write_json(path,value,gid=gid)
                with self.condition:self.errors.pop(path,None)
            except Exception as error:
                with self.condition:self.errors[path]=str(error)
    def close(self):
        with self.condition:self.stopping=True;self.condition.notify()
        self.thread.join(timeout=30)
        if self.thread.is_alive():raise TimeoutError('Status persistence did not finish')
        if self.error:raise RuntimeError('Status persistence failed: '+self.error)
