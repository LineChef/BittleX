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


def test_a_side_lie_is_named_by_its_roll_even_when_the_euler_pitch_flips_to_180():
    assert G.classify(108.8, 179.1) == "right side" and G.classify(-95.0, 2.0) == "left side"
    assert G.classify(10.0, 70.0) == "nose down" and G.classify(5.0, -70.0) == "tail down"


def test_streamed_moves_pin_the_head_at_zero_in_every_step_and_end_on_the_last_keyframe():
    cmds, length = G.stream_commands("rl", frame_s=0.5, hold_s=0.1)
    assert length > 0 and cmds[-1][1] == "i0 0 " + " ".join(f"{8 + j} 15" for j in range(8))
    assert all(c.startswith("i0 0 8 ") and len(c.split()) == 18 for _t, c in cmds)                   # head joint 0 at 0, then joints 8..15
    assert [x[0] for x in cmds] == sorted(x[0] for x in cmds)
    assert all(abs(v) <= 100 for _t, c in cmds for v in map(int, c.split()[3::2]))


def test_a_streamed_sequence_runs_both_moves_in_order_and_still_reports_the_result():
    lk, res = _run([(0.0, 85.0, 3.0), (6.0, 5.0, 3.0)], seq="s_rl_rc", frame_s=0.3)
    assert res["ok"] and res["upright"]
    iss = [c for c in lk.sent if c.startswith("i0 0 ")]
    assert 0 < len(iss) <= len(G.timeline("s_rl_rc", 0.3)) and not any(c in lk.sent for c in ("krc", "krl", "kdropRec"))      # it stops sending once he is upright
    assert lk.sent[-1] == "d" and "kbalance" in lk.sent


def test_a_fall_never_commands_the_stand_pose():
    import inspect
    from pi_pipeline import explore_session as E
    from pi_pipeline.gait import run_gait
    assert 'rt.driver.estop.freeze_token = "d"' in inspect.getsource(E.run_session)
    src = inspect.getsource(run_gait)
    assert 'end_pose", None) == "balance" and end_reason[0] != "fall"' in src


def test_every_move_is_sent_exactly_once_and_balance_is_off_by_default():
    lk, res = _run([(0.0, 85.0, 3.0)], seq="rl_rc", seconds=12.0)                   # never gets up: the whole window runs
    assert [c for c in lk.sent if c in ("krl", "krc")] == ["krl", "krc"] and lk.sent.count("d") == 1
    assert "gb" in lk.sent and "gB" not in lk.sent
    lk2, _ = _run([(0.0, 85.0, 3.0)], seq="s_rl", seconds=3.0, frame_s=0.3)
    cmds = [c for c in lk2.sent if c.startswith("i0 ")]
    assert len(cmds) == len(set(cmds)) or len(cmds) == len(G.timeline("s_rl", 0.3))        # one pass through the keyframes, no second pass
