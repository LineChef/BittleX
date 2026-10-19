import math

from pi_pipeline.gait.stand_guard import StandGuard, WobbleDetector
from pi_pipeline.link.locked import LockedLink
from pi_pipeline.voice.actuator import SerialActuator


def feed(det, samples, dt=0.2):
    t, out = 0.0, []
    for roll, pitch in samples:
        t += dt
        out.append(det.update(t, roll, pitch))
    return out


def test_steady_standing_never_trips():
    assert not any(feed(WobbleDetector(), [(1.7 + 0.05 * ((i % 3) - 1), -2.3) for i in range(200)]))


def test_a_sustained_2hz_oscillation_trips_within_a_few_seconds_of_filling_the_window():
    wob = [(2.0 + 3 * math.sin(2 * math.pi * 1.9 * i * 0.2), -2.0 + 3 * math.sin(2 * math.pi * 1.9 * i * 0.2 + 1)) for i in range(120)]
    out = feed(WobbleDetector(), wob)
    first = out.index(True)
    assert first * 0.2 < 10.0                        # window (4 s) + sustain (4 s) after the start


def test_a_nudge_that_rings_down_quickly_does_not_trip():
    bump = [(2 + 6 * math.exp(-i * 0.2 / 0.7) * math.cos(2 * math.pi * 1.5 * i * 0.2), -2) for i in range(25)] + [(2, -2)] * 100
    assert not any(feed(WobbleDetector(), bump))


def test_a_constant_tilt_offset_is_not_a_wobble():
    assert not any(feed(WobbleDetector(), [(15.0, -12.0)] * 200))


# ---- the guard thread logic, driven by hand

def imu_line(roll, pitch):
    return f"ICM: 0.00 0.00 1.00 0.0 {pitch:.1f} {roll:.1f}"


class FakeLink:
    def __init__(self):
        self.sent, self.queue = [], []

    def send(self, cmd, **kw):
        self.sent.append(cmd); return ""

    def poll_imu(self):
        out, self.queue = self.queue, []
        return out


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def wobble_lines(n, start=0):
    return [imu_line(2 + 3 * math.sin(2 * math.pi * 1.9 * (start + i) * 0.2), -2 + 3 * math.sin(2 * math.pi * 1.9 * (start + i) * 0.2 + 1))
            for i in range(n)]


def run_guard(g, link, clock, seconds, lines_per_s=5, busy=None, start=0):
    n = 0
    for _ in range(int(seconds / 0.2)):
        clock.t += 0.2
        link.queue = wobble_lines(1, start + n); n += 1
        g.tick()


def test_start_turns_balance_off_and_starts_the_imu_print():
    link, clock = FakeLink(), Clock()
    StandGuard(link, clock=clock, sleep=lambda s: None).start().stop()
    assert link.sent[:2] == ["gb", "gP"] and "gp" in link.sent


def test_a_wobble_sends_gb_and_counts_a_trip():
    link, clock = FakeLink(), Clock()
    g = StandGuard(link, clock=clock, sleep=lambda s: None, balance_off_idle=False, quiet_after_activity_s=0)
    run_guard(g, link, clock, 15)
    assert g.trips >= 1 and "gb" in link.sent


def test_nothing_trips_while_a_gait_is_running_or_just_after_a_command():
    link, clock = FakeLink(), Clock()
    busy = [True]
    g = StandGuard(link, is_busy=lambda: busy[0], clock=clock, sleep=lambda s: None, balance_off_idle=False)
    run_guard(g, link, clock, 15)
    assert g.trips == 0 and "gb" not in link.sent
    busy[0] = False
    g.note_activity()                                      # a command was just sent: 8 s quiet window
    run_guard(g, link, clock, 6, start=100)
    assert g.trips == 0


def test_balance_off_is_re_asserted_every_minute_when_idle():
    link, clock = FakeLink(), Clock()
    g = StandGuard(link, clock=clock, sleep=lambda s: None, guard=False, reassert_s=60.0)
    for _ in range(int(130 / 0.2)):
        clock.t += 0.2; g.tick()
    assert link.sent.count("gb") == 3                      # at ~0, ~60 and ~120 s


def test_probation_puts_balance_back_after_a_quiet_spell_and_backs_off_if_the_wobble_returns():
    link, clock = FakeLink(), Clock()
    g = StandGuard(link, clock=clock, sleep=lambda s: None, balance_off_idle=False, quiet_after_activity_s=0, reenable_after_s=30.0)
    run_guard(g, link, clock, 15)                         # wobble -> trip -> gb
    assert g.trips == 1 and "gB" not in link.sent
    for _ in range(int(40 / 0.2)):                        # calm for 40 s
        clock.t += 0.2; link.queue = [imu_line(2, -2)]; g.tick()
    assert "gB" in link.sent                              # probation: balance back on
    run_guard(g, link, clock, 15, start=500)              # ...and it wobbles straight away again
    assert g._wait_s == 60.0                              # so the next wait doubles


# ---- the actuator's balance policy

def make_actuator(off_idle):
    link = FakeLink()
    return SerialActuator("x", 1, link=link, balance_off_idle=off_idle), link


