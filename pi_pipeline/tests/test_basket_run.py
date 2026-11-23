"""The full basket sequence (behavior/basket_run.py) on a simulated floor: the retrieval decisions, the classification after a throw, and the attempts loop with a fake robot, camera and throw."""
from pi_pipeline.behavior import basket_lineup as bl
from pi_pipeline.behavior import basket_run as br
from pi_pipeline.goals import basket_outcome as bo


class P:                                  # a puck reading
    def __init__(self, d, b, w=14, h=14):
        self.claw_in, self.bearing_deg, self.x, self.y, self.width_px, self.height_px, self.area, self.touches_edge = d, b, 120.0 + 2.4 * b, 150.0, w, h, w * h, False


class B(P):                               # a basket reading
    def __init__(self, d, b, x=120.0, y=110.0):
        super().__init__(d, b, 36, 28)
        self.x, self.y = x, y


def act(puck, basket=None, st=None):
    return br.next_retrieval_action(puck, basket, st or br.RState())


def test_the_retrieval_decisions():
    assert act(None).kind == "scan"
    st = br.RState()
    kinds = [br.next_retrieval_action(None, None, st).kind for _ in range(16)]
    assert kinds[:14] == ["scan"] * 14 and kinds[14] == "give_up"                                  # 14 x 27 degrees covers a full circle
    assert act(P(20.0, 40.0)).kind == "pivot" and act(P(20.0, -40.0)).value < 0
    a = act(P(20.0, 10.0))
    assert a.kind == "nudge" and a.value == 10.0
    a = act(P(20.0, 2.0))
    assert a.kind == "forward" and a.value == br.APPROACH_STEP_MAX_IN                                 # a long way: the step cap
    a = act(P(11.0, 2.0))
    assert a.kind == "forward" and abs(a.value - (11.0 - br.PICK_STAND_IN)) < 1e-9
    a = act(P(6.5, 1.0))
    assert a.kind == "pick" and abs(a.value - (6.5 - br.PICK_UNDERSHOOT_IN)) < 1e-9                   # the last walk stops short of the finder's distance
    assert act(P(0.2, 0.0)).value == 0.0
    assert act(P(20.0, 0.0), B(7.0, 0.0)).value == 0.0 and act(P(20.0, 0.0), B(7.0, 0.0)).why == "too_near_the_basket"     # never walks on toward a basket inside the buffer
    st = br.RState(steps=br.MAX_RETRIEVAL_STEPS)
    assert act(P(20.0, 0.0), None, st).why == "could_not_reach_puck"


def test_the_throw_is_classified_from_the_look_afterwards():
    basket = B(16.0, 0.0)
    assert br.classify_after(basket, None)[0] == bo.NOT_SEEN                                         # nothing seen: a make or a lost puck
    assert br.classify_after(basket, P(18.0, 20.0))[0] == bo.MISSED                                  # on the floor outside the basket
    inside = P(16.0, 0.0, 6, 6)
    inside.x, inside.y = basket.x, basket.y
    assert br.classify_after(basket, inside)[0] == bo.MADE
    assert br.classify_after(None, P(10.0, 5.0))[0] == bo.MISSED                                     # a puck on the floor and no basket in view is still a miss
    assert br.classify_after(None, None)[0] == bo.NO_BASKET


class World:
    """One puck on the floor and one basket, seen from G2 (distances from the claw tip, bearings to the right)."""

    def __init__(self, puck=None, basket=(16.0, 0.0)):
        self.puck, self.basket = puck, basket
        self.moves = []

    def mover_call(self, kind, v):
        self.moves.append((kind, round(v, 1)))
        if kind == "forward" and self.puck:
            self.puck = (max(0.0, self.puck[0] - v), self.puck[1])
            self.basket = (self.basket[0] + v * 0.0, self.basket[1])
        if kind in ("pivot", "nudge", "scan") and self.puck:
            self.puck = (self.puck[0], self.puck[1] - v)
        if kind == "back":
            self.basket = (self.basket[0] + v, self.basket[1])
        return "ok"


class Mover:
    def __init__(self, w):
        self.w = w
        for k in ("scan", "pivot", "nudge", "forward", "back"):
            setattr(self, k, (lambda kind: lambda v: self.w.mover_call(kind, v))(k))


