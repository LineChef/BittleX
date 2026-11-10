"""The green-ball finder and the chase loop (2026-10-25). Synthetic pictures (a grey floor and a lime disc), a fake robot and a fake camera: no hardware, no network."""
import io

import numpy as np
import pytest
from PIL import Image

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.vision import ball_finder as bf

BALL = (146, 213, 140)         # the treat ball as the camera sees it


def picture(draw=None, size=240) -> bytes:
    a = np.full((size, size, 3), (128, 128, 122), dtype=np.uint8)
    a[:size // 3] = (168, 187, 195)                                  # the wall
    for fn in (draw or []):
        fn(a)
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def disc(cx, cy, r, colour=BALL):
    def fn(a):
        yy, xx = np.mgrid[:a.shape[0], :a.shape[1]]
        a[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = colour
    return fn


def rect(x0, y0, x1, y1, colour):
    def fn(a):
        a[y0:y1, x0:x1] = colour
    return fn


# ------------------------------------------------------------------------------------------------- the finder

def test_a_dim_ball_right_at_the_claw_is_found_but_a_small_dim_patch_is_not():
    dim = (100, 118, 98)                                             # lamp light, 2026-11-01: green above red/blue by ~18, the normal pass misses it
    close = bf.find_ball(picture([disc(60, 110, 95, dim)]))          # half the picture, cut off at the left edge
    assert close is not None and close.distance_in < 4 and close.touches_edge
    assert bf.find_ball(picture([disc(120, 40, 15, dim)])) is None   # the same colour, small and above the horizon (a lamp shade): not the ball
    assert bf.find_ball(picture([disc(120, 110, 15, dim)])) is not None   # small and dim on the floor: the dim pass finds it


def test_the_ball_is_found_with_its_distance_and_direction():
    r = bf.find_ball(picture([disc(120, 110, 25)]))                  # 50 px across: about 6.6 in away, dead ahead
    assert r is not None and abs(r.x - 120) < 3 and 5.5 < r.distance_in < 8 and abs(r.bearing_deg) < 3 and not r.touches_edge
    far = bf.find_ball(picture([disc(120, 90, 5)]))                  # 10 px across: about 33 in
    assert far is not None and 25 < far.distance_in < 45
    right = bf.find_ball(picture([disc(200, 110, 16)]))              # right of centre: positive bearing
    left = bf.find_ball(picture([disc(40, 110, 16)]))
    assert right.bearing_deg > 10 and left.bearing_deg < -10


def test_nothing_green_gives_none_and_a_flat_or_ring_shape_is_not_a_ball():
    assert bf.find_ball(picture()) is None
    assert bf.find_ball(picture([rect(70, 120, 120, 132, (87, 148, 107))])) is None              # a flat green card
    assert bf.find_ball(b"not a jpeg") is None and bf.find_ball(b"") is None


def test_a_ball_cut_off_by_the_frame_is_flagged_and_a_highlight_does_not_split_it():
    cut = bf.find_ball(picture([disc(238, 110, 16)]))
    assert cut is not None and cut.touches_edge
    lit = bf.find_ball(picture([disc(120, 110, 20), disc(112, 102, 4, (250, 255, 250))]))         # a white highlight inside the ball
    assert lit is not None and lit.area > 1000


def test_the_bottom_of_the_frame_is_ignored():
    assert bf.find_ball(picture([disc(120, 232, 14)])) is None                                    # the jaws and the foot live down there


# ------------------------------------------------------------------------------------------------- the planner

def reading(dist, bearing):
    return bf.BallReading(120.0, 110.0, 500, 30, 30, 30.0, dist, bearing, False)


def test_planner_turns_then_walks_then_punts():
    p = bc.ChasePlanner()
    a = p.decide(reading(30, 25)); assert a.kind == "turn" and a.degrees > 0
    a = p.decide(reading(30, -20)); assert a.kind == "turn" and a.degrees < 0
    a = p.decide(reading(30, 3)); assert a.kind == "walk" and bc.MIN_MOVE_S <= a.seconds <= bc.WALK_MAX_S
    a = p.decide(reading(3, 3)); assert a.kind == "punt"
    a = p.decide(reading(3, 16)); assert a.kind == "align"                                         # near and off line: a small turn to line up before the punt
    a = p.decide(reading(1.5, 0)); assert a.kind == "punt"                                           # too close to punt


def test_planner_backs_up_when_punts_do_not_move_the_ball():
    p = bc.ChasePlanner()
    kinds = [p.decide(reading(3, 0)).kind for _ in range(bc.STUCK_PUNTS + 1)]
    assert kinds == ["punt"] * bc.STUCK_PUNTS + ["back"]


def test_planner_searches_toward_the_side_it_last_saw_and_never_gives_up():
    p = bc.ChasePlanner(claw_ok=False)                                                             # no claw look (a robot that cannot move the arm): turn steps only
    p.decide(reading(20, -30))                                                                     # last seen on the left
    assert p.decide(None).kind == "look" and p.decide(None).kind == "look"                         # two more looks first (three real misses before a search)
    a = p.decide(None); assert a.kind == "search_turn" and a.degrees < 0
    kinds = [p.decide(None).kind for _ in range(bc.SEARCH_STEPS_PER_CIRCLE + 2)]
    assert "search_walk" not in kinds and set(kinds) == {"search_turn"}                              # no blind walking by default (a desk): it keeps turning in place, never gives up
    bc.SEARCH_WALK = True
    try:
        q = bc.ChasePlanner(claw_ok=False); q.decide(reading(20, -30))
        kinds = [q.decide(None).kind for _ in range(bc.SEARCH_STEPS_PER_CIRCLE + 3)]
        assert "search_walk" in kinds                                                                # on a big floor (--search-walk): a full circle, a short walk, and on
    finally:
        bc.SEARCH_WALK = False


# ------------------------------------------------------------------------------------------------- the loop

class FakeRobot:
    def __init__(self, fall_at=None):
        self.moves, self.fall_at = [], fall_at
    def _do(self, what):
        self.moves.append(what)
        return "fell" if self.fall_at is not None and len(self.moves) >= self.fall_at else "ok"
    def walk(self, s): return self._do(("walk", round(s, 1)))
    def turn(self, d, s, stop_deg=0.0): return self._do(("turn", round(d)))
    def back(self, s): return self._do(("back", round(s, 1)))
    def punt(self): return self._do(("punt",))
    def battery_ok(self): return True


class ScriptedRobot(FakeRobot):
    def walk_scripted(self, s): return self._do(("scripted", round(s, 1)))


class FakeCamera:
    def __init__(self, frames):
        self.frames, self.i = frames, 0
    def look(self):
        f = self.frames[min(self.i, len(self.frames) - 1)]
        self.i += 1
        return f


def test_the_loop_turns_walks_and_punts_on_a_series_of_pictures():
    frames = [picture([disc(200, 110, 14)]), picture([disc(124, 110, 12)]), picture([disc(122, 110, 50)])]      # right of centre, ahead and farther, then close
    robot = FakeRobot()
    out = bc.run_chase(robot, FakeCamera(frames), lambda: False, max_steps=3, sleep=lambda s: None, say=lambda m: None)
    assert out == "steps" and [m[0] for m in robot.moves] == ["turn", "walk", "punt"] and robot.moves[0][1] > 0


def test_the_loop_stops_on_the_flag_on_a_fall_and_in_dry_run_sends_nothing():
    cam = FakeCamera([picture([disc(122, 110, 50)])])
    robot = FakeRobot()
    assert bc.run_chase(robot, cam, lambda: True, sleep=lambda s: None, say=lambda m: None) == "stopped" and not robot.moves
    robot = FakeRobot(fall_at=1)
    assert bc.run_chase(robot, FakeCamera([picture([disc(122, 110, 50)])]), lambda: False, sleep=lambda s: None, say=lambda m: None) == "fell"
    robot = FakeRobot()
    bc.run_chase(robot, FakeCamera([picture([disc(122, 110, 50)])]), lambda: False, dry_run=True, max_steps=4, sleep=lambda s: None, say=lambda m: None)
    assert not robot.moves


def test_pictures_with_the_ball_are_saved_with_a_box_at_most_every_two_seconds(tmp_path):
    t = [0.0]
    saver = bc.PictureSaver(str(tmp_path), clock=lambda: t[0])
    jpeg = picture([disc(120, 110, 25)])
    ball = bf.find_ball(jpeg)
    saver.maybe_save(jpeg, ball); t[0] = 1.0; saver.maybe_save(jpeg, ball); t[0] = 2.5; saver.maybe_save(jpeg, ball); saver.maybe_save(jpeg, None)
    assert saver.saved == 2 and len(list(tmp_path.glob("*.jpg"))) >= 1 and list(tmp_path.glob("*.json"))
    import json
    box = json.loads(next(tmp_path.glob("*.json")).read_text())["box_xywh"]
    assert abs(box[0] + box[2] / 2 - 120) < 3 and box[2] > 40
    side = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert side["name"] == "greenball" and side["kind"] == "name:greenball" and side["file"].endswith(".jpg") and side["exposure"]["mean"]       # what the g2pics review page reads


def test_the_serial_robot_sends_the_firmware_skills_and_ends_in_a_balanced_stand():
    class FakeLink:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    lk = FakeLink()
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 100, 0.2)).__next__, use_pick=True)
    assert r.turn(20, 0.3) == "ok" and r.turn(-20, 0.3) == "ok" and r.back(0.3) == "ok" and r.punt() == "ok"
    toks = [c for c in lk.sent if c.startswith("k")]
    assert toks == ["kwkR", "kbalance", "kwkL", "kbalance", "kbkF", "kbalance", "kpickF", "kbalance", "kpickF", "kbalance"]      # (this fake link reports no IMU swing, so the punt is sent twice)


