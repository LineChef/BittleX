"""The shared active look (behavior/active_look.py): the arm, a pluggable tracking method, the end-of-follow judges, the tracking filter, coasting, motion, and the exposure lock (2026-11-17)."""
import importlib.util
import io
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from pi_pipeline.behavior import active_look as al
from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.behavior import live_follow as lf
from pi_pipeline.behavior.ball_tracker import BallTracker
from pi_pipeline.behavior.track_filter import BearingFilter
from pi_pipeline.tests.test_punt_watch import Clock, Script, WatchRobot
from pi_pipeline.vision.motion_detector import PX_PER_DEG, MotionDetector


# ---- the tracking filter
def test_the_filter_follows_a_steady_mover_predicts_ahead_and_ignores_an_old_picture():
    f = BearingFilter()
    assert f.predict(1.0) is None and f.residual(1.0, 5.0) is None
    for i in range(8):
        f.update(1.0 + 0.3 * i, 10.0 * i)                     # 10 deg per 0.3 s = 33 deg/s
    assert abs(f.v - 33.3) < 4.0 and abs(f.predict(3.1 + 0.3) - (70.0 + 10.0)) < 6.0
    b = f.b
    f.update(0.5, 999.0)                                      # an older picture than the last: no change
    assert f.b == b and abs(f.age(f.t + 1.0) - 1.0) < 1e-9
    f.reset()
    assert f.b is None and f.n == 0


# ---- the follower: coasting and the jump check against the prediction
def _follower(**kw):
    cfg = lf.LiveConfig(deadband_deg=1.0, min_move_deg=0.5, **kw)
    return lf.LiveFollower(cfg, "left", lf.PanLog(0.0, 0.0))


def test_with_no_sighting_the_claw_coasts_toward_where_the_target_is_going_and_only_briefly():
    f = _follower(coast_s=1.0)
    ball = lambda x: [("ball", 1.0, x, 0.6, 0.1, 0.1)]                        # noqa: E731
    for i, t in enumerate((1.0, 1.3, 1.6, 1.9)):
        f.decide(t, ball(0.5 + 0.06 * i), t + 0.2, 0.0)                       # drifting right: about 17 deg/s
    want = f.decide(2.2, [], 2.4, 0.0)                                        # a picture with no ball, 0.3 s after the last one
    assert want is not None and want < 0 and f.coasting and "coast" in f.reason          # the pan turns the camera toward the right (negative for "left")
    assert f.decide(3.6, [], 3.8, 0.0) is None and not f.coasting                          # 1.7 s without one: it stops coasting
    off = _follower(coast_s=0.0)
    for t, x in ((1.0, 0.5), (1.3, 0.56), (1.6, 0.62)):
        off.decide(t, ball(x), t + 0.2, 0.0)
    assert off.decide(1.9, [], 2.1, 0.0) is None                              # coasting is off by default


def test_a_fast_steady_mover_is_not_a_jump_but_a_real_jump_still_is():
    f = _follower(jump_deg=15.0)
    ball = lambda x: [("ball", 1.0, x, 0.6, 0.1, 0.1)]                        # noqa: E731
    for i in range(4):
        assert f.tracked(1.0 + 0.3 * i, ball(0.30 + 0.12 * i)) is not None    # about 10.6 deg per 0.3 s: steady, so each one is where the filter expects it
    assert f.tracked(2.2, ball(0.99)) is None                                 # far from the prediction: held until a second one agrees
    assert f.tracked(2.5, ball(0.98)) is not None


# ---- the motion detector
def _scene(seed=1):
    rng = np.random.default_rng(seed)
    base = 110 + rng.normal(0, 4, (240, 240))
    base[:, ::6] += 15                                         # some structure so a shift is visible
    return np.clip(base, 0, 255)


def _jpeg(gray, ball_xy=None):
    im = Image.fromarray(np.stack([gray] * 3, axis=2).astype(np.uint8))
    if ball_xy:
        x, y = ball_xy
        ImageDraw.Draw(im).ellipse((x - 8, y - 8, x + 8, y + 8), fill=(235, 235, 235))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_the_motion_detector_finds_a_mover_and_not_a_static_scene_or_an_exposure_swing():
    scene = _scene()
    d = MotionDetector("left")
    assert d.update(_jpeg(scene, (60, 120)), 0.0) == []                       # no earlier picture
    c = d.update(_jpeg(scene, (140, 120)), 0.0)                               # the same scene, the ball moved 80 px
    assert c and any(abs(x[2] - 140 / 240) < 0.05 for x in c)                 # one candidate is where the ball is now
    d.reset()
    d.update(_jpeg(scene), 0.0)
    assert d.update(_jpeg(scene), 0.0) == []                                  # nothing moved
    d.reset()
    d.update(_jpeg(scene), 0.0)
    assert d.update(_jpeg(np.clip(scene + 45, 0, 255)), 0.0) == []            # the whole picture got brighter: no candidates