def test_gait_gets_balance_on_just_before_and_a_posture_keeps_it_on():
    act, link = make_actuator(True)
    act.perform("walk_forward")
    assert link.sent == ["gB", "kwkF"]
    link.sent.clear(); act.perform("sit")
    assert link.sent == ["ksit"]                                              # a pose keeps balance on (user, 2026-10-19); the stand guard turns it off after
    link.sent.clear(); act.stop()
    assert link.sent == ["d", "gb"]


def test_the_old_behaviour_leaves_balance_alone():
    act, link = make_actuator(False)
    act.perform("walk_forward"); act.perform("sit"); act.stop()
    assert "gB" not in link.sent and "gb" not in link.sent


def test_the_actuator_reports_busy_during_a_gait_and_calls_back_on_commands():
    act, link = make_actuator(True)
    calls = []
    act.on_command = lambda: calls.append(1)
    assert not act.busy
    act.perform("walk_forward"); assert act.busy
    act.stop(); assert not act.busy and len(calls) == 2


def test_locked_link_passes_drain_through():
    class L:
        def drain(self, s=0.3):
            return f"drained {s}"
    assert LockedLink(L()).drain(0.1) == "drained 0.1"


def test_guard_warns_and_retries_gP_if_no_imu_frames_ever_arrive():
    link, clock = FakeLink(), Clock()
    g = StandGuard(link, clock=clock, sleep=lambda s: None, balance_off_idle=False)
    for _ in range(int(40 / 0.2)):
        clock.t += 0.2; g.tick()
    assert g.frames == 0 and link.sent.count("gP") == 1 and g._warned_no_frames


def test_guard_counts_frames():
    link, clock = FakeLink(), Clock()
    g = StandGuard(link, clock=clock, sleep=lambda s: None, balance_off_idle=False)
    link.queue = [imu_line(0, 0)] * 3
    clock.t = 1.0; g.tick()
    assert g.frames == 3


def test_a_fall_at_any_time_calls_on_fall_once_and_rearms_when_he_is_back_up():
    link, clock, falls = FakeLink(), Clock(), []
    g = StandGuard(link, clock=clock, sleep=lambda s: None, on_fall=lambda: falls.append(clock.t), is_busy=lambda: True)   # busy (walking): the fall still counts
    for roll in (5.0, 70.0, 75.0, 80.0, 80.0, 80.0):
        clock.t += 0.2
        link.queue = [imu_line(roll, 3.0)]
        g.tick()
    assert len(falls) == 1                          # tilted past 60 degrees for 0.3 s -> once, not on every frame
    for roll in (10.0, 5.0, 70.0, 75.0, 78.0):
        clock.t += 0.2
        link.queue = [imu_line(roll, 3.0)]
        g.tick()
    assert len(falls) == 2                          # back under 40 degrees re-armed it
    quiet = []
    g2 = StandGuard(link, clock=clock, sleep=lambda s: None, on_fall=lambda: quiet.append(1))
    for _ in range(10):
        clock.t += 0.2
        link.queue = [imu_line(30.0, 20.0)]
        g2.tick()
    assert quiet == []                              # a big lean is not a fall


class EpochLink(FakeLink):
    """Counts the commands that can switch firmware balance on, as SerialLink.balance_epoch does."""
    def __init__(self):
        super().__init__()
        self.balance_epoch = 0

    def send(self, cmd, **kw):
        if cmd == "gB" or cmd.startswith("k"):
            self.balance_epoch += 1
        return super().send(cmd, **kw)


def test_a_swing_while_balance_is_already_off_is_motion_not_a_balance_wobble():
    """2026-10-17/18: four "wobbles" in 20 s, each with balance already off (G2 lying down, being moved): only one gb per 30 s, no WARN trip."""
    link, clock = EpochLink(), Clock()
    g = StandGuard(link, clock=clock, sleep=lambda s: None, quiet_after_activity_s=0, reassert_s=1e9)
    g.start(); g._stop.set()
    assert link.sent.count("gb") == 1                        # the idle policy at start
    run_guard(g, link, clock, 40)
    assert g.trips == 0 and link.sent.count("gb") <= 3       # swings seen, classed as motion; gb re-sent at most every 30 s
    link.send("kbalance")                                    # a skill can switch balance on again
    n = g.trips
    run_guard(g, link, clock, 15, start=500)
    assert g.trips > n                                       # now a swing IS a balance wobble


def test_balance_goes_off_once_a_pose_with_balance_on_is_over():
    link, clock = EpochLink(), Clock()
    link.pose_balance_epoch = 0
    g = StandGuard(link, clock=clock, sleep=lambda s: None, quiet_after_activity_s=8.0, reassert_s=1e9)
    g.start(); g._stop.set()
    link.sent.clear()
    link.pose_balance_epoch += 1; g.note_activity()                # the link sent `gB` before a pose
    for _ in range(35):                                            # 7 s: inside the quiet window, the pose keeps balance on
        clock.t += 0.2; g.tick()
    assert "gb" not in link.sent
    for _ in range(10):                                            # past the 8 s quiet window: balance off, once
        clock.t += 0.2; g.tick()
    assert link.sent.count("gb") == 1


def test_the_link_counts_commands_that_can_switch_balance_on(monkeypatch):
    from pi_pipeline.tests.test_link import _link_with
    lk = _link_with(b"")
    for c in ("gb", "gP", "d", "i8 30", "gB", "kbalance", "b9 5"):
        lk.send(c, read_reply=False, settle=0.0)
    assert lk.balance_epoch == 2 and LockedLink(lk).balance_epoch == 2
