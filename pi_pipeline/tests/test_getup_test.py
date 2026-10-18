"""gait/getup_test.py: refuses an upright start, sends the right tokens in order, and decides success from the IMU."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "gait"))
import getup_test as G  # noqa: E402


def _line(roll_deg, pitch_deg):
    return f"ICM:  0.00  0.00  9.80   0.0 {pitch_deg:6.1f} {roll_deg:6.1f}"


class FakeLink:
    def __init__(self, script):
        self.script = script                  # list of (time, roll, pitch), the pose the IMU reports from that time on
        self.sent, self.t = [], 0.0

    def send(self, cmd, **kw):
        self.sent.append(cmd)

    def poll_imu(self):
        _t, roll, pitch = [row for row in self.script if row[0] <= self.t][-1]
        return [_line(roll, pitch)]


def _run(script, seq="rl_rc", **kw):
    lk = FakeLink(script)
    clock = lambda: lk.t                                     # noqa: E731
    def sleep(s):
        lk.t += s
    return lk, G.run_getup(lk, seq, sleep=sleep, clock=clock, **kw)


def test_parse_check():
    from imu_parse import parse_imu_line
    r = parse_imu_line(_line(80.0, 5.0))
    assert r is not None and abs(math.degrees(r[0]) - 80.0) < 1.0


def test_an_upright_start_is_refused_and_nothing_moves():
    lk, res = _run([(0.0, 3.0, 2.0)])
    assert res["ok"] is False and "upright" in res["why"] and not any(c.startswith("k") for c in lk.sent)


def test_a_side_lie_that_ends_upright_is_a_success_and_the_tokens_go_in_order():
    lk, res = _run([(0.0, 85.0, 3.0), (7.0, 5.0, 3.0)])                # lying on his right side, upright from 5 s into the attempt
    assert res["ok"] and res["upright"] and res["lying"] == "right side" and res["seconds_to_upright"] is not None
    ks = [c for c in lk.sent if c in ("krl", "krc", "kbalance", "d")]
    assert ks == ["krl", "krc", "kbalance", "d"]


def test_a_move_that_does_not_get_him_up_ends_with_rest_only():
    lk, res = _run([(0.0, -80.0, 4.0)], seq="rc", seconds=4.0)
    assert res["ok"] and res["upright"] is False and res["lying"] == "left side" and res["max_tilt"] >= 80
    assert [c for c in lk.sent if c in ("krc", "kbalance", "d")] == ["krc", "d"]
    assert "gb" in lk.sent or "gB" in lk.sent