def test_the_motion_detector_compensates_for_the_pan_between_two_pictures():
    scene = _scene(2)
    shift = int(round(10 * PX_PER_DEG))
    d = MotionDetector("left")
    d.update(_jpeg(scene), 0.0)
    panned = np.roll(scene, shift, axis=1)                                    # the claw panned 10 deg: the whole scene moved sideways
    assert d.update(_jpeg(panned), 10.0) == []                                # compensated: the static scene shows nothing
    compensated = d.last_changed_share
    d.reset()
    d.update(_jpeg(scene), 0.0)
    d.update(_jpeg(panned), 0.0)                                              # the same two pictures with no compensation
    assert d.last_changed_share > compensated + 0.03                          # far more of the picture changed


# ---- the ball's tracker: motion only near the filter's prediction
def _bound_tracker(n=3, b=3.7, v=0.0, t=1.9):
    tr = BallTracker()
    f = lf.LiveFollower(lf.LiveConfig(), "left", lf.PanLog(0.0, 0.0))
    f.filter.b, f.filter.v, f.filter.t, f.filter.n = b, v, t, n
    tr.bind(f.pan_log, f, Clock())
    return tr, f


def test_a_missed_colour_sighting_is_stood_in_for_by_motion_only_near_the_filters_prediction():
    scene = _scene(3)
    tr, f = _bound_tracker()                                                  # the filter expects the ball at about +3.7 deg (x = 130 px) at t = 2.0
    tr(_jpeg(scene, (100, 120)), 1.75)
    dets = tr(_jpeg(scene, (130, 120)), 2.0)                                  # a grey ball: the colour finder sees nothing, motion shows it near the prediction
    assert dets and dets[0][0] == "ball" and tr.motion_sightings == 1
    far, f2 = _bound_tracker(b=40.0)                                          # the filter expects it far to the right: the nearby mover is not it
    far(_jpeg(scene, (100, 120)), 1.75)
    assert far(_jpeg(scene, (130, 120)), 2.0) == []
    fresh, f3 = _bound_tracker(n=1)                                           # too few sightings: motion alone never starts a track
    fresh(_jpeg(scene, (100, 120)), 1.75)
    assert fresh(_jpeg(scene, (130, 120)), 2.0) == []


# ---- the shared function with a different tracking method
class FakeTracker:
    """Not the ball: any tracking method with the same shape. Sees a 'person' drifting right."""
    name = "person"
    wants_capture_time = True

    def __init__(self):
        self.bound, self.times = None, []

    def bind(self, pan_log, follower, clock):
        self.bound = (pan_log, follower)

    def __call__(self, jpeg, t_capture=None):
        self.times.append(t_capture)
        return [("person", 0.9, 0.6, 0.5, 0.2, 0.4)]


class LockableScript(Script):
    def __init__(self, clock, **kw):
        super().__init__(clock, **kw)
        self.lock_calls = []

    def set_exposure_lock(self, on):
        self.lock_calls.append(on)
        return True


def _run(robot, tracker=None, judge=None, cfg=None, grab=None, vanish_at=None, clock=None, **kw):
    c = clock or Clock()
    g = grab or Script(c, vanish_at=vanish_at)
    res = al.run_active_look(robot, lambda find, cf, clock, save: g, tracker or FakeTracker(), cfg or lf.LiveConfig(seconds=2.0, tick_s=0.05), judge=judge, say=lambda *_: None, sleep=c.sleep, clock=c, **kw)
    return res, g


