"""Development control channel; only the explicitly selected VM is addressed."""
import base64,json,socket,time,sys,secrets,threading
from contextlib import contextmanager
SOCKET = None
class Connection:
 """One synchronized QGA stream; reuse it for a multi-chunk file transfer."""
 def __enter__(self):
  self.channel=socket.socket(socket.AF_UNIX);self.channel.settimeout(30)
  try:
   self.channel.connect(SOCKET);self.stream=self.channel.makefile('rb')
   marker=secrets.randbits(63)
   self.channel.sendall(b'\xff'+(json.dumps({'execute':'guest-sync','arguments':{'id':marker}})+'\n').encode())
   # QGA requires synchronization on every connection, including after a
   # timeout. Line-oriented parsers may use guest-sync and discard stale JSON.
   # https://www.qemu.org/docs/master/interop/qemu-ga-ref.html#command-guest-sync
   try:
    return self.synchronize(marker)
   except TimeoutError as error:
    raise TimeoutError('QGA synchronization timed out; '+getattr(self,'sync_state','no response')) from error
  except BaseException:
   self.__exit__(None,None,None);raise
 def synchronize(self,marker):
   self.sync_state='awaiting marker'
   for line in self.stream:
    try:reply=json.loads(line.rsplit(b'\xff',1)[-1])
    except ValueError:continue
    value=reply.get('return')
    self.sync_state='expected '+str(marker)+'; received '+(str(value) if isinstance(value,int) else str(list(reply)))
    if value==marker:return self
   raise ConnectionError('Guest agent disconnected during synchronization')
 def __exit__(self,*_):
  if hasattr(self,'stream'):self.stream.close()
  self.channel.close()
 def call(self,command,arguments=None):
  self.channel.sendall((json.dumps({'execute':command,**({'arguments':arguments} if arguments else {})})+'\n').encode())
  for line in self.stream:
   reply=json.loads(line)
   if 'error' in reply:raise RuntimeError(reply['error'])
   if 'return' in reply:return reply['return']
  raise ConnectionError('Guest agent disconnected before reply')

_shared=None
_shared_socket=None
_lock=threading.RLock()

def reset():
 global _shared,_shared_socket
 with _lock:
  if _shared:_shared.__exit__(None,None,None)
  _shared=None;_shared_socket=None

@contextmanager
def session():
 global _shared,_shared_socket
 with _lock:
  if _shared_socket!=SOCKET:reset()
  if _shared is None:
   _shared=Connection().__enter__();_shared_socket=SOCKET
  try:yield _shared
  except (OSError,ValueError,KeyboardInterrupt,SystemExit):
   reset();raise

def call(command,arguments=None):
 with session() as connection:return connection.call(command,arguments)
def ps(script,timeout=60):
 encoded=base64.b64encode(script.encode('utf-16le')).decode()
 pid=call('guest-exec',{'path':'C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe','arg':['-NoProfile','-NonInteractive','-EncodedCommand',encoded],'capture-output':True})['pid']
 stop=time.monotonic()+timeout
 while time.monotonic()<stop:
  result=call('guest-exec-status',{'pid':pid})
  if result.get('exited'):
   return {'exitcode':result.get('exitcode'),'stdout':base64.b64decode(result.get('out-data','')).decode('utf-8','replace'),'stderr':base64.b64decode(result.get('err-data','')).decode('utf-8','replace')}
  time.sleep(.5)
 return {'running_pid':pid}
if __name__ == '__main__':
 import argparse
 from pathlib import Path
 parser=argparse.ArgumentParser(description='Control an existing QEMU guest through its local Guest Agent socket')
 parser.add_argument('--socket', required=True)
 parser.add_argument('--script', type=Path)
 parser.add_argument('--timeout', type=int, default=30)
 parser.add_argument('--status', type=int)
 args=parser.parse_args(); SOCKET=args.socket
 if args.status:
  result=call('guest-exec-status', {'pid':args.status})
  for key in ('out-data','err-data'):
   if key in result: result[key]=base64.b64decode(result[key]).decode('utf-8','replace')
 else:
  if not args.script:parser.error('--script or --status required')
  result=ps(args.script.read_text(encoding='utf-8'), args.timeout)
 print(json.dumps(result,ensure_ascii=False))
