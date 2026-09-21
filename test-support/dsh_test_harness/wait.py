"""Small helpers shared by real browser scenarios."""
import time

def until(function,timeout=40,wait=None):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=function()
        if value:return value
        (wait or time.sleep)(.1)
    raise TimeoutError('Condition not reached')
