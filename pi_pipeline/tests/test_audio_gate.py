"""One sound at a time (voice/audio_gate.py): a new sound waits for the one playing instead of cutting it off."""
import threading
import time
import types

from pi_pipeline.voice import audio_gate


class FakeSD:
    """play() starts a 'stream' that is active for `dur` seconds and, like the real one, STOPS a stream still playing."""
    def __init__(self):
        self.events, self._end, self._lock = [], 0.0, threading.Lock()

    def play(self, data, rate=None, **kw):
        now = time.monotonic()
        if now < self._end:
            self.events.append(("CUT", data))
        self.events.append(("start", data))
        self._end = now + (data if isinstance(data, float) else 0.15)

    def get_stream(self):
        return types.SimpleNamespace(active=time.monotonic() < self._end)


def test_a_new_sound_waits_for_the_one_playing_instead_of_cutting_it():
    sd = FakeSD()
    assert audio_gate.install(sd=sd) and audio_gate.install(sd=sd)                 # installing twice is harmless
    t0 = time.monotonic()
    sd.play(0.2)                                                                     # a sentence
    sd.play(0.05)                                                                    # a chirp right behind it
    assert not any(e[0] == "CUT" for e in sd.events)
    assert time.monotonic() - t0 >= 0.19                                             # it waited for the sentence to end


def test_two_threads_queue_in_order_and_a_long_sound_is_not_waited_for_forever(monkeypatch):
    sd = FakeSD()
    audio_gate.install(max_wait_s=0.1, sd=sd)
    sd.play(0.6)
    t0 = time.monotonic()
    sd.play(0.01)                                                                    # waits only max_wait_s, then cuts in as before (a safety sound is never held back long)
    assert 0.09 <= time.monotonic() - t0 < 0.4 and [e[0] for e in sd.events] == ["start", "CUT", "start"]


def test_the_gate_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("G2_AUDIO_GATE", "0")
    sd = FakeSD()
    assert audio_gate.install(sd=sd) is False and not getattr(sd, "_g2_gate", False)


def test_beeps_and_speech_wait_for_each_other(monkeypatch):
    from pi_pipeline.voice import audio_gate as g
    assert abs(g.beep_seconds("b9 5 16 8") - (1 / 5 + 1 / 8)) < 1e-9 and g.beep_seconds("kup") == 0.0
    sd = FakeSD()
    g._beep_until = 0.0
    g.note_beep(0.2)                                                                  # the BiBoard is beeping
    t0 = time.monotonic()
    assert g.wait_idle(1.0, sd=sd) and time.monotonic() - t0 >= 0.19
    g.note_beep(0.2)
    sd2 = FakeSD()
    audio_gate.install(sd=sd2)
    t0 = time.monotonic()
    sd2.play(0.01)                                                                    # a sentence about to start waits for the beep
    assert time.monotonic() - t0 >= 0.15


def test_the_serial_link_waits_for_speech_before_a_beep_and_tells_the_gate(monkeypatch):
    import pi_pipeline.voice.audio_gate as g
    from pi_pipeline.link.serial_link import SerialLink
    calls = []
    monkeypatch.setattr(g, "wait_idle", lambda t=2.0, sd=None: calls.append(("wait", t)) or True)
    monkeypatch.setattr(g, "note_beep", lambda s: calls.append(("beep", round(s, 3))))
    link = SerialLink.__new__(SerialLink)
    link._ser = type("S", (), {"write": lambda self, b: None, "flush": lambda self: None, "is_open": True})()
    link._auto_reconnect = False
    link._failed = lambda *a, **k: None
    monkeypatch.setattr(SerialLink, "is_connected", property(lambda self: True))
    monkeypatch.setattr(SerialLink, "_ease_stand_up", lambda self, c: None)
    monkeypatch.setattr(SerialLink, "_read_reply", lambda self, d: "")
    link.last_motion_command = ""
    link.send("b9 5 16 8", read_reply=False, settle=0)
    link.send("kup", read_reply=False, settle=0)
    assert calls == [("wait", 2.0), ("beep", 0.325)]