def test_the_arm_goes_to_120_through_the_attention_pose_unless_it_is_already_up():
    r = WatchRobot()
    res, _ = _run(r)
    assert r.calls[:2] == ["relax", ("claw", 0.0, 120.0)] and res.arm_raised and res.ended == "time"
    up = WatchRobot()
    up.claw_is_up = lambda: True
    res, _ = _run(up)
    assert "relax" not in up.calls and not res.arm_raised                      # a punt leaves it up: nothing is moved
    direct = WatchRobot()
    res, _ = _run(direct, cfg=lf.LiveConfig(seconds=1.0, tick_s=0.05, attention_first=False))
    assert direct.calls[0] == ("claw", 0.0, 120.0) and "relax" not in direct.calls


def test_any_tracking_method_can_be_passed_it_is_bound_to_the_follow_and_given_capture_times():
    tr = FakeTracker()
    r = WatchRobot()
    res, grab = _run(r, tracker=tr, judge=al.TimeOnlyJudge())
    assert tr.bound is not None and isinstance(tr.bound[1], lf.LiveFollower)
    plain = []
    res2, _ = _run(WatchRobot(), tracker=lambda jpeg: plain.append(1) or [])           # a plain function works too (wrapped)
    assert res2.ended == "time" and isinstance(al.as_tracker(lambda j: []), al.SimpleTracker)


def test_the_judges_end_the_follow_and_the_result_says_where_the_target_was_last_seen():
    class Left(FakeTracker):
        def __call__(self, jpeg, t_capture=None):
            return [("person", 0.9, 0.2, 0.5, 0.2, 0.4)]
    cfg = lf.LiveConfig(seconds=20.0, tick_s=0.05)
    res, _ = _run(WatchRobot(), tracker=Left(), cfg=cfg, judge=al.TimeOnlyJudge(), seconds=1.0)
    assert res.ended == "time" and res.last_side == -1 and res.sightings and res.last_bearing < 0
    stop = al.StopOrLostJudge(al.StopLostConfig(seconds=20.0, stable_n=3, min_span_s=0.3))
    res, _ = _run(WatchRobot(), cfg=cfg, judge=stop, tracker=lambda j: [("ball", 1.0, 0.5, 0.6, 0.1, 0.1)])
    assert res.ended == "stopped"                                              # a target that stays put has stopped
    never = al.StopOrLostJudge(al.StopLostConfig(seconds=20.0, never_seen_s=1.0))
    res, _ = _run(WatchRobot(), cfg=cfg, judge=never, tracker=lambda j: [], vanish_at=0.0)         # nothing is ever in view
    assert res.ended == "lost" and res.last_side == 0 and res.last_bearing is None


def test_a_fall_while_raising_the_arm_ends_it_as_a_fall_and_the_stop_file_as_stopped_by_user():
    class Falls(WatchRobot):
        def claw_pose(self, pan, lift):
            return "fell"
    res, _ = _run(Falls())
    assert res.ended == "fell"
    res, _ = _run(WatchRobot(), stopped=lambda: True)
    assert res.ended == "stopped_by_user"


def test_the_exposure_lock_is_frozen_for_the_follow_only_and_always_restored():
    c = Clock()
    g = LockableScript(c)
    res, _ = _run(WatchRobot(), grab=g, cfg=lf.LiveConfig(seconds=1.0, tick_s=0.05, exposure_lock=True))
    assert g.lock_calls == [True, False]
    off = LockableScript(c)
    _run(WatchRobot(), grab=off)
    assert off.lock_calls == []                                                # off by default
    boom = LockableScript(c)

    class Boom(FakeTracker):
        def __call__(self, jpeg, t_capture=None):
            raise RuntimeError("tracker failed")
    res, _ = _run(WatchRobot(), tracker=Boom(), grab=boom, cfg=lf.LiveConfig(seconds=1.0, tick_s=0.05, exposure_lock=True))
    assert boom.lock_calls[-1] is False                                        # restored even when the tracking method breaks (the grabber catches it; the follow goes on)


# ---- parity: one follow loop
def test_no_mode_runs_its_own_follow_loop():
    spec = importlib.util.spec_from_file_location("check_modes_r8", Path(__file__).resolve().parents[2] / "tools" / "check_modes.py")
    cm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cm)
    assert not [v for v in cm.violations() if v["rule"] == "R8"]
    assert cm.FOLLOW_CALL.search("out = follow_loop(robot, grab)") and cm.FOLLOW_CALL.search("f = LiveFollower(cfg)") and "behavior/active_look.py" in cm.FOLLOW_HOMES