def test_a_fall_during_a_firmware_move_still_stops_the_move():
    class FakeLink:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    lk = FakeLink()
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 100, 0.2)).__next__)
    r._fell = lambda: True                                                                           # the fall guard fires at once
    assert r.back(1.0) == "fell"
    assert [c for c in lk.sent if c.startswith("k")] == ["kbkF", "krest"]                           # 2026-11-02: no stop was sent and kbkF ran for over a minute; 2026-11-08: the stop after a fall is the rest position, never a stand


def test_walks_are_always_the_default_gait_policy(monkeypatch):
    from pi_pipeline.gait import policy_walker
    monkeypatch.setenv("G2_DEFAULT_GAIT", "policy")          # (the default is Petoi's scripted arm gait since 2026-11-08; G2_DEFAULT_GAIT=policy brings the learned walk back)
    made = []

    class FakeWalker:
        def __init__(self, link, **kw):
            made.append(kw); self._on_fall = kw.get("on_fall"); self.n = 0; self.walked = []
        @property
        def busy(self):
            self.n += 1
            return self.n < 3
        def walk(self, seconds): self.walked.append(seconds); self.n = 0
        def stop(self, rest=True): pass
    monkeypatch.setattr(policy_walker, "PolicyWalker", FakeWalker)

    class FakeLink:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    lk = FakeLink()
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 100, 0.2)).__next__)
    assert r.walk(1.5) == "ok" and r.walk(2.0) == "ok"
    assert len(made) == 1 and made[0]["hold_between_legs"] is True and r._walker.walked == [1.5, 2.0]     # one walker, ending each walk in a balanced stand
    assert not any(c == "kwkF" for c in lk.sent)                                                          # never Petoi's walk


def test_the_battery_gate_is_strict_on_request_and_lets_an_unreadable_pack_through_in_testing(monkeypatch):
    from pi_pipeline.power import battery

    class Link:
        def __init__(self, reply): self.reply = reply
        def drain(self, s): pass
        def send(self, c, **k): return self.reply
    assert battery.motion_gate(Link("Voltage: 8.20 V")) == (True, 88, 8.2)
    ok, pct, v = battery.motion_gate(Link("Voltage: 7.30 V")); assert ok is False and pct < 30 and v == 7.3         # a reading that works and is low always stops
    waits = []
    monkeypatch.delenv("G2_BATTERY_STRICT", raising=False)
    assert battery.motion_gate(Link("G"), sleep=waits.append) == (True, None, None)                               # testing (user, 2026-11-01): unreadable does not block
    assert waits == [battery.MOTION_GATE_WAIT_S] * (battery.MOTION_GATE_ROUNDS - 1)                                # ... after the retries
    monkeypatch.setenv("G2_BATTERY_STRICT", "1")
    assert battery.motion_gate(Link("G"), sleep=lambda s: None) == (False, None, None)                            # strict: fail safe

    class Late(Link):                                                                                                 # the first reads come back empty (the port just let go: 2026-10-31)
        def __init__(self): self.n = 0
        def send(self, c, **k):
            self.n += 1
            return "" if self.n <= 4 else "Voltage: 8.50 V"
    assert battery.motion_gate(Late(), sleep=lambda s: None) == (True, 100, 8.5)
    battery.MOTION_GATE_WAIT_S, keep = 0.0, battery.MOTION_GATE_WAIT_S
    try:
        assert bc.SerialRobot(Link("Voltage: 8.20 V")).battery_ok() is True and bc.SerialRobot(Link("junk")).battery_ok() is False       # strict still set
        monkeypatch.delenv("G2_BATTERY_STRICT")
        assert bc.SerialRobot(Link("junk")).battery_ok() is True
    finally:
        battery.MOTION_GATE_WAIT_S = keep


def test_one_attempt_ends_after_the_first_punt():
    frames = [picture([disc(122, 110, 50)])]                                                      # the ball right in front of the claw, every look
    robot = FakeRobot()
    out = bc.run_chase(robot, FakeCamera(frames), lambda: False, max_punts=1, max_steps=10, sleep=lambda s: None, say=lambda m: None)
    assert out == "punted" and [m[0] for m in robot.moves] == ["punt"]
    robot = FakeRobot(fall_at=1)
    assert bc.run_chase(robot, FakeCamera(frames), lambda: False, max_punts=1, max_steps=10, sleep=lambda s: None, say=lambda m: None) == "fell"      # a fall is not a punt


def test_a_missing_picture_is_not_a_miss_and_the_voice_cues_say_what_he_sees():
    ball = picture([disc(122, 110, 50)])
    empty = picture()

    class Cam:
        def __init__(self, seq):
            self.seq, self.i = seq, 0
        def look(self):
            f = self.seq[min(self.i, len(self.seq) - 1)]
            self.i += 1
            return f
    said, spoken = [], []
    robot = FakeRobot()
    # no picture, no picture (ignored), then three empty looks (a search starts: "searching"), then the ball (target acquired), then a punt ends the attempt
    bc.run_chase(robot, Cam([None, None, empty, empty, empty, ball]), lambda: False, max_punts=1, max_steps=12, announce=spoken.append, sleep=lambda s: None, say=said.append)
    assert spoken == ["searching", "target acquired", "punting"], spoken
    assert [m[0] for m in robot.moves][:1] == ["turn"] or "punt" in [m[0] for m in robot.moves]
    assert not any("search" in m for m in said[:2])                                                 # the two missing pictures did not start a search
    first = []
    bc.run_chase(FakeRobot(), Cam([ball]), lambda: False, max_punts=1, max_steps=3, announce=first.append, sleep=lambda s: None, say=lambda m: None)
    assert first[:1] == ["target acquired"]                                                          # seen at the very start: said once


def test_he_steps_closer_after_a_punt_that_left_the_ball_far_and_rests_never_backs_up_for_closeness():
    p = bc.ChasePlanner()
    assert p.decide(reading(3.5, 2)).kind == "punt"                                                  # in reach: punt
    assert p.decide(reading(3.5, 2)).kind == "punt"                                                  # (the ball has not moved)
    assert bc.ChasePlanner().decide(reading(5.5, 2)).kind == "walk"                                  # just out of reach: a small step closer first
    q = bc.ChasePlanner()
    kinds = [q.decide(reading(5.5, 2)).kind for _ in range(bc.NUDGES_BEFORE_PUNT + 1)]
    assert kinds == ["walk"] * bc.NUDGES_BEFORE_PUNT + ["punt"]                                       # three nudges that did not help, then punt anyway
    assert bc.ChasePlanner().decide(reading(1.0, 0)).kind == "punt"                                   # right in front of the ball: punt, never back up


def test_a_punt_that_barely_moved_him_is_sent_again_once():
    class Link:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    lk = Link()
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 100, 0.2)).__next__, use_pick=True)
    assert r.punt() == "ok" and [c for c in lk.sent if c == "kpickF"] == ["kpickF", "kpickF"]       # no IMU swing: the lunge did not play, so it is sent again, and only once


def test_a_ball_that_vanishes_at_close_range_is_punted_not_searched_for_and_he_says_punting():
    p = bc.ChasePlanner()
    p.decide(reading(4, 1))                                                                         # seen 4 in away ...
    a = p.decide(None); assert a.kind == "punt"                                                    # ... and gone: it is at the claw
    assert p.decide(None).kind == "look"                                                           # a second miss is a real miss
    far = bc.ChasePlanner(); far.decide(reading(30, 1)); assert far.decide(None).kind == "look"      # lost at 30 in: look again, then search
    spoken = []
    frames = [picture([disc(122, 110, 40)])]
    bc.run_chase(FakeRobot(), FakeCamera(frames), lambda: False, max_punts=1, max_steps=5, announce=spoken.append, sleep=lambda s: None, say=lambda m: None)
    assert spoken == ["target acquired", "punting"], spoken


def test_the_attempt_summary_says_where_the_punt_was_made():
    said = []
    bc.run_chase(FakeRobot(), FakeCamera([picture([disc(122, 110, 50)])]), lambda: False, max_punts=1, max_steps=5, sleep=lambda s: None, say=said.append)
    line = next(m for m in said if m.startswith("ATTEMPT:"))
    assert "punted at (" in line and "after 1 looks" in line


