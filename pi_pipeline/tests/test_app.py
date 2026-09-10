import math

from pi_pipeline.app import (
    CameraSink, HeadSink, LockedLink, PowerSink, SensorHub, SerialActuatorSink,
    WalkerSink, build_bindings,
)
from pi_pipeline.app.sensors import SensorConfig
from pi_pipeline.behavior import BehaviorDriver, DriverInputs
from pi_pipeline.behavior.driver import Effect, EffectKind
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.vision.feed import Detection


class FakeLink:
    def __init__(self, lines=()):
        self.sent = []
        self._lines = list(lines)
        self.is_connected = True

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""

    def read_line(self):
        return self._lines.pop(0) if self._lines else ""

    def close(self):
        pass


# ------------------------------------------------------------------ sinks
def test_actuator_sink_sends_safe_refuses_calibration():
    lk = FakeLink()
    s = SerialActuatorSink(lk)
    s.perform("kstr")
    s.perform("b16 10 12 12")            # a chirp string is fine
    s.perform("c 0 0")                   # calibration -> refused
    s.perform("  ")                      # empty -> ignored
    s.stop()
    assert lk.sent == ["kstr", "b16 10 12 12", "d"]


def test_head_sink_center_sweep_and_bearing():
    lk = FakeLink()
    h = HeadSink(lk, pan_deg=45.0)
    h.move("center")
    h.move("pan_sweep")
    h.move(math.radians(90))            # clamped to +45
    assert lk.sent[0] == "m0 0"
    assert lk.sent[1:4] == ["m0 -36", "m0 36", "m0 0"]
    assert lk.sent[4] == "m0 45"


def test_walker_sink_is_continuous_and_turns_on_bias():
    lk = FakeLink()
    w = WalkerSink(lk, turn_threshold=0.15)
    w.walk(0.0); w.walk(0.0)            # forward, sent once
    w.walk(0.5)                         # bias right
    w.turn(-1.0)                        # left
    assert lk.sent == ["kwkF", "kwkR", "kwkL"]


def test_power_sink_calls_profiles(monkeypatch):
    calls = []
    import pi_pipeline.power as power
    monkeypatch.setattr(power, "apply_headless_profile", lambda d=None: calls.append("headless"))
    monkeypatch.setattr(power, "apply_interactive_profile", lambda d=None: calls.append("interactive"))
    p = PowerSink()
    p.set_profile("headless")
    p.set_profile("interactive")
    p.set_profile("bogus")             # ignored
    assert calls == ["headless", "interactive"]


def test_camera_sink_toggles_and_fires_hook():
    seen = []
    c = CameraSink(on_toggle=lambda on, kind: seen.append((on, kind)))
    c.set_capture(True, "face")
    assert c.capturing and seen == [(True, "face")]
    c.set_capture(False)
    assert not c.capturing


def test_locked_link_passes_through():
    lk = FakeLink(lines=["ypr 1 2 3"])
    ll = LockedLink(lk)
    ll.send("kbalance", read_reply=False)
    assert lk.sent == ["kbalance"] and ll.read_line() == "ypr 1 2 3"
    assert ll.is_connected


def test_build_bindings_dispatches_a_full_tick_without_error():
    lk = FakeLink()
    b = build_bindings(lk, dry_run_power=True)
    out = b.dispatch([
        Effect(EffectKind.SKILL, "kstr"),
        Effect(EffectKind.STOP, None),
        Effect(EffectKind.WALK, 0.0),
        Effect(EffectKind.TURN, 0.5),
        Effect(EffectKind.HEAD, "center"),
        Effect(EffectKind.POWER, "headless"),
        Effect(EffectKind.CAPTURE, ("off", None)),
        Effect(EffectKind.DIAG, ("sleep", "enter")),
    ])
    assert "drop:skill" not in out and "drop:power" not in out
    assert any(c.startswith("k") or c == "d" for c in lk.sent)


def test_bindings_drive_a_real_driver_tick():
    lk = FakeLink()
    b = build_bindings(lk, dry_run_power=True)
    t = [1000.0]
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9,
                                      idle_sit_secs=2, idle_rest_secs=5),
                       clock=lambda: t[0])
    t[0] += 5.0
    b.dispatch(d.tick(DriverInputs()))         # 5s quiet -> descend to SIT
    assert "ksit" in lk.sent


# ------------------------------------------------------------------ SensorHub
def test_sensorhub_reads_level_from_imu():
    lk = FakeLink(lines=["ypr 0 3 2"])          # yaw pitch roll, near-level
    sh = SensorHub(lk, cfg=SensorConfig(level_deg=25.0))
    s = sh.sample()
    assert s["imu_level"] and s["imu_stable"] and not s["held"]


def test_sensorhub_flags_unlevel_then_held():
    t = [0.0]
    # roll 60deg, big gyro -> unlevel + unstable
    lk = FakeLink(lines=["1.05 0 0 3 3 3"] * 10)
    sh = SensorHub(lk, cfg=SensorConfig(held_after_s=0.5), clock=lambda: t[0])
    lk._lines = ["60 0 60 200 0 0"]              # y p r gx gy gz (deg)
    s1 = sh.sample()
    assert not s1["imu_level"] and not s1["imu_stable"] and not s1["held"]
    t[0] = 1.0
    lk._lines = ["60 0 60 200 0 0"]
    s2 = sh.sample()
    assert s2["held"]                            # sustained -> picked up


def test_sensorhub_person_present_from_feed():
    frame = [Detection("face", 0.8, 0.4, 0.4, 0.2, 0.2)]
    sh = SensorHub(None, feed_source=lambda: frame)
    assert sh.sample()["person_present"]
    sh2 = SensorHub(None, feed_source=lambda: [Detection("dog", 0.9, 0, 0, 0.2, 0.2)])
    assert not sh2.sample()["person_present"]


def test_sensorhub_stale_imu_assumes_level():
    t = [0.0]
    lk = FakeLink(lines=["60 0 60 300 0 0"])
    sh = SensorHub(lk, cfg=SensorConfig(stale_after_s=1.0), clock=lambda: t[0])
    sh.sample()                                   # unlevel
    t[0] = 5.0                                    # no more lines -> stale
    s = sh.sample()
    assert s["imu_level"] and s["imu_stable"]


# ---------------------------------------------- B: the integrated runtime build
def test_build_runtime_wires_a_working_loop():
    from pi_pipeline.app.__main__ import _build_runtime
    from pi_pipeline.behavior import Mode

    rt = _build_runtime(None, hz=0)            # null link -> serial sinks no-op
    rt.tick()                                  # a bare tick doesn't raise
    rt.post(wake_word=True)
    rt.tick()
    assert rt.last_tick.mode is Mode.CONVERSE
    rt.post(conversation_ended=True)
    rt.tick()
    assert rt.last_tick.mode is Mode.IDLE
