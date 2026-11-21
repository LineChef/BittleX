"""The arm speed series (behavior/arm_speed_test.py): the plan it builds, the one-step-at-a-time check, what it writes to the board, and the owner's observation."""
import json

import pytest

from pi_pipeline.behavior import arm_speed_test as t

BASE = [0, 0, 0, 0, 0, 0, 0, 0, 30, 30, -30, -30, 40, 40, -40, -40]      # an arm down at 0, legs in some stand pose
JAW = {"jaw_open": 60.0, "jaw_closed": -10.0}


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


class Link:
    def __init__(self):
        self.messages = []

    def play_data_skill(self, m):
        self.messages.append(m)

    def send(self, c, **_opts):
        raise AssertionError("nothing but the data skill may be written: " + c)


class Robot:
    def __init__(self):
        self._lk, self._roll, self._pitch, self.tx = Link(), [], [], []
        self._n = 0

    def stand_up(self):
        return "ok"

    def _tilt(self, *a, **k):
        return (0.0, 0.0)

    def _tx(self, c):
        self.tx.append(c)

    def _fell(self):
        self._n += 1
        self._roll.append(0.5 * self._n)
        self._pitch.append(0.2 * self._n)
        return False


def test_the_lift_plan_holds_the_legs_and_moves_only_the_lift():
    plan = t.build_plan("lift", 16, BASE, lift_lo=0.0, lift_hi=120.0)
    assert [p["name"] for p in plan] == ["to_start", "lift_up", "lower"]
    for p in plan:
        assert p["frame"][8:] == BASE[8:] and p["frame"][t.JAW] == 0 and p["frame"][t.PAN] == 0     # legs, jaw and pan do not change
    assert [p["frame"][t.LIFT] for p in plan] == [0, 120, 0]
    assert plan[1]["speed"] == 16 and plan[0]["speed"] == plan[2]["speed"] == t.SLOW_BYTE            # only the middle leg runs at the speed under test
    assert plan[1]["deg"] == 120.0 and plan[1]["delay"] == t.HOLD_RAW


def test_the_jaw_plan_raises_the_arm_first_and_returns_the_jaw():
    base = list(BASE)
    base[t.JAW] = 15
    plan = t.build_plan("jaw", 24, base, lift_hold=90.0, **JAW)
    assert [p["name"] for p in plan] == ["raise", "jaw_open_slow", "jaw_close", "jaw_open", "jaw_back", "lower"]
    assert plan[0]["frame"][t.LIFT] == 90 and plan[1]["frame"][t.LIFT] == 90                          # the jaw never moves with the arm down on the floor
    assert [p["frame"][t.JAW] for p in plan[1:5]] == [60, -10, 60, 15]                                # open, closed, open, back to where it was
    assert plan[2]["speed"] == plan[3]["speed"] == 24 and plan[1]["speed"] == plan[4]["speed"] == t.SLOW_BYTE
    assert plan[-1]["frame"][t.LIFT] == 0


REFUSED = [
    ({"speed": -1}, "lift"), ({"speed": 128}, "lift"), ({"speed": 0}, "both"), ({"speed": 4, "lift_hi": 121.0}, "lift"), ({"speed": 4, "lift_lo": 130.0}, "lift"),
    ({"speed": 4, "lift_lo": 50.0, "lift_hi": 40.0}, "lift"), ({"speed": 4}, "jaw"), ({"speed": 4, "jaw_open": 60.0, "jaw_closed": 60.0}, "jaw"), ({"speed": 4, "jaw_open": 130.0, "jaw_closed": 0.0}, "jaw")]


def test_out_of_range_plans_are_refused_before_anything_is_sent():
    for overrides, series in REFUSED:
        args = dict(overrides)
        with pytest.raises(ValueError):
            t.build_plan(series, args.pop("speed"), BASE, **args)
    with pytest.raises(ValueError):
        t.build_plan("lift", 4, BASE[:8])                                                             # no angles for the legs: they cannot be held


def test_a_plan_longer_than_the_silent_window_is_refused():
    with pytest.raises(ValueError, match="silent"):
        t.build_plan("lift", 1, BASE)                                                                  # speed 1: 120 degrees takes 15 s of stepping


def test_the_nominal_times_follow_the_firmware_formula():
    assert t.nominal_s(120, 8) == pytest.approx(120 * 0.008)                                           # speed byte 8 = ratio 1: one degree per 8 ms step
    assert t.nominal_s(120, 16) == pytest.approx(60 * 0.008)
    assert t.nominal_s(120, 16, delay_raw=10) == pytest.approx(60 * 0.008 + 0.5)
    assert t.upper_deg_s(8) == pytest.approx(125.0) and t.upper_deg_s(64) == pytest.approx(1000.0)