def test_the_ball_watch_and_the_live_follow_both_go_through_the_shared_function():
    import inspect

    from pi_pipeline.behavior import punt_watch
    assert "run_active_look(" in inspect.getsource(punt_watch.watch_after_punt) and "run_active_look(" in inspect.getsource(lf.run_live)
    assert "follow_loop(" not in inspect.getsource(punt_watch) and bc.CLAW_PAN_SIGN in ("left", "right")


# ---- the follow calibration's arithmetic and its loop on fakes
def test_the_follow_calibration_measures_the_picture_delay_and_the_pan_speed():
    from pi_pipeline.behavior import follow_cal as fc
    # a 20 deg step to the left claw-pan: the scene moves right by 20/89 of the width; the pictures show nothing for 0.4 s, then the move over the next 0.5 s
    ts, te = 10.0, 10.3
    total = 20.0 / 89.0
    rows = [(9.7 + 0.25 * i, 0.5) for i in range(2)]                           # before the command
    rows += [(10.0 + 0.1 * i, 0.5 + total * min(1.0, max(0.0, (10.0 + 0.1 * i - 10.4) / 0.5))) for i in range(1, 21)]
    m = fc.step_metrics(ts, te, 0.0, 20.0, rows)
    assert 0.4 <= m["delay_s"] <= 0.7 and 35.0 <= m["speed_deg_s"] <= 60.0 and m["command_s"] == 0.3 and 18.0 <= m["settled_deg"] <= 21.0
    assert fc.step_metrics(ts, te, 0.0, 20.0, rows[:2])["delay_s"] is None      # no pictures after the command: nothing to say
    s = fc.summarize([m, {**m, "step_deg": -20.0}])
    assert s["delay_s"]["n"] == 2 and 20.0 in s["speed_by_step_deg"]


def test_the_follow_calibration_loop_takes_each_step_out_and_back_and_stops_on_a_fall():
    from pi_pipeline.behavior import follow_cal as fc

    class Cal(WatchRobot):
        def __init__(self):
            super().__init__()
            self.pans = []
            self.fall_at = None

        def claw_pose(self, pan, lift):
            self.pans.append(pan)
            return "fell" if self.fall_at is not None and len(self.pans) >= self.fall_at else "ok"
    c = Clock()

    class Rows(Script):
        def __init__(self, clock):
            super().__init__(clock)
            self.rows = [{"t_done": 0.0, "det": [("ball", 0.5)]}]
    r = Cal()
    out = fc.run_follow_cal(r, lambda find, cfg, clock, save: Rows(c), lambda j: [], steps=(10.0, 20.0), repeats=1, say=lambda *_: None, sleep=c.sleep, clock=c)
    assert out["ended"] == "done" and len(out["trials"]) == 8                      # 2 sizes x 2 directions x (out and back)
    assert r.pans[1:] == [10.0, 0.0, -10.0, 0.0, 20.0, 0.0, -20.0, 0.0]            # (the first claw_pose is the arm going up)
    f = Cal()
    f.fall_at = 3
    assert fc.run_follow_cal(f, lambda find, cfg, clock, save: Rows(c), lambda j: [], steps=(10.0,), repeats=1, say=lambda *_: None, sleep=c.sleep, clock=c)["ended"] == "fell"


# ---- 2026-11-17 (owner-approved): a judge per mode, the per-picture log for every use, the arm height per call, safety no mode can widen
class FixedScript(Script):
    """A grabber whose target sits at one place in every picture (cx as a share of the width), or is never there."""

    def __init__(self, clock, cx=0.5, there=True):
        super().__init__(clock)
        self.cx, self.there = cx, there

    def take(self):
        t = self.clock()
        return (t - 0.2, [("person", 0.9, self.cx, 0.5, 0.2, 0.4)] if self.there else [], int(t / 0.25) + 1)


def test_a_greeting_style_look_ends_centred_once_the_target_has_stayed_in_the_middle():
    cfg = lf.LiveConfig(seconds=20.0, tick_s=0.05)
    c = Clock()
    res, _ = _run(WatchRobot(), cfg=cfg, judge=al.CenteredJudge(hold_s=1.0, tol_deg=6.0), grab=FixedScript(c, 0.5), clock=c)
    assert res.ended == "centred"                                              # right in the middle for a second
    c = Clock()
    res, _ = _run(WatchRobot(), cfg=lf.LiveConfig(seconds=2.0, tick_s=0.05), judge=al.CenteredJudge(hold_s=1.0, tol_deg=6.0), grab=FixedScript(c, 0.9), clock=c)
    assert res.ended == "time"                                                 # 35 deg off the middle in every picture (the fake claw never turns): never centred
    c = Clock()
    res, _ = _run(WatchRobot(), cfg=lf.LiveConfig(seconds=3.0, tick_s=0.05), judge=al.CenteredJudge(hold_s=5.0, lost_after_s=1.0), grab=FixedScript(c, 0.5, there=False), clock=c)
    assert res.ended == "time"                                                 # never seen: "lost" needs a first sighting, so only the time ends it


