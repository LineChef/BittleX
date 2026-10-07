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
