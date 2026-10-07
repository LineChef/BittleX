"""SerialDetectionFeed.snapshot: one picture on the feed's own port, then back to detecting. Fake serial only; no camera, no network."""
import base64
import json
import threading
import time

import pytest

from pi_pipeline.vision.feed import BackgroundFrameSource, SerialDetectionFeed

JPEG = b"\xff\xd8\xff\xe0fake-picture\xff\xd9"


def picture_line():
    return (json.dumps({"type": 1, "name": "INVOKE", "code": 0,
                        "data": {"image": base64.b64encode(JPEG).decode(), "resolution": [240, 240], "boxes": [[120, 120, 60, 60, 80, 0]]}}) + "\r\n").encode()


def detection_line():
    return (json.dumps({"type": 1, "name": "INVOKE", "code": 0, "data": {"count": 1, "resolution": [240, 240], "boxes": [[120, 120, 60, 60, 90, 0]]}}) + "\r\n").encode()


class FakeSerial:
    """Records writes; readline() returns detection lines until a one-shot INVOKE was written, then a picture line."""

    def __init__(self, answer=True):
        self.writes, self.answer, self._one_shot, self._lock = [], answer, False, threading.Lock()

    def write(self, data):
        with self._lock:
            self.writes.append(data)
            if data == b"AT+INVOKE=1,0,0\r\n":
                self._one_shot = True
            if data == b"AT+INVOKE=-1,0,1\r\n":
                self._one_shot = False

    def reset_input_buffer(self):
        pass

    def readline(self):
        time.sleep(0.005)
        with self._lock:
            if self._one_shot:
                if self.answer:
                    self._one_shot = False
                    return picture_line()
                return b""
        return detection_line()

    def close(self):
        pass


@pytest.fixture
def feed(monkeypatch):
    import sys
    import types
    fake = FakeSerial()
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=lambda *a, **k: fake))
    f = SerialDetectionFeed("/dev/null", auto_start=False, labels=["face"])
    f._ser = fake
    return f, fake


def test_snapshot_stops_the_loop_asks_once_and_restarts_it(feed, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    f, ser = feed
    snap = f.snapshot(timeout_s=2.0)
    assert snap is not None and snap.jpeg == JPEG and snap.detections[0][0] == "face"
    cmds = [w for w in ser.writes]
    assert cmds == [b"AT+BREAK\r\n", b"AT+INVOKE=1,0,0\r\n", b"AT+BREAK\r\n", b"AT+INVOKE=-1,0,1\r\n"]     # stop, one shot, stop, loop again


def test_snapshot_returns_none_when_the_module_is_silent_and_still_restarts_detection(monkeypatch):
    import sys
    import types
    fake = FakeSerial(answer=False)
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=lambda *a, **k: fake))
    f = SerialDetectionFeed("/dev/null", auto_start=False)
    f._ser = fake
    assert f.snapshot(timeout_s=0.05) is None
    assert fake.writes[-1] == b"AT+INVOKE=-1,0,1\r\n"


def test_a_snapshot_taken_while_the_background_reader_runs(feed):
    f, ser = feed
    src = BackgroundFrameSource(f, max_age_s=5.0).start()
    try:
        deadline = time.monotonic() + 3.0
        while not src() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert src(), "the reader should be producing detections"
        snap = src.snapshot(timeout_s=3.0)
        assert snap is not None and snap.jpeg == JPEG
        deadline = time.monotonic() + 3.0
        while not src() and time.monotonic() < deadline:      # detections come back after the picture
            time.sleep(0.01)
        assert src()
    finally:
        src._stop.set()


def test_every_snapshot_makes_the_shutter_click_and_a_silent_module_does_not(feed, monkeypatch):
    from pi_pipeline.voice import shutter
    monkeypatch.setattr(time, "sleep", lambda s: None)
    clicks = []
    monkeypatch.setattr(shutter, "click", lambda: clicks.append(1))
    f, ser = feed
    assert f.snapshot(timeout_s=2.0) is not None
    assert clicks == [1]
    ser.answer = False
    assert f.snapshot(timeout_s=0.3) is None
    assert clicks == [1]


def test_a_picture_is_taken_at_240_then_detection_goes_back_to_its_own_capture_option(monkeypatch):
    """The module's JPEG buffer cuts a 480 x 480 picture short, so the feed switches to the 240 option for the picture only."""
    import sys
    import types
    monkeypatch.setattr(time, "sleep", lambda s: None)
    fake = FakeSerial()
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=lambda *a, **k: fake))
    f = SerialDetectionFeed("/dev/null", auto_start=False, labels=["face"], sensor_opt=1, ae_bump=0)
    f._ser = fake
    assert f.snapshot(timeout_s=2.0) is not None
    w = fake.writes
    assert w == [b"AT+BREAK\r\n", b"AT+SENSOR=1,1,0\r\n", b"AT+INVOKE=1,0,0\r\n", b"AT+BREAK\r\n", b"AT+SENSOR=1,1,1\r\n", b"AT+INVOKE=-1,0,1\r\n"]


def test_no_switch_when_the_detection_option_is_already_the_picture_option_or_unknown(monkeypatch):
    import sys
    import types
    monkeypatch.setattr(time, "sleep", lambda s: None)
    for sensor_opt, snap_opt in ((0, 0), (None, 0), (1, None)):
        fake = FakeSerial()
        monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(Serial=lambda *a, **k: fake))
        f = SerialDetectionFeed("/dev/null", auto_start=False, labels=["face"], sensor_opt=sensor_opt, snapshot_sensor_opt=snap_opt)
        f._ser = fake
        f.snapshot(timeout_s=2.0)
        assert not any(b"AT+SENSOR" in x for x in fake.writes)
