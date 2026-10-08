import threading
import time
import types

from pi_pipeline.app.sinks import SerialActuatorSink, WalkerSink
from pi_pipeline.gait.policy_walker import PolicyWalker
from pi_pipeline.link.fanout import ImuFanout
from pi_pipeline.voice.actuator import SerialActuator


class Link:
    def __init__(self):
        self.sent, self._imu = [], []

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""

    def poll_imu(self):
        out, self._imu = self._imu, []
        return out


def test_each_consumer_gets_every_imu_line():
    link = Link()
    fan = ImuFanout(link)
    a, b = fan.consumer(), fan.consumer()
    link._imu = ["l1", "l2"]
    assert a.poll_imu() == ["l1", "l2"] and b.poll_imu() == ["l1", "l2"]
    assert a.poll_imu() == [] and b.poll_imu() == []
    link._imu = ["l3"]
    assert b.poll_imu() == ["l3"] and a.poll_imu() == ["l3"]
    a.send("x")
    assert link.sent == ["x"]                                   # everything else passes through


class FakeWalker:
    def __init__(self):
        self.busy, self.calls = False, []

    def walk(self, seconds=None):
        self.busy = True
        self.calls.append(("walk", seconds))

    def stop(self, rest=True, timeout=5.0):
        if self.busy:
            self.calls.append(("stop", rest))
        self.busy = False


def test_walk_forward_uses_the_learned_policy_not_the_firmware_gait():
    link, w = Link(), FakeWalker()
    act = SerialActuator("x", 1, link=link, policy_walker=w)
    act.perform("walk_forward", 5)
    assert w.calls == [("walk", 5.0)] and "kwkF" not in link.sent and act.busy
    act.perform("turn_left" if False else "sit")                   # another skill replaces the walk, without resting first
    assert ("stop", False) in w.calls and not act.busy
    act.perform("walk_forward")
    act.stop()
    assert ("stop", True) in w.calls and link.sent[-1] == "d"


def test_without_a_walker_the_firmware_gait_is_still_used():
    link = Link()
    SerialActuator("x", 1, link=link).perform("walk_forward")
    assert "kwkF" in link.sent


def test_explore_walker_uses_policy_straight_and_firmware_for_turns():
    link, w = Link(), FakeWalker()
    s = WalkerSink(link, policy_walker=w)
    s.walk(0.0)
    s.walk(0.0)                                                 # already walking: no restart
    assert w.calls == [("walk", None)] and link.sent == []
    s.walk(0.5)                                                 # a right-hand curve is a firmware gait
    assert w.calls[-1] == ("stop", False) and link.sent == ["kwkR"]
    s.walk(0.0)                                                 # back to straight: the policy again
    assert w.calls[-1] == ("walk", None)
    s.stop()
    assert w.calls[-1] == ("stop", True) and link.sent[-1] == "d"
    act = SerialActuatorSink(link, policy_walker=w)
    w.busy = True
    act.perform("kup")
    assert w.calls[-1] == ("stop", False)


def test_policy_walker_runs_the_loop_in_a_thread_and_stops_it():
    started, ended = threading.Event(), []

    def fake_run(lk, cmd, seconds, hz, fmt, balance_off, stop_event=None, in_service=False, on_battery=None):
        started.set()
        assert in_service and balance_off and cmd == 0.10
        while not stop_event.is_set():
            time.sleep(0.005)
        ended.append(getattr(stop_event, "rest", True))

    w = PolicyWalker(Link(), run_fn=fake_run)
    w.walk(10)
    assert started.wait(2) and w.busy
    w.stop(rest=False)
    assert not w.busy and ended == [False]
    w.stop()                                                    # stopping an idle walker is harmless


def test_a_walk_that_ends_in_a_fall_calls_the_fall_handler_and_other_endings_do_not():
    """On 2026-10-07 the exploration kept sending walks after G2 fell (three more, on his back). The walker now reports a fall so the session can halt."""
    import time
    from pi_pipeline.gait.policy_walker import PolicyWalker
    for reason, expect in (("fall", 1), ("stopped", 0), ("complete", 0), (None, 0)):
        fell = []
        w = PolicyWalker(object(), run_fn=lambda *a, _r=reason, **k: _r, on_fall=lambda: fell.append(1))
        w.walk(1.0)
        deadline = time.time() + 2.0
        while w.busy and time.time() < deadline:
            time.sleep(0.01)
        assert len(fell) == expect, reason


