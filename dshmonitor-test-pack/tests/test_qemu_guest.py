"""Old replies must never become a new guest-exec PID or file handle."""
import json,socket,threading,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
import qemu_guest

def test_discards_partial_and_complete_stale_replies(tmp_path,monkeypatch):
    address=str(tmp_path/'agent.sock');monkeypatch.setattr(qemu_guest,'SOCKET',address)
    server=socket.socket(socket.AF_UNIX);server.bind(address);server.listen(1)
    errors=[]
    def serve():
        try:
            with server.accept()[0] as client:
                stream=client.makefile('rb')
                sync=json.loads(stream.readline().lstrip(b'\xff'))
                client.sendall(b'old partial response\n{"return":{"pid":999}}\n\xff'+json.dumps({'return':sync['arguments']['id']}).encode()+b'\n')
                assert json.loads(stream.readline())['execute']=='guest-exec'
                client.sendall(b'{"return":{"pid":42}}\n')
                assert json.loads(stream.readline())['execute']=='guest-exec-status'
                client.sendall(b'{"return":{"exited":true}}\n');stream.close()
        except Exception as error:errors.append(error)
    thread=threading.Thread(target=serve);thread.start()
    try:
        assert qemu_guest.call('guest-exec',{'path':'test'})=={'pid':42}
        assert qemu_guest.call('guest-exec-status',{'pid':42})=={'exited':True}
    finally:qemu_guest.reset();thread.join(10);server.close()
    assert not thread.is_alive() and not errors