def test_the_punch_keeps_the_claw_shut_sends_no_pick_skill_and_ends_on_the_balance_pose(monkeypatch):
    """User, 2026-10-25: test the punch, not a pick with the claw. The punch is the lunge of pickF with the claw held closed, as `i` commands, ending on the balance pose."""
    from pi_pipeline.link import transitions as T
    monkeypatch.setenv("G2_ATTACHMENT", "arm")

    class Link:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    lk = Link()
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 100, 0.2)).__next__)
    r._fell = lambda: False
    assert r.punch() == "ok"
    moves = [c for c in lk.sent if c.startswith("i1 ")]
    assert moves and all(" 2 0 " in c for c in moves)                                         # the claw (joint 2) is at 0 in every command: it never opens
    assert not any(c.startswith("kpick") for c in lk.sent) and "kbalance" not in lk.sent          # no pick skill, no firmware stand-up
    lifts = [int(c.split()[1]) for c in moves]
    assert max(lifts) == 75 and lifts[-1] == 0                                                  # the arm swings out to 75 and comes back
    bal = [round(x) for x in T.balance_pose()]
    assert moves[-1] == r._pose_cmd(0, bal[:4], bal[4:])                                       # it ends on the balance pose
    lung = next(c for c in moves if c.startswith("i1 75 "))
    assert " 8 -57 " in lung or " 8 43 " in lung                                               # the front shoulders carry the arm build's -10 shift (53 - 10)


def test_an_attempt_ends_when_its_time_is_up():
    t = [0.0]
    def clock():
        t[0] += 10.0
        return t[0]
    out = bc.run_chase(FakeRobot(), FakeCamera([picture()]), lambda: False, max_seconds=35, clock=clock, sleep=lambda s: None, say=lambda m: None)
    assert out == "time"


def test_the_punt_test_asks_for_each_distance_punches_once_and_writes_a_csv(tmp_path):
    from pi_pipeline.behavior import punt_test as pt

    class Robot:
        def __init__(self): self.punts = 0
        def punt(self): self.punts += 1; return "ok"
        def swing_deg(self): return 15.0
    answers = iter(["", "", "18", "y", "", "", "s", "", "", "10", "n", "hit the leg"])        # d1: ready, punch, 18 in, hit, no note | d2: ready, skip | d3: ready, punch, 10 in, no, a note
    prompts = []
    def ask(p):
        prompts.append(p)
        return next(answers)
    cam = FakeCamera([picture([disc(122, 110, 40)])])
    robot = Robot()
    csv_path = str(tmp_path / "punts.csv")
    rows = pt.run_tests(robot, cam, [2.0, 3.0, 4.0], ask=ask, say=lambda m: None, csv_path=csv_path, sleep=lambda s: None)
    assert robot.punts == 2 and [r["asked_in"] for r in rows] == [2.0, 4.0]                            # the skipped distance is not punched
    assert rows[0]["ball_went_in"] == "18" and rows[0]["claw_hit_first"] == "y" and rows[1]["note"] == "hit the leg"
    text = open(csv_path).read().splitlines()
    assert text[0].startswith("time,asked_in,read_in") and len(text) == 3
    assert any("2 in ahead" in p for p in prompts) and any("4 in ahead" in p for p in prompts)


def test_the_punt_settings_file_changes_the_constants_and_bad_values_are_reported(tmp_path, monkeypatch):
    import json
    import sys

    from pi_pipeline.behavior import punt_settings as ps
    me = sys.modules[bc.__name__]
    keep = (bc.PUNT_MAX_IN, bc.NUDGE_MAX_IN, bc.NUDGES_BEFORE_PUNT, bc.PUNCH_LUNGE_S, bc.SEARCH_WALK)
    try:
        p = tmp_path / "punt_settings.json"
        p.write_text(json.dumps({"_help": "x", "punt_max_in": 3.2, "nudges_before_punt": 1, "punch_lunge_s": 0.2, "search_walk": True, "max_seconds": 40, "punt_align_deg": 99, "nope": 1, "nudge_max_in": "far"}))
        eff, problems = ps.effective(me, str(p))
        assert eff["punt_max_in"] == 3.2 and bc.PUNT_MAX_IN == 3.2 and bc.NUDGES_BEFORE_PUNT == 1 and bc.PUNCH_LUNGE_S == 0.2 and bc.SEARCH_WALK is True and eff["max_seconds"] == 40.0
        assert bc.punch_keys()[2][0] == 0.2                                                    # the punch uses the new lunge time
        assert len(problems) == 3 and any("punt_align_deg" in x for x in problems) and any("nope" in x for x in problems) and any("nudge_max_in" in x for x in problems)
        assert bc.PUNT_ALIGN_DEG == 12.0                                                         # a value out of range is not used
        assert ps.effective(me, str(tmp_path / "missing.json"))[1] == []                         # no file: no problem, all defaults
    finally:
        bc.PUNT_MAX_IN, bc.NUDGE_MAX_IN, bc.NUDGES_BEFORE_PUNT, bc.PUNCH_LUNGE_S, bc.SEARCH_WALK = keep
    monkeypatch.setenv("G2_PUNT_SETTINGS", str(tmp_path / "x.json"))
    assert ps.path() == str(tmp_path / "x.json")
    t = json.loads(ps.template(me))
    assert set(ps.SPEC) <= set(t) and t["punt_max_in"] == bc.PUNT_MAX_IN


def test_set_value_checks_then_writes_one_setting(tmp_path):
    import json
    import sys

    from pi_pipeline.behavior import punt_settings as ps
    me = sys.modules[bc.__name__]
    p = str(tmp_path / "s.json")
    assert ps.set_value(me, "punt_max_in", "3.5", p).startswith("punt_max_in: ") and json.load(open(p))["punt_max_in"] == 3.5       # created from the defaults
    assert json.load(open(p))["nudges_before_punt"] == bc.NUDGES_BEFORE_PUNT                                                       # the other values are there
    assert ps.set_value(me, "nudges_before_punt", "2", p) and json.load(open(p))["nudges_before_punt"] == 2
    assert ps.set_value(me, "search_walk", "true", p) and json.load(open(p))["search_walk"] is True
    for name, text in (("nope", "1"), ("punt_max_in", "99"), ("punt_max_in", "far"), ("search_walk", "maybe")):
        try:
            ps.set_value(me, name, text, p)
        except ValueError:
            continue
        raise AssertionError((name, text))
    assert json.load(open(p))["punt_max_in"] == 3.5                                                                                # a rejected value changes nothing


def test_a_search_turn_is_short_then_he_looks_again():
    p = bc.ChasePlanner()
    p.claw_ok = False
    acts = [p.decide(None) for _ in range(bc.LOST_LOOKS + 2)]
    turns = [a for a in acts if a.kind == "search_turn"]
    assert turns and all(a.seconds <= bc.SEARCH_MOVE_MAX_S + 1e-9 for a in turns)


def test_no_wall_turn_with_the_ball_in_reach():
    p = bc.ChasePlanner()
    ball = bf.find_ball(picture([disc(120, 110, 70)]))               # about 2.4 in, straight ahead
    assert ball is not None and ball.distance_in <= bc.PUNT_MAX_IN
    assert p.decide(ball, bc.WallSeen(6.0, "left")).kind == "punt"


def test_every_turn_is_logged_with_its_cause(tmp_path, monkeypatch):
    import json
    monkeypatch.setenv("G2_TURN_LOG", str(tmp_path / "t.jsonl"))
    bc.log_turn(bc.Action("wall_turn", 2.0, -45.0, "a wall 8 in ahead: turn away"), None, bc.WallSeen(8.0, "left"), "ok")
    row = json.loads((tmp_path / "t.jsonl").read_text().splitlines()[0])
    assert row["cause"] == "a wall ahead" and row["direction"] == "left" and row["wall_in"] == 8.0 and row["ball"] is None


def test_he_waits_in_the_attention_pose_and_stands_up_right_before_each_move(monkeypatch):
    monkeypatch.setattr(bc, "BETWEEN_MOVES", "attention")                         # the attention flow (the switch; the default is stand)
    class FakeLink:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    lk = FakeLink()
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 1000, 0.2)).__next__)
    assert r.relax() == "ok" and r.relax() == "ok" and r.posture == "attention"        # the second does nothing
    assert r.turn(20, 0.3) == "ok" and r.posture == "stand"
    assert r.stand_up() == "ok"                                                         # standing already: nothing sent
    r.relax()
    assert r.back(0.3) == "ok"
    toks = [c for c in lk.sent if c.startswith("k")]
    assert toks == [bc.CLAW_LOOK_POSE, "kbalance", "kwkR", "kbalance", bc.CLAW_LOOK_POSE, "kbalance", "kbkF", "kbalance"]


def test_the_claw_look_from_the_attention_pose_needs_no_stand_up_and_stays_down_afterwards(monkeypatch):
    monkeypatch.setattr(bc, "BETWEEN_MOVES", "attention")                         # the attention flow (the switch; the default is stand)
    class FakeLink:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    lk = FakeLink()
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 1000, 0.2)).__next__)
    r.relax()
    assert r.sit_down() == "ok" and r.stand_from_sit() == "ok" and r.posture == "attention"
    assert [c for c in lk.sent if c.startswith("k")] == [bc.CLAW_LOOK_POSE, bc.CLAW_LOOK_POSE]   # the pose again (it drives the legs again), no kbalance either side


