"""The whole-cycle stop, the pre-position and the gait cycle measurement (user, 2026-11-06: falls at transitions)."""
import math

from pi_pipeline.behavior import ball_chase as chase
from pi_pipeline.behavior import gait_cycle, transition_drill


def _wave(period, secs=4.0, hz=60.0):
    t = [i / hz for i in range(int(secs * hz))]
    return t, [8.0 * math.sin(2 * math.pi * x / period) + 0.5 * math.sin(7 * x) for x in t]


def test_estimate_finds_the_period():
    t, roll = _wave(0.55)
    p, strength = gait_cycle.estimate(t, roll, [0.0] * len(t))
    assert abs(p - 0.55) < 0.04 and strength > 0.6


def test_no_cycle_in_a_still_body():
    t = [i / 50 for i in range(200)]
    assert gait_cycle.estimate(t, [0.1] * 200, [0.0] * 200) is None


def test_stop_after_whole_cycles():
    assert abs(gait_cycle.stop_after(1.0, 0.4, 0.8) - 0.2) < 1e-6        # 1.0 s -> 3 cycles = 1.2 s
    assert gait_cycle.stop_after(1.0, 1.0, 0.8) == 0.0                   # already on a boundary
    assert gait_cycle.stop_after(1.0, 1.9, 0.5) is None                  # next boundary 0.9 s away
    assert gait_cycle.stop_after(0.1, 0.4, 0.8) > 0.29                   # at least one cycle


def test_period_order_and_file(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_GAIT_CYCLES", str(tmp_path / "c.json"))
    monkeypatch.delenv("G2_GAIT_CYCLE_S", raising=False)
    assert gait_cycle.period_for("kwkL")[0] is None
    gait_cycle.save("kwkL", 0.5, 0.8, 100)
    assert gait_cycle.period_for("kwkL") == (0.5, "measured")
    monkeypatch.setenv("G2_GAIT_CYCLE_S", "0.7")
    assert gait_cycle.period_for("kwkL") == (0.7, "G2_GAIT_CYCLE_S")
    monkeypatch.setenv("G2_GAIT_CYCLE_S", "99")
    assert gait_cycle.period_for("kwkL")[1] == "measured"


def test_variants_have_the_two_new_levers():
    assert transition_drill.VARIANTS["baseline"] == (False, False, False, False)
    assert transition_drill.VARIANTS["cycle"][2] and transition_drill.VARIANTS["pre"][3]
    assert all(len(v) == 4 for v in transition_drill.VARIANTS.values())


def test_levers_default_off():
    assert chase.CYCLE_STOP is False and chase.PREPOSITION is False


def test_ease_into_records_and_skips_the_second_ramp(monkeypatch):
    from pi_pipeline.link.serial_link import SerialLink
    lk = SerialLink.__new__(SerialLink)
    written = []
    lk._write_pose = written.append
    lk.last_motion_command, lk._last_motion_t, lk._ramping = "kbalance", None, False
    monkeypatch.setattr("pi_pipeline.link.serial_link.time.sleep", lambda s: None)
    monkeypatch.setattr("pi_pipeline.link.transitions.time.sleep", lambda s: None)
    rec = lk.ease_into("kwkL")
    assert rec["cmd"] == "kwkL" and lk.last_ease is rec
    if rec["ran"]:
        assert written and lk._ease_done == "kwkL"
        n = len(written)
        lk._ease_transition("kwkL")
        assert len(written) == n and lk._ease_done is None               # send()'s own ramp is skipped once
    else:
        assert rec["why"]
