"""The jaw range helper (behavior/jaw_range.py): the steps it takes, the limits it keeps and what it sends."""
import pytest

from pi_pipeline.behavior import jaw_range as j


class Robot:
    def __init__(self, fell_at=None):
        self.tx, self.poses, self.fell_at, self.polls = [], [], fell_at, 0

    def claw_pose(self, pan, lift):
        self.poses.append((pan, lift))
        return "ok"

    def _tx(self, c):
        self.tx.append(c)

    def _fell(self):
        self.polls += 1
        return self.fell_at is not None and self.polls >= self.fell_at


def test_the_sweep_goes_in_small_steps_and_ends_on_the_target():
    assert j.sweep_angles(0, 40, 10) == [10, 20, 30, 40]
    assert j.sweep_angles(20, -10, 10) == [10, 0, -10]
    assert j.sweep_angles(0, 25, 10)[-1] == 25 and max(abs(b - a) for a, b in zip([0] + j.sweep_angles(0, 25, 10), j.sweep_angles(0, 25, 10))) <= 10


def test_ranges_the_helper_refuses():
    for start, target, step in ((0, 130, 10), (0, 70, 10), (0, 0, 10), (0, 40, 0), (0, 40, 20), (0, 60, 4)):
        with pytest.raises(ValueError):
            j.sweep_angles(start, target, step)


def test_the_arm_is_raised_before_the_jaw_moves_and_lowered_after():
    r = Robot()
    rec = j.run_sweep(r, 0, 30, 10, say=lambda *_: None, sleep=lambda s: None)
    assert rec["state"] == "ok" and r.poses == [(0.0, j.LIFT_HOLD_DEG), (0.0, 0.0)]                      # the claw look's way up first, down at the end
    assert [c for c in r.tx if c.startswith("i2")] == ["i2 10", "i2 20", "i2 30", "i2 20", "i2 10", "i2 0"]   # out to the target, then back to where it started
    assert r.tx[0] == "gP"
    assert [s[2] for s in rec["steps"]] == ["out"] * 3 + ["back"] * 3


def test_a_fall_stops_the_sweep_and_leaves_the_arm_alone():
    r = Robot(fell_at=2)
    rec = j.run_sweep(r, 0, 30, 10, say=lambda *_: None, sleep=lambda s: None)
    assert rec["state"] == "fell" and r.poses == [(0.0, j.LIFT_HOLD_DEG)] and len([c for c in r.tx if c.startswith("i2")]) == 2


def test_the_marks_give_the_speed_series_command_line():
    answers = iter(["60", "-10", "", "stiff at the end"])
    marks = j.ask_marks(ask=lambda _p: next(answers))
    assert marks == {"open": 60.0, "closed": -10.0, "stopped_at": None, "note": "stiff at the end"}
    assert j.command_line(marks) == "g2armspeed --series jaw --speed 4 --jaw-open 60 --jaw-closed -10"
    assert j.command_line({"open": 60.0, "closed": None}) is None