class Env:
    def __init__(self, throws, puck_after=None, pick_works=True, fell_in_look=False, battery=True, basket_start=(16.0, 0.0)):
        self.w = World(None, basket_start)
        self.mover = Mover(self.w)
        self.throws, self.puck_after, self.pick_works, self.fell_in_look, self.battery, self.thrown = list(throws), list(puck_after or []), pick_works, fell_in_look, battery, []
        self.picks = 0

    def battery_ok(self):
        return self.battery

    def throw(self, holding):
        self.thrown.append(holding)
        t = self.throws.pop(0)
        self.w.puck = self.puck_after.pop(0) if t.get("ok") and self.puck_after else None
        return t

    def after_throw(self):
        return self.look()

    def look(self):
        from pi_pipeline.behavior.basket_run import Fell
        if self.fell_in_look:
            raise Fell()
        basket = B(*self.w.basket) if self.w.basket else None
        puck = P(*self.w.puck) if self.w.puck else None
        return basket, puck

    def quick_basket(self):
        return B(*self.w.basket) if self.w.basket else None

    def pick(self):
        self.picks += 1
        if self.pick_works:
            self.w.puck = None
        return "ok"


def ok(**k):
    return {"ok": True, **k}


def test_a_throw_that_is_not_seen_afterwards_counts_as_a_make_and_stops_for_the_owners_reset():
    env = Env([ok()], puck_after=[None])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made" and len(r["attempts"]) == 1 and env.thrown == [False]


def test_a_miss_is_searched_picked_up_lined_up_and_thrown_again_without_a_pick_up():
    env = Env([ok(), ok()], puck_after=[(24.0, 25.0), None])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made" and len(r["attempts"]) == 2
    assert env.thrown == [False, True]                                                           # the second throw is from a puck already held
    a1 = r["attempts"][0]
    assert a1["after"]["code"] == bo.MISSED and a1["retrieval"]["outcome"] == "retrieved" and a1["lineup"]["outcome"] == "aligned"
    kinds = [m[0] for m in env.w.moves]
    assert "pivot" in kinds and "forward" in kinds and env.picks == 1
    assert abs(env.w.basket[0] - bl.TARGET_IN) <= bl.DIST_TOL_IN                                 # ends lined up at the shot distance


def test_the_stops():
    assert br.run_sequence(Env([ok()], battery=False), say=lambda s: None)["outcome"] == "battery"
    assert br.run_sequence(Env([{"ok": True, "fell": True}]), say=lambda s: None)["outcome"] == "fell"
    assert br.run_sequence(Env([{"ok": False}]), say=lambda s: None)["outcome"] == "throw_failed"
    assert br.run_sequence(Env([ok()], fell_in_look=True), say=lambda s: None)["outcome"] == "fell"
    r = br.run_sequence(Env([ok()], puck_after=[(24.0, 0.0)], pick_works=False), say=lambda s: None)
    assert r["outcome"] == "pick_failed" and r["attempts"][0]["retrieval"]["steps"][-1]["why"] == "puck still on the floor"
    r = br.run_sequence(Env([ok(), ok(), ok()], puck_after=[(24.0, 0.0)] * 3), max_attempts=2, say=lambda s: None)
    assert r["outcome"] == "max_attempts" and len(r["attempts"]) == 2
    r = br.run_sequence(Env([ok()], puck_after=[(20.0, 0.0)], basket_start=(6.0, 0.0)), say=lambda s: None)
    assert r["outcome"] == "too_near_the_basket"                                                  # a puck lying in front of a basket that close is not walked to


def test_a_fall_in_a_mover_ends_the_retrieval():
    env = Env([ok()], puck_after=[(24.0, 0.0)])
    env.mover.forward = lambda v: "fell"
    assert br.run_sequence(env, say=lambda s: None)["outcome"] == "fell"


def test_the_looks_are_merged_into_one_body_frame_reading():
    from pi_pipeline.vision import basket_finder as bf, puck_finder as pf
    puck = lambda d, b: pf.PuckReading(120.0, 130.0, 14, 14, 150, b, d)                                       # noqa: E731
    basket = lambda d, b: bf.BasketReading(120.0, 110.0, 36, 28, b, d + 2, d, False)                          # noqa: E731
    offsets = {"look_left": -35.0, "look_right": 35.0, "centre": 0.0}
    seen = {"look_left": (None, puck(14.0, 5.0)), "look_right": (basket(30.0, -4.0), None), "centre": (basket(18.0, 1.0), puck(20.0, 2.0))}
    b, p = br.merge_looks(seen, offsets)
    assert b.claw_in == 18.0 and b.bearing_deg == 1.0                                                         # the centre picture's basket first
    assert p.claw_in == 14.0 and p.bearing_deg == -30.0                                                       # the nearest puck, in the body frame: 5 degrees right of a picture pointing 35 left
    assert br.merge_looks({}, offsets) == (None, None)
    b, p = br.merge_looks({"look_right": (basket(30.0, -4.0), None)}, offsets)
    assert b.bearing_deg == 31.0 and p is None


