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
    a = p.decide(reading(3, 16)); assert a.kind == "turn"                                          # near and off line: align before the punt
    a = p.decide(reading(1.5, 0)); assert a.kind == "punt"                                           # too close to punt


def test_planner_backs_up_when_punts_do_not_move_the_ball():
    p = bc.ChasePlanner()
    kinds = [p.decide(reading(3, 0)).kind for _ in range(bc.STUCK_PUNTS + 1)]
    assert kinds == ["punt"] * bc.STUCK_PUNTS + ["back"]


def test_planner_searches_toward_the_side_it_last_saw_and_never_gives_up():
    p = bc.ChasePlanner()
    p.decide(reading(20, -30))                                                                     # last seen on the left
    assert p.decide(None).kind == "look" and p.decide(None).kind == "look"                         # two more looks first (three real misses before a search)
    a = p.decide(None); assert a.kind == "search_turn" and a.degrees < 0
    kinds = [p.decide(None).kind for _ in range(bc.SEARCH_STEPS_PER_CIRCLE + 2)]
    assert "search_walk" not in kinds and set(kinds) == {"search_turn"}                              # no blind walking by default (a desk): it keeps turning in place, never gives up
    bc.SEARCH_WALK = True
    try:
        q = bc.ChasePlanner(); q.decide(reading(20, -30))
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
    def turn(self, d, s): return self._do(("turn", round(d)))
    def back(self, s): return self._do(("back", round(s, 1)))
    def punt(self): return self._do(("punt",))
    def battery_ok(self): return True


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
    assert r.turn(20, 0.3) == "ok" and r.turn(-20, 0.3) == "ok" and r.walk(0.3) == "ok" and r.back(0.3) == "ok" and r.punt() == "ok"
    toks = [c for c in lk.sent if c.startswith("k")]
    assert toks == ["kwkR", "kbalance", "kwkL", "kbalance", "kwkF", "kbalance", "kbkF", "kbalance", "kpickF", "kbalance", "kpickF", "kbalance"]      # (this fake link reports no IMU swing, so the punt is sent twice)


def test_the_battery_gate_fails_safe_and_the_serial_robot_uses_it():
    from pi_pipeline.power import battery

    class Link:
        def __init__(self, reply): self.reply = reply
        def drain(self, s): pass
        def send(self, c, **k): return self.reply
    assert battery.motion_gate(Link("Voltage: 8.20 V")) == (True, 88, 8.2)
    ok, pct, v = battery.motion_gate(Link("Voltage: 7.30 V")); assert ok is False and pct < 30 and v == 7.3         # low: not ok
    assert battery.motion_gate(Link("G")) == (False, None, None)                                                   # unreadable: not ok, never "fine"
    assert bc.SerialRobot(Link("Voltage: 8.20 V")).battery_ok() is True and bc.SerialRobot(Link("junk")).battery_ok() is False


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