def test_every_use_keeps_the_per_picture_log_in_its_result_and_the_live_follow_writes_it():
    from pi_pipeline.behavior import punt_watch
    assert punt_watch.frame_log is al.frame_log                                # one log format, defined once
    rows = [{"t_capture": 5.0, "det": [("x", 0.5)], "best": (0.5, 0.5, 0.1), "mean": 100, "bytes": 6000}, {"t_capture": 5.3, "det": [], "mean": 90, "bytes": 5900, "diag": {"area": 7, "x": 3, "y": 4}}]

    class Rows(Script):
        def __init__(self, clock):
            super().__init__(clock)
            self.rows = rows
    c = Clock()
    res = al.run_active_look(WatchRobot(), lambda f, cf, clk, sv: Rows(c), lambda j: [], lf.LiveConfig(seconds=1.0, tick_s=0.05), say=lambda *_: None, sleep=c.sleep, clock=c)
    assert res.frames == al.frame_log(rows) and res.frames[0]["ball"] == [0.5, 0.5, 0.1] and res.frames[1]["blob"] == [7, 3, 4]


def test_a_mode_picks_the_arm_height_and_the_default_stays_120():
    r = WatchRobot()
    _run(r, lift_deg=90.0)
    assert r.calls[:2] == ["relax", ("claw", 0.0, 90.0)]
    r2 = WatchRobot()
    _run(r2)
    assert r2.calls[1] == ("claw", 0.0, al.DEFAULT_LIFT_DEG) and al.DEFAULT_LIFT_DEG == 120.0


def test_safety_is_the_same_for_every_mode_a_config_can_lower_the_limits_but_never_raise_them():
    seen = {}

    class Spy(lf.LiveConfig):
        pass
    orig = lf.follow_loop

    def spy(robot, grab, follower, pan_log, cfg, **kw):
        seen["cfg"] = cfg
        return orig(robot, grab, follower, pan_log, cfg, **kw)
    lf.follow_loop = spy
    try:
        _run(WatchRobot(), cfg=lf.LiveConfig(seconds=0.5, tick_s=0.05, max_tilt_change_deg=45.0, tilt_check_s=9.0))
        assert seen["cfg"].max_tilt_change_deg == al.MAX_TILT_CHANGE_DEG == 10.0 and seen["cfg"].tilt_check_s == al.MAX_TILT_CHECK_S                    # raised values are clamped
        _run(WatchRobot(), cfg=lf.LiveConfig(seconds=0.5, tick_s=0.05, max_tilt_change_deg=4.0, tilt_check_s=0.5))
        assert seen["cfg"].max_tilt_change_deg == 4.0 and seen["cfg"].tilt_check_s == 0.5                                                               # lowered values are kept
    finally:
        lf.follow_loop = orig


def test_a_fall_a_sag_and_the_stop_file_end_the_follow_with_any_judge_and_any_tracker():
    judges = (al.TimeOnlyJudge, lambda: al.StopOrLostJudge(al.StopLostConfig(seconds=20.0)), lambda: al.CenteredJudge())
    trackers = (FakeTracker(), lambda j: [])
    for make_judge in judges:
        for tr in trackers:
            class Falls(WatchRobot):
                def _fell(self):
                    return True
            res, _ = _run(Falls(), tracker=tr, judge=make_judge())
            assert res.ended == "fell"
            res, _ = _run(WatchRobot(), tracker=tr, judge=make_judge(), stopped=lambda: True)
            assert res.ended == "stopped_by_user"
            tilting = WatchRobot()
            tilts = iter([(0.0, 0.0)] + [(0.0, 30.0)] * 400)
            tilting._tilt = lambda *a, **k: next(tilts)
            tilting._roll, tilting._pitch = [30.0] * 10, [0.0] * 10
            res, _ = _run(tilting, tracker=tr, judge=make_judge(), cfg=lf.LiveConfig(seconds=5.0, tick_s=0.05, tilt_check_s=0.2))
            assert res.ended == "sag"