def test_the_loop_takes_each_picture_in_the_attention_pose_and_goes_back_to_it_after_each_move(monkeypatch):
    monkeypatch.setattr(bc, "BETWEEN_MOVES", "attention")                         # the attention flow (the switch; the default is stand)
    class PoseRobot(FakeRobot):
        def relax(self): self.moves.append("attention"); return "ok"
        def stand_up(self): self.moves.append("stand"); return "ok"
    frames = [picture([disc(200, 110, 20)]), picture([disc(122, 110, 20)]), picture([disc(122, 110, 50)])]
    robot = PoseRobot()
    bc.run_chase(robot, FakeCamera(frames), lambda: False, max_punts=1, max_steps=6, sleep=lambda s: None, say=lambda m: None)
    kinds = [m if isinstance(m, str) else m[0] for m in robot.moves]
    assert kinds[0] == "attention" and kinds[-1] == "attention"                        # the first picture is taken in the attention pose; down again when the attempt is over
    assert "stand" not in kinds                                                         # the loop never stands him up for a picture: the robot's own moves do it (SerialRobot)
    for i, k in enumerate(kinds):
        if k in ("walk", "turn", "back"):
            assert kinds[i + 1] == "attention"                                          # every move: attention pose right after, and the next picture from there


def test_close_to_the_ball_he_stays_standing_between_the_small_steps(monkeypatch):
    monkeypatch.setattr(bc, "BETWEEN_MOVES", "attention")                         # the attention flow (the switch; the default is stand)
    class PoseRobot(FakeRobot):
        def relax(self): self.moves.append("attention"); return "ok"
        def stand_up(self): self.moves.append("stand"); return "ok"
    import types
    near_off = picture([disc(165, 110, 33)])                 # about 5 in away, off to one side: a line-up turn
    robot = PoseRobot()
    bc.run_chase(robot, FakeCamera([near_off, picture([disc(122, 110, 60)])]), lambda: False, max_punts=1, max_steps=4, sleep=lambda s: None, say=lambda m: None)
    kinds = [m if isinstance(m, str) else m[0] for m in robot.moves]
    i = kinds.index("turn")
    assert kinds[i + 1] != "attention"                                                  # no attention pose after the line-up turn: the next picture is taken standing
    assert kinds[-1] == "attention"                                                     # but the attempt still ends in it
    assert bc._dialing_in(None) is False and bc._dialing_in(types.SimpleNamespace(distance_in=bc.NUDGE_MAX_IN + 5)) is False


def test_a_fall_records_which_way_he_went(monkeypatch):
    import math
    from pi_pipeline.gait import imu_parse
    monkeypatch.setattr(imu_parse, "parse_imu_line", lambda line: (math.radians(-5.0), math.radians(-60.0)))
    class FakeLink:
        def send(self, c, read_reply=False, settle=0.0): return ""
        def poll_imu(self): return ["x"]
    r = bc.SerialRobot(FakeLink(), sleep=lambda s: None)
    r.posture = "attention"
    assert r._fell() is True
    assert r.last_fall == {"pitch": -60.0, "roll": -5.0, "way": "nose up", "posture": "attention"}


class _PoseLink:
    """Answers `j` with a fixed 16-joint pose (an index header row first, as the firmware may print one)."""
    def __init__(self, pose_name):
        legs = bc._known_poses()[pose_name]
        self.joints = [0] * 8 + [int(round(legs[sv])) for sv in range(8, 16)]
        self.sent, self._other, self.last_motion_command = [], [], ""
    def send(self, c, read_reply=False, settle=0.0):
        self.sent.append(c)
        if c == "j":
            self._other += [",".join(str(i) for i in range(16)), ",\t".join(str(v) for v in self.joints)]
        return ""
    def poll_imu(self): return []
    def pop_other(self):
        out, self._other = self._other, []
        return out


def test_the_pose_read_names_each_known_pose_and_nothing_else():
    for name in ("stand", "attention", "rest", "sit"):
        assert bc.classify_pose(bc.read_joints(_PoseLink(name), sleep=lambda s: None)) == name
    assert bc.classify_pose([0] * 8 + [90] * 8) == "unknown" and bc.classify_pose(None) == "unknown"


@pytest.mark.parametrize("pose, link_belief, sends_stand", [("attention", "kcalib", True), ("rest", "krest", True), ("sit", "ksit", True), ("stand", "", False)])
def test_before_a_move_he_reads_his_pose_and_stands_up_the_way_that_pose_needs(pose, link_belief, sends_stand, monkeypatch):
    monkeypatch.setattr(bc, "BETWEEN_MOVES", "attention")                         # the pose read and tilt check belong to the attention flow
    lk = _PoseLink(pose)
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 1000, 0.2)).__next__)
    assert r.stand_up() == "ok" and r.posture == "stand"
    assert ("kbalance" in lk.sent) is sends_stand and "j" in lk.sent
    assert lk.last_motion_command == link_belief                          # the link runs the stand-up that pose needs: back legs first from attention, the slow one from a sit, the firmware one from rest


def test_an_attention_pose_the_board_ignores_is_asked_for_again_then_taken_as_standing():
    lk = _PoseLink("stand")                                                           # the board keeps reading the stand whatever is sent
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 10000, 0.2)).__next__)
    r.posture = "stand"
    r.relax()
    assert lk.sent.count(bc.CLAW_LOOK_POSE) == bc.ATTENTION_TRIES
    assert r.posture == "stand" and lk.last_motion_command == "kbalance"              # nothing after this believes he is in the attention pose


def test_standing_but_tilted_means_sagged_legs_and_they_are_driven_back_before_the_move(monkeypatch):
    monkeypatch.setattr(bc, "BETWEEN_MOVES", "attention")                         # the pose read and tilt check belong to the attention flow
    import math
    from pi_pipeline.gait import imu_parse, standup
    tilt = {"pitch": -33.0}
    monkeypatch.setattr(imu_parse, "parse_imu_line", lambda line: (0.0, math.radians(tilt["pitch"])))

    class Link(_PoseLink):
        def poll_imu(self): return ["imu"]
        def send(self, c, read_reply=False, settle=0.0):
            if c.startswith("i8"):
                tilt["pitch"] = -2.0                                                  # the stand angles sent again: the legs hold again
            return super().send(c, read_reply, settle)
    lk = Link("stand")
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=iter(np.arange(0, 10000, 0.2)).__next__)
    r._stand_tilt = (-1.0, 0.0)
    assert r.stand_up() == "ok"
    assert lk.sent.count(standup.move_cmd(standup.balance_pose())) == 2 and bc.CLAW_LOOK_POSE not in lk.sent
    tilt["pitch"] = -3.0
    lk.sent.clear()
    assert r.stand_up() == "ok" and not any(c.startswith("i8") for c in lk.sent)       # level enough: no re-drive


def test_the_default_flow_stands_between_moves_and_logs_the_still_time_before_each_move():
    class PoseRobot(FakeRobot):
        def relax(self): self.moves.append("attention"); return "ok"
        def stand_up(self): self.moves.append("stand"); return "ok"
    assert bc.BETWEEN_MOVES == "stand"
    frames = [picture([disc(200, 110, 20)]), picture([disc(122, 110, 20)]), picture([disc(122, 110, 50)])]
    robot, trace = PoseRobot(), []
    bc.run_chase(robot, FakeCamera(frames), lambda: False, max_punts=1, max_steps=6, sleep=lambda s: None, say=lambda m: None, trace=trace)
    assert "attention" not in robot.moves                                               # no attention pose anywhere in the default flow
    stills = [e for e in trace if e.get("kind") == "still"]
    assert [e["before"] for e in stills] == ["turn", "walk", "punt"] and all(e["seconds"] >= 0 for e in stills)


def test_a_quick_follow_on_move_skips_the_pose_read(monkeypatch):
    monkeypatch.setattr(bc, "BETWEEN_MOVES", "attention")                         # the pose read and tilt check belong to the attention flow
    lk = _PoseLink("stand")
    t = iter(np.arange(0, 1000, 0.2))
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=t.__next__)
    r.posture, r._moved_at = "stand", r._clock()
    assert r.stand_up() == "ok" and "j" not in lk.sent                                  # just moved: he goes at once
    r._moved_at = r._clock() - 10.0
    assert r.stand_up() == "ok" and "j" in lk.sent                                      # still a while: the pose is read first


def test_a_walk_that_cannot_start_because_the_board_sends_nothing_ends_the_attempt():
    class SilentBoard(FakeRobot):
        def walk(self, s): self.moves.append(("walk", s)); return "board_silent"
    said = []
    robot = SilentBoard()
    out = bc.run_chase(robot, FakeCamera([picture([disc(122, 110, 20)])]), lambda: False, max_steps=10, sleep=lambda s: None, say=said.append)
    assert out == "board_silent" and len([m for m in robot.moves if m[0] == "walk"]) == 1      # once, not rest-picture-stand over and over (2026-11-02)
    assert any("power-cycle" in m for m in said)


