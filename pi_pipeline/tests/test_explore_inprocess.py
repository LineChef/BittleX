"""An exploration run inside the voice service (explore_session.run_inprocess) on fake parts: it borrows the service's link, walker and fan-out and gives them
back as it found them, without closing anything."""
import threading
import time

from pi_pipeline import explore_session as E
from pi_pipeline.link.fanout import ImuFanout


class FakeLink:
    def __init__(self):
        self.sent, self.closed = [], False
        self.last_motion_command = ""

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""

    def poll_imu(self):
        return []

    def close(self):
        self.closed = True

    def __getattr__(self, name):              # anything else the runtime asks of a link: a harmless no-op
        return lambda *a, **k: None


class Walker:
    busy = False

    def __init__(self):
        self._on_battery, self._on_fall, self._hold, self._on_stall, self._on_contact = "b", "f", False, "s", "c"
        self.stops = []

    def walk(self, seconds=None):
        return True

    def stop(self, *, rest=True, timeout=5.0):
        self.stops.append(rest)


class Wake:
    def __init__(self):
        self.ev = threading.Event()

    def wait(self):
        self.ev.wait(30)


class Stt:
    def listen(self, timeout_s=None):
        return ""


def test_run_inprocess_gives_everything_back(monkeypatch, tmp_path):
    from pi_pipeline.app import __main__ as A
    monkeypatch.setattr(A, "_make_vision_source", lambda *a, **k: None)     # no camera on the test machine
    monkeypatch.setenv("G2_EXPLORE_PICTURES_DIR", str(tmp_path))
    monkeypatch.setenv("G2_COMPLETE_SOUND", "0")
    monkeypatch.setenv("G2_FALL_HORN", "off")
    real_parse = E.parse_args
    monkeypatch.setattr(E, "parse_args", lambda argv=None: (lambda a: (setattr(a, "max_s", 1.0), setattr(a, "no_narrate", True), a)[-1])(real_parse(argv)))
    real_sleep = time.sleep
    monkeypatch.setattr(E.time, "sleep", lambda s: real_sleep(min(s, 0.05)))      # the clean-up's settle pauses, shortened
    link, walker, wake = FakeLink(), Walker(), Wake()
    fan = ImuFanout(link)
    before = len(fan._queues)
    shared = E.SharedParts(link=link, fan=fan, policy_walker=walker, memory=None, tts=None, wake=wake, stt=Stt())
    t0 = time.monotonic()
    try:
        ended = E.run_inprocess(shared, 60)
    finally:
        wake.ev.set()
    assert time.monotonic() - t0 < 20
    assert ended                                                       # it ended and said how
    assert not link.closed and not shared.exploring.is_set()           # the service's link stays open; the guards are back on duty
    assert (walker._on_battery, walker._on_fall, walker._hold, walker._on_stall, walker._on_contact) == ("b", "f", False, "s", "c")
    assert len(fan._queues) == before                                  # every IMU stream it took was handed back
    assert "d" in link.sent                                            # he lay down at the end