def test_the_follow_calibration_can_freeze_exposure_for_the_run_and_always_restores_it_and_reports_the_brightness_spread():
    from pi_pipeline.behavior import follow_cal as fc
    c = Clock()

    class Rows(LockableScript):
        def __init__(self, clock):
            super().__init__(clock)
            self.rows = [{"t_done": 0.0, "det": [("ball", 0.5)], "mean": 150}, {"t_done": 0.3, "det": [], "mean": 110}, {"t_done": 0.6, "det": []}]
    g = Rows(c)
    out = fc.run_follow_cal(WatchRobot(), lambda f, cf, clk, sv: g, lambda j: [], steps=(10.0,), repeats=1, say=lambda *_: None, sleep=c.sleep, clock=c, exposure_lock=True)
    assert g.lock_calls == [True, False] and out["summary"]["exposure_locked"] is True
    assert out["summary"]["brightness"] == {"n": 2, "no_brightness": 1, "min": 110, "max": 150, "mean": 130.0, "stdev": 20.0}
    g2 = Rows(c)
    out2 = fc.run_follow_cal(WatchRobot(), lambda f, cf, clk, sv: g2, lambda j: [], steps=(10.0,), repeats=1, say=lambda *_: None, sleep=c.sleep, clock=c)
    assert g2.lock_calls == [] and out2["summary"]["exposure_locked"] is False


def test_every_claw_move_ends_with_the_settle_step_and_home_keeps_its_own_confirm():
    class Link:
        def __init__(self): self.sent = []
        def send(self, c, read_reply=False, settle=0.0): self.sent.append(c); return ""
        def poll_imu(self): return []
    r = bc.SerialRobot(Link(), sleep=lambda s: None, clock=lambda: 0.0)
    r._fell = lambda: False
    assert r.claw_pose(20.0, 120.0) == "ok"
    assert [c for c in r._lk.sent if c.startswith("i")][-bc.CLAW_SETTLE_RESENDS:] == ["i0 20 1 120"] * bc.CLAW_SETTLE_RESENDS


# ---- 2026-11-17 (owner-approved): far balls: the ball's own colour in every look, still retries before "lost", far-miss evidence
def test_the_shared_finder_falls_back_to_the_balls_own_colour_and_the_chase_looks_use_it(monkeypatch):
    from pi_pipeline.vision import ball_finder as bf
    calls = []
    monkeypatch.setattr(bf, "find_ball", lambda j: None)
    monkeypatch.setattr(bf, "find_ball_color", lambda j, c: calls.append(c) or "found")
    assert bf.find_ball_or_color(b"x", (1, 2, 3)) == "found" and calls == [(1, 2, 3)]
    assert bf.find_ball_or_color(b"x", None) is None and bf.find_ball_or_color(b"", (1, 2, 3)) is None
    import inspect
    from pi_pipeline.behavior import ball_chase as bc
    src = inspect.getsource(bc)
    assert src.count("bf_find_ball_or_color") >= 3                              # the claw look and the walking look both use the shared finder (plus its import)


def test_the_watch_looks_again_before_it_says_the_ball_is_lost():
    from pi_pipeline.behavior import punt_watch as pw
    c = Clock()
    tries = {"n": 0}

    def find_still(camera):
        tries["n"] += 1
        return None
    find_still.last_diag = None
    r = pw.watch_after_punt(WatchRobot(), object(), lambda f, cf, clk, sv: FixedScript(c, there=False), lambda j: [], find_still, pw.WatchConfig(seconds=1.0), say=lambda *_: None, announce=lambda *_: None, sleep=c.sleep, clock=c)
    assert tries["n"] == 1 + pw.STILL_RETRIES and r.found is False
    tries["n"] = 0

    def second_time(camera):
        tries["n"] += 1
        return None if tries["n"] < 3 else bc_reading()
    second_time.last_diag = None
    c2 = Clock()
    r2 = pw.watch_after_punt(WatchRobot(), object(), lambda f, cf, clk, sv: FixedScript(c2, there=False), lambda j: [], second_time, pw.WatchConfig(seconds=1.0), say=lambda *_: None, announce=lambda *_: None, sleep=c2.sleep, clock=c2)
    assert tries["n"] == 3 and r2.found is True