def test_the_message_is_a_k_skill_with_a_frame_per_step():
    plan = t.build_plan("lift", 12, BASE)
    m = t.payload_message(plan)
    assert m[:1] == b"K" and m[-1:] == b"~" and len(m) == 1 + 7 + 3 * 20 + 1
    assert m[1] == (-3) & 0xFF                                                                         # a negative frame count is a behavior skill
    body = m[8:-1]
    assert body[16] == 6 and body[36] == 12 and body[56] == 6                                          # each frame ends with its speed byte
    assert body[17] == 4 and body[37] == t.HOLD_RAW and body[57] == 0                                  # and its delay


def test_the_first_run_is_the_baseline_and_each_next_is_one_step(tmp_path):
    assert t.check_step(4, None) is None and "baseline" in t.check_step(6, None)
    last = {"speed_byte": 4, "observation": {"result": "followed"}}
    assert t.check_step(6, last) is None and t.check_step(4, last) is None and t.check_step(2, last) is None
    assert "one step" in t.check_step(8, last)
    assert "no recorded observation" in t.check_step(6, {"speed_byte": 4})
    for bad in t.STOP_RESULTS:
        assert bad in t.check_step(6, {"speed_byte": 4, "observation": {"result": bad}})
        assert t.check_step(4, {"speed_byte": 4, "observation": {"result": bad}}) is None             # repeating the step is fine
    assert t.check_step(127, last, allow_jump=True) is None                                             # the owner's call
    assert t.check_step(127, {"speed_byte": 127, "observation": {"result": "followed"}}) is None        # nothing above the last step to refuse


def test_last_run_reads_the_newest_log_of_the_series(tmp_path):
    for name, sp in (("20261120_100000_lift_s004.json", 4), ("20261120_101000_lift_s006.json", 6), ("20261120_102000_jaw_s004.json", 4)):
        (tmp_path / name).write_text(json.dumps({"speed_byte": sp}))
    (tmp_path / "20261120_103000_lift_s008.json").write_text("{not json")
    assert t.last_run("lift", str(tmp_path))["speed_byte"] == 6 and t.last_run("jaw", str(tmp_path))["speed_byte"] == 4
    assert t.last_run("lift", str(tmp_path / "none")) is None


def test_the_observation_is_typed_in_and_survives_no_input():
    answers = iter(["s", "squeal at the top", "claw clicked"])
    assert t.ask_observation(ask=lambda _p: next(answers)) == {"result": "stalled", "sound": "squeal at the top", "note": "claw clicked"}
    assert t.ask_observation(ask=lambda _p: "x")["result"] is None

    def eof(_p):
        raise EOFError
    assert t.ask_observation(ask=eof) == {"result": None, "sound": None, "note": None}


def test_a_run_writes_only_the_data_skill_and_logs_the_trace_and_the_label():
    c, r = Clock(), Robot()
    res, plan = t.run_step(r, r._lk, "lift", 8, BASE, watch_s=1.0, say=lambda *_: None, sleep=c.sleep, clock=c, wall=lambda: 5.5)
    assert len(r._lk.messages) == 1 and r._lk.messages[0][:1] == b"K"                                   # one message, nothing else written through the link (its send() would have raised)
    assert res["skill"] == "lift_s008" and res["sent_at"] == 5.5 and res["frames"] > 0
    assert res["verdict"] == "ok"                                                                       # a quiet body is not a failure here: only the arm moves
    assert len(plan) == 3


def test_next_speed_follows_the_steps_and_stops_where_it_should():
    assert t.next_speed(None) == (4, None)
    assert t.next_speed({"speed_byte": 4, "observation": {"result": "followed"}}) == (6, None)
    assert t.next_speed({"speed_byte": 12, "observation": {"result": "lagged"}}) == (16, None)
    for bad in t.STOP_RESULTS:
        nxt, why = t.next_speed({"speed_byte": 8, "observation": {"result": bad}})
        assert nxt is None and bad in why
    assert t.next_speed({"speed_byte": 8}) [0] is None                                                  # no observation recorded yet
    assert t.next_speed({"speed_byte": 127, "observation": {"result": "followed"}})[0] is None         # the top step


def test_the_report_lists_the_runs_and_the_next_step(tmp_path):
    (tmp_path / "20261120_100000_lift_s004.json").write_text(json.dumps({"speed_byte": 4, "max_roll_dev": 1.2, "max_pitch_dev": 2.0, "onset_s": 0.3, "pack_pct": 88, "time": "t1",
                                                                         "observation": {"result": "followed", "sound": None, "note": "smooth"}}))
    (tmp_path / "20261120_101000_lift_s006.json").write_text(json.dumps({"speed_byte": 6, "observation": {"result": "stalled", "sound": "squeal"}}))
    lines = t.report("lift", str(tmp_path))
    assert lines[0] == "lift series: 2 run(s)" and "followed" in lines[1] and "note: smooth" in lines[1]
    assert "stalled" in lines[2] and "sound: squeal" in lines[2]
    assert lines[-1].startswith("  next: none") and "stalled" in lines[-1]
    both = t.report(None, str(tmp_path))
    assert any(ln.startswith("jaw series: 0 run(s)") for ln in both) and both[-1] == "  next: speed 4"


