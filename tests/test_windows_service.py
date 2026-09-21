"""Windows service transport contracts; real desktop acceptance remains in JSON."""
import threading


def test_slow_capture_does_not_block_evidence_delivery(monkeypatch):
    import sys
    previous = sys.excepthook
    from deploy import windows_service as service
    sys.excepthook = previous
    entered, release = threading.Event(), threading.Event()
    class Collector:
        def configure(self, sampling):
            assert sampling == {}
        def capture(self):
            entered.set()
            release.wait(5)
    sensor = service.Sensor.__new__(service.Sensor)
    sensor.lock = threading.Lock()
    sensor.collector = Collector()
    monkeypatch.setattr(service, 'deliver', lambda operation, payload: {'written': 1})
    capture = threading.Thread(target=lambda: sensor.call('capture'))
    capture.start()
    completed = threading.Event()
    answer = []
    export = threading.Thread(target=lambda: (answer.append(sensor.call('export', {})), completed.set()))
    try:
        assert entered.wait(2)
        export.start()
        assert completed.wait(1), 'Evidence delivery waited on the unrelated desktop capture'
        assert answer == [{'written': 1}]
    finally:
        release.set()
        capture.join(3)
        if export.ident: export.join(3)