def bc_reading():
    from pi_pipeline.vision import ball_finder as bf
    return bf.BallReading(120.0, 150.0, 100, 12, 12, 12.0, 20.0, 0.0, False, "normal")


def test_far_misses_are_noted_and_at_most_six_pictures_are_kept_per_session(tmp_path, monkeypatch):
    import io
    import os
    import numpy as np
    from PIL import Image
    from pi_pipeline.vision import miss_log
    monkeypatch.setenv("HOME", str(tmp_path))
    rgb = np.zeros((240, 240, 3), dtype=np.uint8)
    rgb[150:162, 100:112] = (60, 200, 60)                                        # a small green blob: worth a picture
    buf = io.BytesIO(); Image.fromarray(rgb).save(buf, "JPEG"); green = buf.getvalue()
    buf = io.BytesIO(); Image.fromarray(np.zeros((240, 240, 3), dtype=np.uint8)).save(buf, "JPEG"); empty = buf.getvalue()
    miss_log.begin_session()
    assert miss_log.note_miss(empty, "a") is None and miss_log.note_miss(None, "a") is None            # an empty floor: noted, no picture
    for _ in range(9):
        miss_log.note_miss(green, "watch_still")
    saved = [f for d, _, fs in os.walk(tmp_path) for f in fs if f.startswith("miss_")]
    assert len(saved) == miss_log.MAX_PICTURES == 6 and miss_log.notes()[-1]["blob"]["area"] > 10
    miss_log.begin_session()
    assert miss_log.notes() == []


# ---- 2026-11-17 (owner-approved after two falls on a rolled stand): the final tilt check before every move, the level check after every stand-up
def _tilt_robot(monkeypatch, tilts):
    from pi_pipeline.behavior import ball_chase as bc
    sent = []

    class L:
        def send(self, c, read_reply=False, settle=0.0): sent.append(c); return ""
        def poll_imu(self): return []
    r = bc.SerialRobot(L(), sleep=lambda s: None, clock=lambda: 0.0)
    seq = iter(tilts)
    r._tilt = lambda seconds=0.5: next(seq, (0.0, 0.0))
    r._already_fell = lambda t: False
    r.posture = "stand"
    return r, sent, bc


def test_the_final_tilt_check_lets_a_level_body_move_and_stops_a_rolled_one(monkeypatch):
    r, sent, bc = _tilt_robot(monkeypatch, [(1.0, 2.0)])
    assert r._tilt_before_move() == "ok" and r.move_gate_stops == 0 if hasattr(r, "move_gate_stops") else True
    r, sent, bc = _tilt_robot(monkeypatch, [(0.0, 23.0), (0.0, 1.0)])
    calls = []
    r.recover_sag = lambda t=None: calls.append(t) or "ok"
    assert r._tilt_before_move() == "ok" and calls == [(0.0, 23.0)] and r.move_gate_stops == 1       # rolled 23 deg: laid down and stood up again, then level: goes on
    r, sent, bc = _tilt_robot(monkeypatch, [(0.0, 23.0), (0.0, 21.0)])
    r.recover_sag = lambda t=None: "ok"
    assert r._tilt_before_move() == "fell"                                                             # still rolled after standing again: the move is not sent


def test_every_leg_move_and_every_punt_ends_with_the_final_tilt_check(monkeypatch):
    import inspect
    from pi_pipeline.behavior import ball_chase as bc
    assert "_tilt_before_move" in inspect.getsource(bc.SerialRobot._skill) and "_tilt_before_move" in inspect.getsource(bc.SerialRobot._punch)
    assert bc.FINAL_TILT_S == 0.3 and bc.STAND_LEVEL_DEG == 8.0 and bc.MOVE_TILT_GATE_DEG == 12.0


def test_a_stand_up_that_ends_rolled_is_repeated_once_and_every_stand_up_is_logged(monkeypatch):
    r, sent, bc = _tilt_robot(monkeypatch, [])
    tick = {"t": 0.0}

    def clock():
        tick["t"] += 0.5
        return tick["t"]
    r._clock = clock                                                          # a clock that moves, so the stand-up's wait loop ends
    monkeypatch.setattr(bc, "wait_for_pose", lambda *a, **k: "stand")
    monkeypatch.setattr(r, "leg_check", lambda *a, **k: None)
    r._fell = lambda: False
    r._imu_release = lambda: None
    ends = iter([(0.0, 20.0), (0.0, 2.0)])
    r._tilt = lambda seconds=0.5: next(ends, (0.0, 0.0))
    r.claw_pose = lambda *a, **k: "ok"
    assert r._stand_up_from("rest") == "ok"
    assert [e["roll"] for e in r.stand_log] == [20.0, 2.0] and [e["repeat"] for e in r.stand_log] == [False, True]   # rolled 20 deg: once more from rest, level the second time
    assert sent.count("kbalance") == 2 and "krest" in sent