def test_the_burst_recorder_keeps_frames_in_memory_only_and_builds_a_sheet(tmp_path, monkeypatch):
    import io

    from PIL import Image

    def jpeg(c):
        out = io.BytesIO()
        Image.new("RGB", (240, 240), c).save(out, "JPEG")
        return out.getvalue()

    class Cam:
        def grab_burst(self, seconds):
            return [(10.00, 10.20, jpeg((200, 0, 0))), (10.25, 10.45, jpeg((0, 200, 0))), (10.50, 10.70, jpeg((0, 0, 200)))]

    monkeypatch.chdir(tmp_path)
    rec = br.BurstRecorder(Cam(), seconds=1.0)
    rec.start(t_send=10.0)
    frames = rec.join()
    assert [round(f[1], 2) for f in frames] == [0.20, 0.45, 0.70] and len(rec.last_frames) == 3
    assert list(tmp_path.rglob("*")) == []                                                                 # nothing is written to disk
    png = rec.sheet_png()
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"

    class Broken:
        def grab_burst(self, seconds):
            raise RuntimeError("no camera")

    bad = br.BurstRecorder(Broken())
    bad.start(t_send=0.0)
    assert bad.join() == [] and bad.sheet_png() is None                                                   # a failure here never stops a throw


def test_the_camera_burst_returns_back_to_back_frames_without_exposure_work():
    from pi_pipeline.vision.snapshot import CameraSnapshotter, Snapshot
    t = [0.0]
    cam = CameraSnapshotter("/dev/null", clock=lambda: t[0], sleep=lambda s: None)
    cam._open = lambda: None

    def grab():
        t[0] += 0.25
        return Snapshot(b"jpeg%d" % int(t[0] * 100), 240, 240)
    cam._grab_one = grab
    frames = cam.grab_burst(1.0)
    assert 3 <= len(frames) <= 5 and all(f[2].startswith(b"jpeg") and f[1] >= f[0] for f in frames)
    assert cam.grab_burst(1.0, max_frames=2).__len__() == 2
    cam._open = lambda: (_ for _ in ()).throw(OSError("no port"))
    assert cam.grab_burst(1.0) == []                                                                 # never raises


def test_a_basket_cut_off_by_the_frame_is_too_near_to_walk_toward():
    near = B(30.0, 0.0)
    near.touches_edge = True
    assert act(P(20.0, 0.0), near).why == "too_near_the_basket"


def test_the_save_hook_sees_the_run_as_it_goes_and_a_retrieval_step_is_saved_when_taken():
    seen = []
    env = Env([ok(), ok()], puck_after=[(24.0, 25.0), None])
    br.run_sequence(env, say=lambda s: None, save=lambda r: seen.append(([a.get("retrieval", {}).get("outcome") for a in r["attempts"]], r["outcome"])))
    assert seen and seen[-1][1] == "running"                                                                  # (the final outcome is the return value)
    assert any(o and o[0] == "running" for o, _ in seen)                                                      # a retrieval step was saved while it was still running
    assert any(o and o[0] == "retrieved" for o, _ in seen)


def test_the_lob_end_pose_is_not_a_sag_for_a_short_while_after_a_lob_only():
    from pi_pipeline.behavior import ball_chase as chase
    t = [100.0]
    r = chase.SerialRobot.__new__(chase.SerialRobot)
    r._clock = lambda: t[0]
    r.lob_end_until = float("-inf")
    assert r._lob_end_pose((-28.0, -2.0)) is False                                                            # no lob: the gate applies as always
    r.expect_lob_end()
    assert r._lob_end_pose((-28.0, -2.0)) is True
    assert r._lob_end_pose((-28.0, 14.0)) is False                                                            # rolled past the gate: still a sag
    assert r._lob_end_pose((-10.0, 0.0)) is False and r._lob_end_pose((30.0, 0.0)) is False                  # a different pitch is not the lob's pose
    assert r._lob_end_pose(None) is False
    t[0] += chase.LOB_END_S + 1
    assert r._lob_end_pose((-28.0, -2.0)) is False                                                            # and it runs out