def test_the_standing_flow_sends_nothing_extra_before_a_move_or_at_session_start(monkeypatch):
    """2026-11-02: the pose read, the tilt check and the stand-up polling put extra serial traffic in front of every walk, and the walks after them showed no board echoes. In the
    default flow a move sends exactly what it sent before: no `j`, no `gp` / `gP` pair, nothing."""
    assert bc.BETWEEN_MOVES == "stand"
    lk = _PoseLink("stand")
    t = iter(np.arange(0, 100000, 0.2))
    r = bc.SerialRobot(lk, sleep=lambda s: None, clock=t.__next__)
    r._moved_at = r._clock() - 60.0                                                    # long still: the attention flow would read the pose and the tilt now
    assert r.stand_up() == "ok" and lk.sent == ["gP", "gp"]                           # (user, 2026-11-05) standing 5 s or more: only the tilt read for the sag check, no pose read
    for move in (lambda: r.turn(20, 0.3), lambda: r.back(0.3)):
        lk.sent.clear()
        assert move() == "ok"
        assert lk.sent[0] == "gP" and "j" not in lk.sent and lk.sent.count("gP") == 1 and lk.sent.count("gp") == 1       # the skill wrapper's own gP ... gp, as before


def test_the_session_start_reads_the_pose_once_and_waits_a_fixed_time(monkeypatch):
    import types
    waits = []
    monkeypatch.setattr(bc.time, "sleep", lambda s: waits.append(s))
    writes, sent = [], []
    row = ",\t".join(str(v) for v in [0] * 8 + [67, 67, 77, 77, -47, -47, -53, -53]).encode()          # the rest pose
    ser = types.SimpleNamespace(in_waiting=len(row), reset_input_buffer=lambda: None, write=lambda b: writes.append(b), read=lambda n: row)
    lk = types.SimpleNamespace(_ser=ser, send=lambda c, **k: sent.append(c), last_motion_command="")
    assert bc._stand_if_lying(lk) is True
    assert writes == [b"j\n"] and sent == ["kbalance"] and lk.last_motion_command == "krest" and waits == [1.0, 3.0]      # one `j`, one stand-up, a fixed 3 s: no polling loop
    sent.clear(); writes.clear(); waits.clear()
    row2 = ",\t".join(str(v) for v in [0] * 16).encode()                                                   # the attention pose: the link must run its back-legs-first stand-up
    ser.read = lambda n: row2
    assert bc._stand_if_lying(lk) is True and sent == ["kbalance"] and lk.last_motion_command == "kcalib"


def test_the_light_is_metered_in_the_background_before_a_move_and_the_pack_is_not_read_twice():
    """2026-11-02: metering the light and a second pack read happened while he stood waiting for the first picture (the legs let go after 7 to 10 s standing)."""
    import threading
    metered, batteries = [], []

    class Cam(FakeCamera):
        def premeter(self, force=False): metered.append(threading.current_thread().name == "MainThread")

    class Bot(FakeRobot):
        def battery_ok(self): batteries.append(1); return True
    frames = [picture([disc(200, 110, 20)]), picture([disc(122, 110, 20)]), picture([disc(122, 110, 50)])]
    bc.run_chase(Bot(), Cam(frames), lambda: False, max_punts=1, max_steps=6, sleep=lambda s: None, say=lambda m: None, battery_checked=True)
    assert len(metered) >= 2 and not batteries                                          # before each move; and no pack read at step 1 when the goal has just read it
    batteries.clear()
    bc.run_chase(Bot(), Cam(frames), lambda: False, max_punts=1, max_steps=3, sleep=lambda s: None, say=lambda m: None)
    assert batteries == [1]                                                             # a lone chase still reads it at step 1


def test_the_snapshot_camera_premeters_in_a_thread_one_at_a_time():
    import threading
    started, gate = [], threading.Event()

    class Inner:
        def premeter(self, force=False): started.append(force); gate.wait(2.0)
    cam = bc._SnapshotCamera(Inner())
    cam.premeter(); cam.premeter(force=True)                                           # the second is ignored while the first runs
    gate.set(); cam._pre_thread.join(2.0)
    assert started == [False]


def test_premetering_skips_a_recent_measurement_and_forces_a_stale_one():
    from pi_pipeline.vision.snapshot import CameraSnapshotter
    cam = object.__new__(CameraSnapshotter)
    import threading
    cam._lock, cam._exposure_check, cam._meter_every_s, cam._metered_at, cam._clock = threading.Lock(), True, 30.0, 100.0, lambda: 105.0
    calls = []
    cam._open, cam._meter = lambda: None, lambda: calls.append(1)
    assert cam.premeter() is False and calls == []                                      # metered 5 s ago: fine
    cam._clock = lambda: 125.0
    assert cam.premeter() is True and calls == [1]                                      # over half an interval old
    cam._clock = lambda: 101.0
    assert cam.premeter(force=True) is True and calls == [1, 1]


def test_every_decision_is_logged_with_its_reason_and_what_was_passed_over(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(bc, "SEARCH_ORDER", "full_circle")
    monkeypatch.setattr(bc, "BACK_BUDGET_S", 0.0)                         # no back-up left: the circle's back-up is passed over
    p = bc.ChasePlanner()
    p.claw_ok = False
    for _ in range(40):
        p.considered = []
        act = p.decide(None)
        bc.log_decision(1, act, None, None, p, 3.0)
    rows = [json.loads(ln) for ln in (tmp_path / "decision_log.jsonl").read_text().splitlines()]
    assert len(rows) == 40 and all(r["why"] and "state" in r for r in rows)
    assert rows[-1]["state"]["search_order"] == "full_circle" and p.circles >= 1 and any(r["passed_over"] for r in rows)


def test_the_sim_never_writes_the_real_logs(tmp_path, monkeypatch):
    import os
    from tools.sim_train import world
    monkeypatch.setenv("G2_TURN_LOG", "keep.jsonl")
    with world.patched():
        assert os.environ["G2_TURN_LOG"] == os.devnull and os.environ["G2_DECISION_LOG"] == os.devnull
    assert os.environ["G2_TURN_LOG"] == "keep.jsonl"


def test_the_chase_logs_stop_growing_at_the_size_cap(tmp_path, monkeypatch):
    f = tmp_path / "d.jsonl"
    monkeypatch.setenv("G2_DECISION_LOG", str(f))
    monkeypatch.setattr(bc, "LOG_MAX_BYTES", 100)
    p = bc.ChasePlanner()
    for _ in range(20):
        bc.log_decision(1, bc.Action("look", 1.0, why="x"), None, None, p, 0.0)
    assert 0 < f.stat().st_size < 1500


def test_the_180_search_turns_half_way_round_in_one_move(monkeypatch):
    monkeypatch.setattr(bc, "SEARCH_ORDER", "claw_turn_180")
    p = bc.ChasePlanner()
    p.claw_ok, p.seen_ball, p.search_side = True, False, 1
    first, second, third = p._search_move(), p._search_move(), p._search_move()
    assert first.kind == "claw_look"
    assert second.kind == "search_turn" and second.degrees == bc.U_TURN_DEG and second.seconds > bc.SEARCH_MOVE_MAX_S
    assert third.kind == "claw_look"
    monkeypatch.setattr(bc, "SEARCH_ORDER", "turn_180")
    q = bc.ChasePlanner()
    q.search_side = -1
    a = q._search_move()
    assert a.kind == "search_turn" and a.degrees == -bc.U_TURN_DEG


def test_a_ball_gone_right_after_a_line_up_turn_means_he_turned_past_it_so_he_backs_up():
    p = bc.ChasePlanner()
    a = p.decide(reading(3, 36)); assert a.kind == "align"
    assert a.seconds <= bc.ALIGN_PULSE_MAX_S
    p.prev_kind = "align"
    b = p.decide(None)
    assert b.kind == "back" and "turned past" in b.why


def test_a_line_up_pulse_turns_only_part_of_the_bearing_and_less_when_close():
    p = bc.ChasePlanner()
    far = p.decide(reading(6, 16)); near = bc.ChasePlanner().decide(reading(3, 16))
    assert far.kind == near.kind == "align" and far.seconds >= near.seconds >= bc.ALIGN_PULSE_MIN_S


def _search_dir(p):
    for _ in range(6):
        a = p.decide(None)
        if a.kind == "search_turn":
            return 1 if a.degrees > 0 else -1
    return None


def test_the_search_goes_toward_the_side_the_ball_was_last_seen_on(monkeypatch):
    monkeypatch.setattr(bc, "SEARCH_ORDER", "turn")
    p = bc.ChasePlanner(); p.decide(reading(30, -25)); p.last_dist = None
    assert _search_dir(p) == -1
    q = bc.ChasePlanner(); q.decide(reading(30, 25)); q.last_dist = None
    assert _search_dir(q) == 1


def test_with_no_clear_side_the_search_picks_by_chance_so_it_goes_left_sometimes(monkeypatch):
    import random
    monkeypatch.setattr(bc, "SEARCH_ORDER", "turn")
    dirs = set()
    for seed in range(12):
        p = bc.ChasePlanner(rng=random.Random(seed))
        p.decide(reading(30, 1)); p.last_dist = None            # a ball nearly dead ahead: no side
        dirs.add(_search_dir(p))
    assert dirs == {-1, 1}
    dirs = set()
    for seed in range(12):
        dirs.add(_search_dir(bc.ChasePlanner(rng=random.Random(seed))))      # never seen
    assert dirs == {-1, 1}


def test_after_turning_past_the_ball_the_search_goes_back_the_other_way(monkeypatch):
    monkeypatch.setattr(bc, "SEARCH_ORDER", "turn")
    monkeypatch.setattr(bc, "BACK_BUDGET_S", 0.0)               # no back-up left: he searches
    p = bc.ChasePlanner()
    a = p.decide(reading(3, 36)); assert a.kind == "align" and a.degrees > 0     # turned right toward it
    p.prev_kind = "align"
    p.decide(None)
    assert _search_dir(p) == -1                                  # it is on the left of that turn


# ------------------------------------------------------------------------------------------------- the dialing-in steps use Petoi's scripted walk (user, 2026-11-04)

def test_the_small_steps_closer_are_planned_as_scripted_walks_and_the_long_walk_is_not():
    p = bc.ChasePlanner()
    near = p.decide(reading(5.5, 0))                                                                 # between punt_max_in and nudge_max_in, straight ahead: a small step closer
    assert near.kind == "walk" and near.scripted and near.seconds == bc.NUDGE_S
    far = bc.ChasePlanner().decide(reading(30, 0))
    assert far.kind == "walk" and not far.scripted                                                   # the long walk stays the learned policy
    old = bc.NUDGE_GAIT
    bc.NUDGE_GAIT = "policy"
    try:
        assert not bc.ChasePlanner().decide(reading(5.5, 0)).scripted                                # the switch back
    finally:
        bc.NUDGE_GAIT = old


def test_the_loop_sends_a_scripted_step_to_walk_scripted_and_a_robot_without_one_still_walks():
    frames = [picture([disc(122, 110, 30)]), picture([disc(122, 110, 50)])]
    for robot_cls, want in ((ScriptedRobot, "scripted"), (FakeRobot, "walk")):
        robot = robot_cls()
        bc.run_chase(robot, FakeCamera(frames), lambda: False, max_steps=2, sleep=lambda s: None, say=lambda m: None)
        assert [m[0] for m in robot.moves][:1] == [want], robot.moves


# ------------------------------------------------------------------------------------------------- gyro-stopped line-up turns (2026-11-05)

def _gyro_robot(deg_per_s, imu=True, coast_deg=1.0):
    """A SerialRobot on a fake link whose yaw turns at deg_per_s once the turn skill is sent (and coasts a little after kbalance); time moves only when the robot sleeps."""
    t = {"now": 0.0, "since": None, "yaw": 100.0, "stopped": False}

    class Link:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0):
            self.sent.append((c, round(t["now"], 2)))
            if c in ("kwkL", "kwkR"): t["since"] = t["now"]
            if c == "kbalance" and t["since"] is not None:
                t["yaw"] += (t["now"] - t["since"]) * deg_per_s + coast_deg; t["since"] = None
            return ""
        def poll_imu(self):
            if not imu: return []
            yaw = t["yaw"] + ((t["now"] - t["since"]) * deg_per_s if t["since"] is not None else 0.0)
            return [f"ICM:{0.0:6.2f}{0.0:6.2f}{1.0:6.2f}{yaw:7.1f}{0.0:7.1f}{0.0:7.1f}"]

    def sleep(s): t["now"] += s
    lk = Link()
    r = bc.SerialRobot(lk, sleep=sleep, clock=lambda: t["now"])
    r.stand_up = lambda: "ok"
    return r, lk