def test_the_turn_calibration_logs_asked_against_counted_yaw_and_stops_on_a_fall():
    from pi_pipeline.behavior import turn_cal as tc

    class R(WatchRobot):
        def __init__(self, fall_at=None):
            super().__init__()
            self.n, self.fall_at = 0, fall_at
            self.last_turn_deg = self.last_turn_s = self.last_turn_end = None
            self._roll, self._pitch = [1.0, 4.0], [0.0, 2.0]

        def _tilt(self, *a, **k):
            return (0.0, 1.0)

        def turn(self, degrees, seconds, stop_deg=0.0):
            self.n += 1
            self.last_turn_deg, self.last_turn_s, self.last_turn_end = abs(degrees) * 2.0, 0.5, "gyro"       # overshoots by double, like the small turns do
            return "fell" if self.fall_at == self.n else "ok"
    out = tc.run_turn_cal(R(), asks=(6.0, 20.0), repeats=1, say=lambda *_: None, sleep=lambda s: None)
    assert out["ended"] == "done" and len(out["trials"]) == 4 and out["summary"]["asked_6"]["overshoot_median"] == 2.0 and out["summary"]["asked_6"]["roll_swing_max"] == 3.0
    out = tc.run_turn_cal(R(fall_at=2), asks=(6.0, 20.0), repeats=1, say=lambda *_: None, sleep=lambda s: None)
    assert out["ended"] == "fell" and len(out["trials"]) == 2 and out["summary"]["fell"] == 1


def test_the_turn_calibration_measures_forward_travel_from_a_fixed_ball_and_the_turn_skill_can_be_swapped():
    from pi_pipeline.behavior import ball_chase as bc
    from pi_pipeline.behavior import turn_cal as tc
    assert bc.SerialRobot.__init__.__code__ and "turn_tokens" in bc.SerialRobot.turn.__code__.co_names
    seen = iter([bc.BallReading(120.0, 150.0, 100, 12, 12, 12.0, 18.0, 0.0, False, "normal"), bc.BallReading(120.0, 150.0, 100, 12, 12, 12.0, 15.0, 10.0, False, "normal")])

    class R(WatchRobot):
        last_turn_deg, last_turn_s, last_turn_end = 6.0, 0.5, "gyro"
        _roll, _pitch = [0.0, 1.0], [0.0, 1.0]

        def _tilt(self, *a, **k): return (0.0, 0.0)
        def turn(self, degrees, seconds, stop_deg=0.0): return "ok"
    out = tc.run_turn_cal(R(), asks=(6.0,), repeats=1, say=lambda *_: None, sleep=lambda s: None, look=lambda: next(seen, None))
    t = out["trials"][0]
    assert t["fwd_in"] == round(18.0 - 15.0 * 0.985, 1) and out["trials"][1].get("fwd_in") is None               # the 2nd look found no ball: no number, no crash


def test_the_turn_calibration_logs_which_way_the_gyro_says_each_turn_went():
    """2026-11-18: the pivot test counted only the size of each turn, so it could not say whether a right command really turned him right; each trial now carries the signed yaw change."""
    from pi_pipeline.behavior import turn_cal as tc

    class R(WatchRobot):
        last_turn_deg, last_turn_s, last_turn_end = 40.0, 1.0, "gyro"
        last_turn_signed = -40.0
        _roll, _pitch = [0.0, 1.0], [0.0, 1.0]

        def _tilt(self, *a, **k): return (0.0, 0.0)
        def turn(self, degrees, seconds, stop_deg=0.0): return "ok"
    lines = []
    out = tc.run_turn_cal(R(), asks=(45.0,), repeats=1, say=lines.append, sleep=lambda s: None)
    assert [t["got_signed"] for t in out["trials"]] == [-40.0, -40.0] and any("yaw change -40.0" in x for x in lines)