def test_the_retrieval_never_stands_straight_up_from_the_attention_pose():
    class Robot:
        def __init__(self):
            self.posture, self.calls = "attention", []

        def rest_then_stand(self):
            self.calls.append("rest_then_stand")
            self.posture = "stand"
            return "ok"

        def stand_up(self):
            self.calls.append("stand_up")
            return "ok"

        def stand_up_from_attention(self):
            self.calls.append("stand_up_from_attention")
            return "ok"

    r = Robot()
    env = br.RealEnv.__new__(br.RealEnv)
    env.robot = r
    env._ready_to_move()
    assert r.calls == ["rest_then_stand"]                                                                 # claw down, rest, then the eased stand-up from rest
    env._ready_to_move()
    assert r.calls == ["rest_then_stand"]                                                                 # standing already: nothing

    class Falls(Robot):
        def rest_then_stand(self):
            return "fell"

    env.robot = Falls()
    try:
        env._ready_to_move()
        raise AssertionError("a fall must stop the run")
    except br.Fell:
        pass


def test_the_arm_lift_after_the_lob_is_read_from_the_script_and_the_watch_is_short():
    assert br.lob_end_lift() == 125.0                                                                         # the lob's last frame: the arm stays up at the throw's lift
    assert br.THROW_WATCH_S < 3.0                                                                              # the attention pose follows the animation, not the long default watch


def test_the_attention_pose_is_sent_at_once_with_no_read_and_no_arm_move():
    sent = []

    class Robot:
        posture = "stand"
        _claw = (0.0, 0.0)

        def __init__(self):
            self._pitch = self._roll = None

        def _clock(self):
            return 5.0

        def expect_lob_end(self):
            sent.append("expect")

        def _tx(self, c):
            sent.append(c)

        def claw_pose(self, *a):
            sent.append("claw_pose")

        def sit_down(self):
            sent.append("sit_down")

    env = br.RealEnv.__new__(br.RealEnv)
    env.robot = Robot()
    env._attention_now()
    assert sent == ["expect", "gP", "kcalib"]                                                              # the pose and nothing else: no tilt read, no settle sleep, no claw move over the playing skill
    assert env.robot.posture == "attention" and env.robot._claw == (0.0, 125.0)


def test_after_the_throw_one_attention_picture_is_taken_when_the_pose_ends_then_the_standard_lie_down_at_once_with_no_claw_move(monkeypatch):
    from pi_pipeline.behavior import ball_chase as chase
    from pi_pipeline.vision import basket_finder as bf
    from pi_pipeline.vision import puck_finder as pf
    order = []
    monkeypatch.setattr(br.time, "sleep", lambda s: order.append("sleep"))
    monkeypatch.setattr(chase, "ensure_rest", lambda link: order.append("confirm_rest"))
    monkeypatch.setattr(bf, "find_basket", lambda j: B(16.0, 0.0))
    monkeypatch.setattr(pf, "find_puck", lambda j, b=None, by="row": P(12.0, 3.0))

    class Cam:
        def refresh_exposure(self):
            order.append("meter")

        def look(self):
            order.append("picture")
            return b"jpeg"

    class Link:
        def __init__(self):
            self.polls = [[], [], ["K"], ["calib"]]

        def pop_other(self):
            order.append("poll")
            return self.polls.pop(0) if self.polls else []

    class Robot:
        posture = "attention"
        _claw = (0.0, 125.0)

        def _tx(self, c):
            order.append(c)

        def claw_pose(self, *a):
            order.append("claw_pose")

    env = br.RealEnv.__new__(br.RealEnv)
    env.robot, env.link, env._cam, env.show_picture, env.attempt = Robot(), Link(), Cam(), False, 1
    basket, puck = env.after_throw()
    assert "claw_pose" not in order and "j" not in order                                                    # the claw is not moved and nothing is read first
    assert order.index("picture") < order.index("confirm_rest")                                              # picture, then the standard lie-down at once
    assert order.count("poll") == 4 and order.index("meter") > max(i for i, o in enumerate(order) if o == "poll")      # it waited for the pose's end echo before the picture
    assert env.robot.posture == "rest" and env.robot._claw == (0.0, 0.0) and basket.claw_in == 16.0 and puck.claw_in == 12.0


def test_he_stands_up_again_from_rest_only_when_a_look_is_needed():
    calls = []

    class Robot:
        posture = "rest"

        def stand_up_from_rest(self):
            calls.append("stand_up_from_rest")
            self.posture = "stand"
            return "ok"

        def stand_up(self):
            calls.append("stand_up")
            return "ok"

        def rest_then_stand(self):
            calls.append("rest_then_stand")
            return "ok"

    env = br.RealEnv.__new__(br.RealEnv)
    env.robot = Robot()
    env._ready_to_move()
    assert calls == ["stand_up_from_rest"]                                                                 # the eased stand-up from rest, never from the attention pose
    env._ready_to_move()
    assert calls == ["stand_up_from_rest"]