def test_a_line_up_turn_stops_on_the_gyro_not_the_clock():
    r, lk = _gyro_robot(28.0)
    assert r.turn(30.0, 1.0, stop_deg=5.0) == "ok"                                                  # timed, this would be 1 s = 28 deg
    sent = [c for c, _ in lk.sent]
    assert sent.index("kwkR") < sent.index("kbalance")
    stop_at = [at for c, at in lk.sent if c == "kbalance"][0] - [at for c, at in lk.sent if c == "kwkR"][0]
    assert stop_at < 0.5                                                                            # stopped by the yaw, long before the timed second
    assert r.last_turn_deg is not None and r.last_turn_deg < 8.0 and abs(r.last_turn_s - stop_at) < 1e-6


def test_a_gyro_turn_that_barely_moves_ends_at_the_cap_and_no_imu_means_the_timed_turn():
    r, lk = _gyro_robot(0.5)
    r.turn(-30.0, 1.0, stop_deg=5.0)
    at = {c: t for c, t in lk.sent}
    assert at["kbalance"] - at["kwkL"] <= bc.ALIGN_CAP_S + 0.1 and r.last_turn_deg < 5.0
    r2, lk2 = _gyro_robot(28.0, imu=False)
    r2.turn(30.0, 1.0, stop_deg=5.0)
    at2 = {c: t for c, t in lk2.sent}
    assert abs((at2["kbalance"] - at2["kwkR"]) - 1.0) < 0.1 and r2.last_turn_deg is None            # no yaw frames: the old timed turn


def test_the_line_up_target_is_small_and_inside_its_limits():
    for bearing, dist in ((16, 6), (40, 6), (75, 3), (13, 4)):
        a = bc.ChasePlanner().decide(reading(dist, bearing))
        assert a.kind == "align" and bc.ALIGN_MIN_DEG <= a.stop_deg <= bc.ALIGN_MAX_DEG
    assert bc.ChasePlanner().decide(reading(6, 40)).stop_deg == bc.ALIGN_MAX_DEG


def test_standing_five_seconds_then_tilted_means_sagged_legs_even_in_the_standing_flow(monkeypatch):
    import math
    from pi_pipeline.gait import imu_parse
    assert bc.BETWEEN_MOVES == "stand"
    tilt = {"pitch": -2.0}
    monkeypatch.setattr(imu_parse, "parse_imu_line", lambda line: (0.0, math.radians(tilt["pitch"])))

    class Link(_PoseLink):
        def poll_imu(self): return ["imu"]
        def send(self, c, read_reply=False, settle=0.0):
            if c == bc.CLAW_LOOK_POSE:
                legs = bc._known_poses()["attention"]; self.joints = [0] * 8 + [int(round(legs[sv])) for sv in range(8, 16)]
            if c == "kbalance":
                tilt["pitch"] = -2.0                                                   # up again from the attention pose: the legs hold
                legs = bc._known_poses()["stand"]; self.joints = [0] * 8 + [int(round(legs[sv])) for sv in range(8, 16)]
            return super().send(c, read_reply, settle)
    lk = Link("stand")
    now = {"t": 100.0}
    r = bc.SerialRobot(lk, sleep=lambda s: now.__setitem__("t", now["t"] + s), clock=lambda: now["t"])
    r.posture, r._moved_at = "stand", 100.0
    now["t"] = 103.0
    assert r.stand_up() == "ok" and bc.CLAW_LOOK_POSE not in lk.sent                    # 3 s: too soon to check
    now["t"] = 106.0
    assert r.stand_up() == "ok" and bc.CLAW_LOOK_POSE not in lk.sent                    # 6 s, legs holding: nothing to do
    r._moved_at = 106.0; now["t"] = 112.0
    tilt["pitch"] = -30.0                                                              # the legs let go
    lk.sent.clear()
    assert r.stand_up() == "ok"
    assert bc.CLAW_LOOK_POSE in lk.sent and lk.sent.index(bc.CLAW_LOOK_POSE) < lk.sent.index("kbalance")        # attention pose first, then the stand-up
    assert r.posture == "stand"


def test_a_ball_that_swings_to_the_other_side_after_an_approach_turn_means_back_up_and_look_again():
    p = bc.ChasePlanner()
    a = p.decide(reading(20, 30)); assert a.kind == "turn" and a.degrees > 0                 # on the right: turn right
    p.prev_kind = "turn"
    b = p.decide(reading(19, -22))                                                          # next picture: on the left
    assert b.kind == "back" and "overshot the turn" in b.why
    p.prev_kind = "back"
    c = p.decide(reading(21, -20))
    assert c.kind == "turn" and c.degrees < 0                                               # re-acquired, then lines up again from the new picture


def test_a_turn_that_leaves_the_ball_on_the_same_side_or_near_straight_is_not_an_overshoot():
    p = bc.ChasePlanner(); p.decide(reading(20, 30)); p.prev_kind = "turn"
    assert p.decide(reading(19, 14)).kind != "back"                                         # still right, just less
    q = bc.ChasePlanner(); q.decide(reading(20, 30)); q.prev_kind = "turn"
    assert q.decide(reading(19, -4)).kind != "back"                                         # within the dead band around straight: noise, not a swing
    r = bc.ChasePlanner(); r.decide(reading(20, 30)); r.prev_kind = "walk"
    assert r.decide(reading(19, -22)).kind != "back"                                        # only a turn is judged this way


# ---- falls at transitions (user, 2026-11-06): the pose gate and the calm stop (unproven on G2 until the hardware A/B)

def _gate_robot(tilts):
    """A robot that just changed pose; `_tilt` answers from the list (the last value repeats), `recover_sag` is counted."""
    class Link:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    r = bc.SerialRobot(Link(), sleep=lambda s: None, clock=lambda: 10.0)
    r.posture, r._posed_at, r._stand_tilt = "stand", 5.0, (0.0, 0.0)
    seq = list(tilts)
    r._tilt = lambda seconds=0.5: seq.pop(0) if len(seq) > 1 else seq[0]
    r.reseats = []
    r.recover_sag = lambda tilt=None: (r.reseats.append(tilt), "ok")[1]
    return r