def test_a_session_offers_the_next_step_and_one_step_at_a_time(tmp_path):
    ran, replies = [], iter(["", "", "12", "s"])
    logs = tmp_path

    def execute(speed):
        ran.append(speed)
        (logs / f"20261120_1{len(ran):05d}_lift_s{speed:03d}.json").write_text(json.dumps({"speed_byte": speed, "observation": {"result": "followed"}}))
        return str(logs)
    out = []
    n = t.session(None, None, "lift", {}, execute, ask=lambda _p: next(replies), say=lambda *a: out.append(" ".join(str(x) for x in a)), log_dir=str(tmp_path))
    assert ran == [4, 6] and n == 2                                                                     # Enter twice: the baseline, then the next step
    assert any("one step" in line for line in out)                                                     # 12 after 6 is refused (the next step is 8), then s stops


def test_a_session_stops_when_a_step_does_not_run_or_the_series_is_finished(tmp_path):
    assert t.session(None, None, "lift", {}, lambda s: None, ask=lambda _p: "", say=lambda *a: None, log_dir=str(tmp_path)) == 0
    (tmp_path / "20261120_100000_lift_s008.json").write_text(json.dumps({"speed_byte": 8, "observation": {"result": "hit"}}))
    out = []
    assert t.session(None, None, "lift", {}, lambda s: "x", ask=lambda _p: "", say=lambda *a: out.append(" ".join(map(str, a))), log_dir=str(tmp_path)) == 0
    assert any("hit" in line for line in out)


def test_from_attention_goes_into_the_attention_pose_before_the_legs_are_read_and_rests_after(monkeypatch, tmp_path):
    from pi_pipeline.behavior import ball_chase as chase
    from pi_pipeline.link import imu_print
    from pi_pipeline.power import battery
    order = []
    monkeypatch.setattr(battery, "motion_gate", lambda link: (True, 90, 8.2))
    monkeypatch.setattr(battery, "read_voltage", lambda link, *a, **k: 8.2)
    monkeypatch.setattr(imu_print, "board_answers", lambda link: True)
    monkeypatch.setattr(chase, "_stand_if_lying", lambda link, token="kbalance": order.append("stand") or True)
    monkeypatch.setattr(chase, "read_joints", lambda link, *a, **k: order.append("read") or list(BASE))
    monkeypatch.setattr(chase, "ensure_rest", lambda link, *a, **k: order.append("rest") or True)
    monkeypatch.setattr(t, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(t, "run_step", lambda *a, **k: (order.append("skill") or {"verdict": "ok", "max_roll_dev": 0.0, "max_pitch_dev": 0.0, "skill": "x", "variant": "x"}, [{"nominal_s": 1.0}]))

    class Rb(Robot):
        posture = "unknown"

        def sit_down(self):
            order.append("attention:" + self.posture)
            return "ok"
    t.execute_step(Link(), Rb(), "lift", 16, {"lift_lo": 0.0, "lift_hi": 120.0, "lift_hold": 120.0, "jaw_open": None, "jaw_closed": None}, prompt=False, from_attention=True, say=lambda *a: None)
    assert order == ["stand", "attention:stand", "read", "skill", "rest"]       # the legs are read in the attention pose, and rest is sent straight from it
    order.clear()
    t.execute_step(Link(), Rb(), "lift", 16, {"lift_lo": 0.0, "lift_hi": 120.0, "lift_hold": 120.0, "jaw_open": None, "jaw_closed": None}, prompt=False, say=lambda *a: None)
    assert order == ["stand", "read", "skill", "rest"]                            # without the option nothing changes


def test_speed_zero_is_an_instant_jump_that_needs_a_deliberate_flag_and_the_both_series_moves_lift_and_jaw():
    assert t.check_step(0, None) is not None and t.check_step(0, None, allow_jump=True) is None
    plan = t.build_plan("both", 0, BASE, **JAW)
    assert [p["name"] for p in plan] == ["to_start", "lift_up", "jaw_open", "jaw_close", "jaw_open_again", "jaw_back", "lower"]
    assert [p["speed"] for p in plan[1:5]] == [0, 0, 0, 0] and plan[0]["speed"] == plan[5]["speed"] == plan[6]["speed"] == t.SLOW_BYTE
    assert plan[1]["nominal_s"] == 0.3 and plan[2]["frame"][t.LIFT] == 120                          # no interpolation steps at speed 0, only the pause after the frame; the jaw moves with the arm up