def test_policy_walker_passes_the_foot_hold_and_respects_off(monkeypatch):
    import time
    from pi_pipeline.gait.policy_walker import PolicyWalker, default_foot_hold
    seen = []

    def fake_run(lk, cmd, seconds, hz, fmt, dis, **kw):
        seen.append(kw.get("foot_hold", "absent"))
        return "complete"

    def legacy_run(lk, cmd, seconds, hz, fmt, dis, stop_event=None, in_service=False, on_battery=None):
        seen.append("legacy")
        return "complete"

    monkeypatch.delenv("G2_FOOT_HOLD", raising=False)
    assert default_foot_hold() == "fl"
    for fn, hold in ((fake_run, "env"), (fake_run, None), (legacy_run, "env")):
        w = PolicyWalker(object(), run_fn=fn, foot_hold=hold)
        w.walk(1)
        for _ in range(100):
            if not w.busy:
                break
            time.sleep(0.01)
    assert seen == ["fl", "absent", "legacy"]
    monkeypatch.setenv("G2_FOOT_HOLD", "off")
    assert default_foot_hold() is None


def test_a_turn_is_timed_and_the_straight_policy_walk_waits_for_it():
    link, w = Link(), FakeWalker()
    now = [100.0]
    s = WalkerSink(link, policy_walker=w, clock=lambda: now[0])
    s.walk(0.0)
    assert w.calls == [("walk", None)]
    s.turn(0.9)                                                  # about 52 deg to the right: 0.85 * 52 / 18 deg/s = 2.5 s of the firmware turn
    assert link.sent == ["kwkR"] and s.turning() and w.calls[-1] == ("stop", False)
    now[0] += 1.0
    s.walk(0.0)                                                  # the next WANDER tick: the turn is left alone
    s.turn(0.9)
    assert link.sent == ["kwkR"] and w.calls[-1] == ("stop", False)
    now[0] += 1.6                                                # 2.6 s in: the turn is over
    assert not s.turning()
    s.walk(0.0)
    assert w.calls[-1] == ("walk", None)                         # the learned policy walks on, straight, with a fresh hold


def test_a_left_turn_takes_longer_than_a_right_turn_and_small_or_nested_turns_are_ignored():
    for rad, expect_s in ((0.9, 2.5), (-0.9, 4.2)):
        link, w = Link(), FakeWalker()
        now = [0.0]
        s = WalkerSink(link, policy_walker=w, clock=lambda: now[0])
        s.turn(rad)
        now[0] = expect_s - 0.3
        assert s.turning()
        now[0] = expect_s + 0.3
        assert not s.turning()
    link, w = Link(), FakeWalker()
    s = WalkerSink(link, policy_walker=w, clock=lambda: 0.0)
    s.turn(0.05)                                                 # under 7 deg: nothing is sent
    assert link.sent == [] and not s.turning()
    s.turn(6.0)                                                  # a huge turn is capped at 6 s
    assert 0.0 < s._turn_until <= 6.0
    s.stop()                                                     # a stop cancels the turn
    assert s._turn_until == 0.0


def test_a_walker_stopped_from_its_own_thread_does_not_raise_and_a_resting_g2_is_not_told_to_rest_again():
    from pi_pipeline.gait.policy_walker import PolicyWalker
    errors = []
    holder = {}

    def fake_run(lk, cmd, seconds, hz, fmt, dis, stop_event=None, in_service=False, on_battery=None, **kw):
        try:
            holder["w"].stop(rest=False)               # the fall callback does this from the walker thread
        except Exception as e:  # noqa: BLE001
            errors.append(e)
        return "complete"

    w = PolicyWalker(object(), run_fn=fake_run, foot_hold=None)
    holder["w"] = w
    w.walk(1)
    for _ in range(100):
        if not w.busy:
            break
        __import__("time").sleep(0.01)
    assert errors == []
    # a link that remembers the last leg command: the second rest is not sent
    class L(Link):
        last_motion_command = ""
        def send(self, cmd, **kw):
            super().send(cmd, **kw)
            if cmd[:1] in ("k", "d", "i", "m"):
                self.last_motion_command = cmd
    link, walker = L(), FakeWalker()
    s = WalkerSink(link, policy_walker=walker)
    s.stop(); s.stop(); s.stop()
    assert link.sent == ["d"]
    s.walk(0.9); s.stop()                              # a turn command moved the legs: rest again
    assert link.sent.count("d") == 2