def test_the_gate_lets_a_steady_stance_go_and_checks_once_per_pose_change():
    r = _gate_robot([(1.0, 0.5), (1.2, 0.4)])
    assert r._gate() == "ok" and r.reseats == [] and r.gate_reseats == 0
    r._tilt = lambda seconds=0.5: (_ for _ in ()).throw(AssertionError("checked twice"))
    assert r._gate() == "ok"                                                         # the same pose change is not checked again


def test_the_gate_reseats_legs_that_lag_then_goes_and_never_looks_at_the_pack(monkeypatch):
    r = _gate_robot([(15.0, 0.0), (15.0, 0.0), (1.0, 0.0), (1.0, 0.0)])               # tilted 15 deg off the stand, then steady after the re-seat
    assert r._gate() == "ok" and len(r.reseats) == 1 and r.gate_reseats == 1
    bad = _gate_robot([(20.0, 0.0)])
    assert bad._gate() == "ok" and len(bad.reseats) == bc.GATE_RESEATS               # still off: tried twice, then goes anyway (logged)
    drift = _gate_robot([(0.0, 0.0), (4.0, 0.0), (1.0, 0.0), (1.0, 0.0)])            # steady tilt on average but still moving: the legs are settling
    assert drift._gate() == "ok" and len(drift.reseats) == 1
    assert "battery" not in __import__("inspect").getsource(bc.SerialRobot._gate)


def test_the_gate_lowers_a_raised_claw_first_and_is_off_without_a_pose_change():
    r = _gate_robot([(0.0, 0.0)])
    r._claw = (35.0, 120.0)
    moved = []
    r.claw_pose = lambda pan, lift: (moved.append((pan, lift)), "ok")[1]
    assert r._gate() == "ok" and moved == [(0.0, 0.0)]
    idle = _gate_robot([(30.0, 0.0)])
    idle._posed_at = None
    assert idle._gate() == "ok" and idle.reseats == []                                # no pose change since a verified stance: nothing to check


def test_the_stop_waits_for_a_calm_moment_and_gives_up_after_the_cap(monkeypatch):
    t = {"now": 0.0}
    r = bc.SerialRobot(type("L", (), {"send": lambda s, *a, **k: "", "poll_imu": lambda s: []})(), sleep=lambda s: t.__setitem__("now", t["now"] + s), clock=lambda: t["now"])
    frames = iter([(8.0, 9.0), (6.0, 7.0), (0.5, 0.4), (0.4, 0.5)])                   # swaying through the stride, then calm
    def fell():
        p, ro = next(frames, (0.0, 0.0))
        r._pitch.append(p); r._roll.append(ro)
        return False
    r._fell = fell
    assert r._calm_before_stop() == "ok" and t["now"] < bc.CALM_MAX_S                  # it waited a few samples, not the whole cap
    t["now"] = 0.0
    r2 = bc.SerialRobot(type("L", (), {"send": lambda s, *a, **k: "", "poll_imu": lambda s: []})(), sleep=lambda s: t.__setitem__("now", t["now"] + s), clock=lambda: t["now"])
    def swaying():
        r2._pitch.append(9.0 if len(r2._pitch) % 2 else -9.0); r2._roll.append(9.0)
        return False
    r2._fell = swaying
    assert r2._calm_before_stop() == "ok" and t["now"] >= bc.CALM_MAX_S                # never calm: stops anyway after the cap


def test_a_stop_with_no_imu_frames_does_not_wait():
    t = {"now": 0.0}
    r = bc.SerialRobot(type("L", (), {"send": lambda s, *a, **k: "", "poll_imu": lambda s: []})(), sleep=lambda s: t.__setitem__("now", t["now"] + s), clock=lambda: t["now"])
    assert r._calm_before_stop() == "ok" and t["now"] == 0.0


def test_the_transition_drill_counts_cycles_near_falls_and_stops_at_the_first_fall():
    from pi_pipeline.behavior import transition_drill as td
    class R:
        gate_reseats = 0
        def __init__(self, fell_on, swing=3.0): self.n, self.fell_on, self.swing = 0, fell_on, swing
        def relax(self): return "ok"
        def fallen(self): return False
        def stand_up_from_attention(self): return "ok"
        def turn(self, deg, s): self.n += 1; return "fell" if self.n == self.fell_on else "ok"
        def swing_deg(self): return self.swing
    kw = dict(look=lambda r: None, say=lambda *a: None, sleep=lambda s: None)
    assert td.run_variant(R(0), 4, **kw) == {"cycles": 4, "fell": False, "fell_at": "", "worst_swing_deg": 3.0, "near_falls": 0, "reseats": 0, "stand_ups_with_legs_off": 0}
    third = td.run_variant(R(3), 10, **kw)
    assert third["cycles"] == 1 and third["fell_at"] == "turn left"                    # two turns a cycle: the third turn is in cycle 2
    big = td.run_variant(R(0, swing=25.0), 2, **kw)
    assert big["near_falls"] == 6 and big["worst_swing_deg"] == 25.0                    # stand-up and two turns, twice


def test_the_drill_stops_at_once_when_he_is_found_fallen_after_the_attention_pose():
    from pi_pipeline.behavior import transition_drill as td
    calls = []
    class R:
        gate_reseats = 0
        def relax(self): return "ok"
        def fallen(self): return True
        def stand_up_from_attention(self): calls.append("stand"); return "ok"
        def turn(self, deg, s): calls.append("turn"); return "ok"
        def swing_deg(self): return 0.0
    res = td.run_variant(R(), 5, look=lambda r: calls.append("look"), say=lambda *a: None, sleep=lambda s: None)
    assert res["fell"] and res["cycles"] == 0 and calls == []                       # no claw look, no stand-up, no turn on a fallen G2


def test_a_fall_in_the_middle_of_the_claw_look_stops_the_arm_moves():
    from pi_pipeline.behavior import claw_survey
    sent = []
    class L:
        def send(self, c, **k): sent.append(c)
    state = claw_survey.run_claw_look(L(), None, "x", sleep=lambda s: None, stopped=lambda: True)
    assert state == "stopped" and len([c for c in sent if c.startswith("i0")]) <= 10 and sent[-1] == "gp"


