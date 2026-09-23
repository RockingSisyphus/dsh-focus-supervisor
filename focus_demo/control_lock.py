"""Keep state changes ordered; perform their file cleanup after releasing control."""
import threading


class ControlLock:
    def __init__(self):
        self.mutex=threading.RLock()
        self.local=threading.local()

    def __enter__(self):
        self.mutex.acquire()
        if not getattr(self.local,'depth',0):self.local.cleanup=[]
        self.local.depth=getattr(self.local,'depth',0)+1
        return self

    def after_release(self,callback):
        if getattr(self.local,'depth',0):self.local.cleanup.append(callback)
        else:callback()

    def __exit__(self,*error):
        self.local.depth-=1
        callbacks=self.local.cleanup if not self.local.depth else []
        if callbacks:self.local.cleanup=[]
        self.mutex.release()
        failures=[]
        for callback in callbacks:
            try:callback()
            except Exception as failure:failures.append(failure)
        if failures:raise failures[0]
