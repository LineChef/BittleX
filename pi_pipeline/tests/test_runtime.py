import random

from pi_pipeline.behavior import (
    BehaviorDriver, BehaviorRuntime, Mode, Posture, SleepState,
    latest_frame_source,
)
from pi_pipeline.behavior.bindings import MockBindings
from pi_pipeline.behavior.sleep_mode import SleepModeConfig
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.vision.feed import Detection, MockDetectionFeed


class Clk:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


def _rt(**driver_kw):
    c = Clk()
    p = driver_kw.pop("params", BehaviorParams(
        idle_secs_before_explore=1e9, idle_sit_secs=5, idle_rest_secs=10))
    d = BehaviorDriver(p, clock=c, rng=random.Random(0), **driver_kw)
    mb = MockBindings()
    rt = BehaviorRuntime(d, mb, hz=0, clock=c)
    return rt, mb, c


# ------------------------------------------------------------- basic ticking
def test_idle_descent_dispatches_through_the_bindings():
    rt, mb, c = _rt()
    for _ in range(60):
        c.adv(1.0)
        rt.tick()
    seen = [n for n, _a, _k in mb.calls]
    assert "actuator.perform" in seen
    perf = [a[0] for n, a, _k in mb.calls if n == "actuator.perform"]
    assert "ksit" in perf and "d" in perf
    assert perf.index("ksit") < perf.index("d")


def test_max_ticks_bounds_run_forever():
    rt, mb, c = _rt()
    ticks = {"n": 0}
    rt._sleep = lambda _s: c.adv(1.0)
    rt._period = 0.2                        # so _sleep is actually called
    rt._sensors = lambda: (ticks.__setitem__("n", ticks["n"] + 1) or {})
    rt.run_forever(max_ticks=7)
    assert ticks["n"] == 7 and rt.last_tick is not None


def test_stop_from_a_source_callback_ends_the_loop():
    rt, mb, c = _rt()
    ticks = {"n": 0}

    def sensors():
        ticks["n"] += 1
        if ticks["n"] == 4:
            rt.stop()
        return {}

    rt._sensors = sensors
    rt.run_forever(max_ticks=99)
    assert ticks["n"] == 4


# --------------------------------------------------------- the event queue
def test_posted_event_flows_in_and_is_consumed_once():
    rt, mb, c = _rt()
    c.adv(0.5)
    rt.post(say_hi=True)
    rt.tick()
    say_hi_skills = [a[0] for n, a, _k in mb.calls
                     if n == "actuator.perform"]
    assert say_hi_skills                       # a greeting skill went out
    before = len(mb.calls)
    c.adv(0.5)
    rt.tick()                                  # event must not re-fire
    assert not [1 for n, a, _k in mb.calls[before:]
                if n == "actuator.perform"]


def test_events_merge_between_ticks():
    rt, mb, c = _rt()
    rt.post(loud_sound=True)
    rt.post(wake_word=True, meet_name="")      # blank meet_name ignored
    merged = rt._pending.drain()
    assert merged == {"loud_sound": True, "wake_word": True}


def test_unknown_event_key_raises():
    rt, _mb, _c = _rt()
    try:
        rt.post(banana=True)
    except KeyError as e:
        assert "banana" in str(e)
    else:                                       # pragma: no cover
        raise AssertionError("expected KeyError")


# ------------------------------------------------------------- pause / resume
def test_pause_holds_ticks_but_keeps_queued_events():
    rt, mb, c = _rt()
    rt.pause()
    rt.post(say_hi=True)
    assert rt.tick() is None
    assert mb.calls == []
    rt.resume()
    c.adv(0.5)
    rt.tick()
    assert any(n == "actuator.perform" for n, _a, _k in mb.calls)


# --------------------------------------------- sleep -> wake through the loop
def test_runtime_sleeps_then_wakes_on_a_posted_wake_word():
    rt, mb, c = _rt(sleep_cfg=SleepModeConfig(sleep_after_resting_s=20.0,
                                              settle_timeout_s=2.0,
                                              min_sleep_s=1.0))
    for _ in range(60):                        # quiet -> descend -> sleep
        c.adv(1.0)
        rt.tick()
    assert rt.last_tick.sleep_state in (SleepState.DOZING, SleepState.ASLEEP)
    powered = [a[0] for n, a, _k in mb.calls if n == "power.set_profile"]
    assert "headless" in powered

    c.adv(5.0)
    rt.post(wake_word=True)
    rt.tick()
    powered = [a[0] for n, a, _k in mb.calls if n == "power.set_profile"]
    assert powered[-1] == "interactive"
    assert rt.last_tick.mode is Mode.CONVERSE


# --------------------------------------------------- sensor + frame sources
def test_sensor_source_feeds_continuous_state():
    rt, mb, c = _rt()

    def sensors():
        return {"person_present": True, "held": False}

    rt._sensors = sensors
    c.adv(30.0)
    tick = rt.tick()
    # person_present lengthens the sit->rest delay (x4) -> still SIT, not RESTING
    assert tick.posture is Posture.SIT


def test_latest_frame_source_adapts_a_detection_feed():
    frames = [[Detection("sam", 0.9, 0.4, 0.4, 0.2, 0.2)],
              [Detection("sam", 0.9, 0.4, 0.4, 0.2, 0.2)]]
    feed = MockDetectionFeed(frames)
    src = latest_frame_source(feed)
    got = src()
    assert got and got[0].label == "sam"


def test_roster_plus_frame_drives_the_recognition_hop():
    rt, mb, c = _rt()
    rt.driver._vision = True
    rt._frame_source = lambda: [Detection("sam", 0.9, 0.4, 0.4, 0.25, 0.25)]
    rt._roster = lambda: {"sam"}
    c.adv(0.5)
    rt.tick()
    perf = [a[0] for n, a, _k in mb.calls if n == "actuator.perform"]
    assert perf                                 # an excited-hop skill / HAPPY chirp
    assert any(str(x).startswith("b") for x in perf)   # the HAPPY chirp string