def test_the_leg_check_names_a_joint_that_holds_the_wrong_angle_after_a_stand_up(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    stand = bc._known_poses()["stand"]
    joints = [0] * 16
    for sv, d in stand.items():
        joints[sv] = d
    r = bc.SerialRobot(type("L", (), {"send": lambda s, *a, **k: "", "poll_imu": lambda s: []})(), sleep=lambda s: None, clock=lambda: 0.0)
    monkeypatch.setattr(bc, "read_joints", lambda *a, **k: list(joints))
    assert r.leg_check() == [] and r.last_leg_check == []
    sv = sorted(stand)[3]
    joints[sv] = stand[sv] + 40                                                      # one leg joint kept an old angle (a lost command)
    bad = r.leg_check("test")
    assert [b[0] for b in bad] == [sv] and bad[0][2] == stand[sv] + 40
    monkeypatch.setenv("G2_LEG_CHECK", "0")
    assert r.leg_check() == []


# ---- falls at transitions, the firmware-reading levers (user, 2026-11-06): whole-cycle stop and pre-position (both default off, unproven)

def _timed_robot(monkeypatch, sent):
    t = {"now": 0.0}
    class L:
        def send(self, c, read_reply=False, settle=0.0): sent.append((round(t["now"], 2), c)); return ""
        def poll_imu(self): return []
    r = bc.SerialRobot(L(), sleep=lambda s: t.__setitem__("now", t["now"] + s), clock=lambda: t["now"])
    r._fell = lambda: False
    r.stand_up = lambda: "ok"
    return r, t


def test_a_timed_turn_runs_on_to_a_whole_cycle_when_the_lever_is_on(monkeypatch, tmp_path):
    monkeypatch.setenv("G2_GAIT_CYCLES", str(tmp_path / "c.json"))
    monkeypatch.setenv("G2_GAIT_CYCLE_S", "0.7")
    monkeypatch.setattr(bc, "CYCLE_STOP", True)
    monkeypatch.setattr(bc, "STOP_CALM", False)
    monkeypatch.setattr(bc, "POSE_GATE", False)
    sent = []
    r, t = _timed_robot(monkeypatch, sent)
    assert r.turn(25.0, 1.0) == "ok"
    stop = [x for x in sent if x[1] == "kbalance"][0][0]
    assert 1.38 <= stop <= 1.5                                                         # 2 cycles of 0.7 s, not 1.0 s
    assert r.last_cycle_stop["period_s"] == 0.7 and r.last_cycle_stop["extra_s"] > 0.3


def test_with_the_lever_off_or_no_cycle_the_turn_stops_on_time(monkeypatch, tmp_path):
    monkeypatch.setenv("G2_GAIT_CYCLES", str(tmp_path / "c.json"))
    monkeypatch.delenv("G2_GAIT_CYCLE_S", raising=False)
    monkeypatch.setattr(bc, "STOP_CALM", False)
    monkeypatch.setattr(bc, "POSE_GATE", False)
    for on in (False, True):
        monkeypatch.setattr(bc, "CYCLE_STOP", on)
        sent = []
        r, t = _timed_robot(monkeypatch, sent)
        r.turn(25.0, 1.0)
        stop = [x for x in sent if x[1] == "kbalance"][0][0]
        assert stop < 1.1                                                              # off: on time; on with no known period and no IMU frames: on time too


def test_the_gyro_stopped_line_up_turn_is_never_lengthened(monkeypatch):
    monkeypatch.setattr(bc, "CYCLE_STOP", True)
    src = __import__("inspect").getsource(bc.SerialRobot._skill)
    assert "yaw0 is None and CYCLE_STOP" in src


def test_the_preposition_asks_the_link_only_when_on(monkeypatch):
    monkeypatch.setattr(bc, "STOP_CALM", False)
    monkeypatch.setattr(bc, "POSE_GATE", False)
    asked = []
    for on in (False, True):
        monkeypatch.setattr(bc, "PREPOSITION", on)
        sent = []
        r, t = _timed_robot(monkeypatch, sent)
        r._lk.ease_into = lambda token: (asked.append(token), {"cmd": token, "ran": True})[1]
        r.turn(25.0, 0.3)
    assert asked == ["kwkR"] and r.last_preposition == {"cmd": "kwkR", "ran": True}


def test_eased_stop_freezes_then_eases_to_balance_before_the_kbalance(monkeypatch, tmp_path):
    monkeypatch.setenv("G2_GAIT_CYCLES", str(tmp_path / "c.json"))
    monkeypatch.setenv("G2_GAIT_CYCLE_S", "0.5")
    for k, v in (("EASED_STOP", True), ("CYCLE_STOP", False), ("STOP_CALM", False), ("POSE_GATE", False)):
        monkeypatch.setattr(bc, k, v)
    sent, raw = [], []
    r, t = _timed_robot(monkeypatch, sent)
    r._lk._write_pose = raw.append
    assert r.turn(25.0, 1.0) == "ok"
    assert raw[0].startswith("i8 ") and raw[-1].startswith("i8 ") and len(raw) > 5      # frozen, then a ramp
    assert r.last_eased_stop["ran"] and r.last_eased_stop["secs"] > 0
    kb = [x for x in sent if x[1] == "kbalance"][0][0]
    assert kb >= 1.0 + r.last_eased_stop["secs"] * 0.9                                 # the kbalance came after the ramp


def test_eased_stop_does_nothing_without_a_period_or_a_writer(monkeypatch, tmp_path):
    monkeypatch.setenv("G2_GAIT_CYCLES", str(tmp_path / "c.json"))
    monkeypatch.delenv("G2_GAIT_CYCLE_S", raising=False)
    for k, v in (("EASED_STOP", True), ("CYCLE_STOP", False), ("STOP_CALM", False), ("POSE_GATE", False)):
        monkeypatch.setattr(bc, k, v)
    sent = []
    r, t = _timed_robot(monkeypatch, sent)
    r._lk._write_pose = lambda c: None
    r.turn(25.0, 1.0)
    assert not r.last_eased_stop["ran"] and "period" in r.last_eased_stop["why"]


def test_with_the_scripted_default_gait_a_chase_walk_is_the_firmware_walk(monkeypatch):
    """User, 2026-11-08: the default gait is Petoi's scripted arm gait (`kwkF`, played as `wkArmF` on the arm); no learned walker is made."""
    monkeypatch.setenv("G2_DEFAULT_GAIT", "firmware")
    sent = []

    class L:
        def send(self, c, read_reply=False, settle=0.0): sent.append(c); return ""
        def poll_imu(self): return []
    t = {"now": 0.0}
    r = bc.SerialRobot(L(), sleep=lambda s: t.__setitem__("now", t["now"] + s), clock=lambda: t["now"])
    r.stand_up = lambda: "ok"
    r._fell = lambda: False
    monkeypatch.setattr(bc, "POSE_GATE", False)
    monkeypatch.setattr(bc, "STOP_CALM", False)
    assert r.walk(1.0) == "ok"
    assert "kwkF" in sent and r._walker is None and r.bumped is False


def test_a_stand_up_that_swings_30_degrees_is_a_fall_and_nothing_more_is_sent():
    """2026-11-07: a stand-up with a leg out stayed under the 45 deg limit and the drill kept driving him."""
    from pi_pipeline.behavior import transition_drill as td
    turned = []

    class R:
        gate_reseats = 0
        def relax(self): return "ok"
        def fallen(self): return False
        def stand_up_from_attention(self): return "ok"
        def turn(self, deg, s): turned.append(deg); return "ok"
        def swing_deg(self): return 37.0
    res = td.run_variant(R(), 5, look=lambda r: None, say=lambda *a: None, sleep=lambda s: None)
    assert res["fell"] and res["fell_at"] == "stand-up from attention (swing)" and turned == []


def test_a_turns_only_round_stands_once_and_never_poses_or_looks():
    from pi_pipeline.behavior import transition_drill as td
    log = []

    class R:
        gate_reseats = 0
        def stand_up(self): log.append("stand"); return "ok"
        def relax(self): log.append("relax"); return "ok"
        def fallen(self): return False
        def stand_up_from_attention(self): log.append("up"); return "ok"
        def turn(self, deg, s): log.append(("turn", s)); return "ok"
        def swing_deg(self): return 4.0
    res = td.run_variant(R(), 3, look=lambda r: log.append("look"), say=lambda *a: None, sleep=lambda s: None, turns_only=True)
    assert res["cycles"] == 3 and not res["fell"]
    assert log[0] == "stand" and log.count("stand") == 1 and "relax" not in log and "look" not in log and "up" not in log
    assert [x for x in log if isinstance(x, tuple)] == [("turn", td.TURN_S)] * 6 and td.TURN_S >= 1.4      # the turn is long enough for the cycle stop to have a boundary to reach


def test_a_yaw_spike_at_the_start_of_a_turn_does_not_stop_it(monkeypatch):
    """2026-11-08, a ball goal: `asked 6.0 deg, got 22.4 deg in 0.02 s` ended a line-up turn before it began (a 22 deg jump in 0.02 s is a sensor spike, turns run at about 30 deg/s)."""
    t = {"now": 0.0, "since": None}

    class Link:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0):
            self.sent.append((c, round(t["now"], 2)))
            if c in ("kwkL", "kwkR"): t["since"] = t["now"]
            return ""
        def poll_imu(self):
            yaw = 100.0
            if t["since"] is not None:
                el = t["now"] - t["since"]
                yaw += 22.4 + max(0.0, el - 0.1) * 28.0                                      # a jump of 22 deg right at the start (the reading stays offset), then a real 28 deg/s turn
            return [f"ICM:{0.0:6.2f}{0.0:6.2f}{1.0:6.2f}{yaw:7.1f}{0.0:7.1f}{0.0:7.1f}"]

    def sleep(s): t["now"] += s
    lk = Link()
    r = bc.SerialRobot(lk, sleep=sleep, clock=lambda: t["now"])
    r.stand_up = lambda: "ok"
    assert r.turn(30.0, 1.0, stop_deg=6.0) == "ok"
    at = {c: when for c, when in lk.sent}
    ran = at["kbalance"] - at["kwkR"]
    assert 0.15 < ran < 0.6                                                                      # it kept going past the spike until the real turn reached about 6 deg (a stop on the spike would be at 0.0 s)


def test_with_the_yaw_stop_off_a_line_up_turn_is_the_timed_turn(monkeypatch):
    monkeypatch.setattr(bc, "ALIGN_YAW_STOP", False)
    sent = []

    class Link:
        def send(self, c, read_reply=False, settle=0.0): sent.append(c); return ""
        def poll_imu(self): return []
    t = {"now": 0.0}
    r = bc.SerialRobot(Link(), sleep=lambda s: t.__setitem__("now", t["now"] + s), clock=lambda: t["now"])
    r.stand_up = lambda: "ok"
    r.turn(30.0, 1.0, stop_deg=6.0)
    assert r.last_turn_deg is None and 0.95 <= t["now"] <= 3.0                                  # timed: no yaw was counted


def test_a_stand_only_round_rests_stands_and_stops_at_the_first_fall():
    from pi_pipeline.behavior import transition_drill as td
    sent = []

    class Link:
        def send(self, c, read_reply=False, settle=0.0): sent.append(c); return ""

    class R:
        def __init__(self, swings): self._lk, self.swings, self._pitch, self._roll, self.t = Link(), list(swings), [], [], 0.0
        def _clock(self): self.t += 0.5; return self.t
        def _fell(self): return False
        def swing_deg(self): return self.swings.pop(0)
    ok = td.run_stand_only(R([3.0, 4.0, 5.0]), 3, say=lambda *a: None, sleep=lambda s: None)
    assert ok["cycles"] == 3 and not ok["fell"] and sent.count("kbalance") == 3 and sent.count("krest") == 3 and ok["swings"] == [3.0, 4.0, 5.0]
    sent.clear()
    bad = td.run_stand_only(R([3.0, 40.0, 3.0]), 5, say=lambda *a: None, sleep=lambda s: None)
    assert bad["fell"] and bad["cycles"] == 1 and sent.count("kbalance") == 2                  # it stopped at the second stand-up: nothing more was sent
