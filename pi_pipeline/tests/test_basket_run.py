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


def test_the_arm_lift_after_the_lob_is_read_from_the_script_and_the_throw_is_never_cut_short():
    assert br.lob_end_lift() == 125.0                                                                         # the lob's last frame: the arm stays up at the throw's lift
    import inspect
    assert "--watch" not in inspect.getsource(br.RealEnv.throw)                                                # the throw is watched for its full default length: nothing is written to the board while the lob still plays (2026-11-23: a 2.3 s watch cut the release off)


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


def test_a_failed_picture_after_the_throw_is_never_a_make_and_no_picture_is_taken_before_the_attention_pose():
    env = Env([ok()], puck_after=[None])
    env.picture_ok = False
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "no_picture" and r["attempts"][0]["after"]["code"] == "no_picture"            # not counted as a make
    import inspect
    assert "GripLooker" not in inspect.getsource(br.main) and "snapshot()" not in inspect.getsource(br.main)   # no warm-up picture, no check picture at the start
    opened = []

    class Cam:
        def open_port(self):
            opened.append(1)
            return True

        def close(self):
            pass

        def snapshot(self):
            raise AssertionError("no picture before the attention pose")

    h = br.CameraHolder(Cam())
    assert h.open_port() is True and opened == [1] and h._ready.is_set()


def test_there_is_no_picture_between_the_pickup_and_the_throw():
    import inspect
    src = inspect.getsource(br.RealEnv.throw)
    assert '"--grip-look"' not in src and "--pick" in src                                                    # the owner's sequence: pickup, throw, nothing in between


def test_the_lob_end_pose_is_not_a_sag_for_a_short_while_after_a_lob_only():
    from pi_pipeline.behavior import ball_chase as chase
    t = [100.0]
    r = chase.SerialRobot.__new__(chase.SerialRobot)
    r._clock = lambda: t[0]
    r.lob_end_until = float("-inf")
    assert r._lob_end_pose((-28.0, -2.0)) is False
    r.expect_lob_end()
    assert r._lob_end_pose((-28.0, -2.0)) is True
    assert r._lob_end_pose((-28.0, 14.0)) is False and r._lob_end_pose((-10.0, 0.0)) is False and r._lob_end_pose(None) is False
    t[0] += chase.LOB_END_S + 1
    assert r._lob_end_pose((-28.0, -2.0)) is False


def test_the_camera_is_warmed_up_with_two_silent_pictures_before_anything_moves():
    class Cam:
        def __init__(self, answers):
            self.answers, self._click, self.clicks_during = list(answers), True, []

        def snapshot(self):
            self.clicks_during.append(self._click)
            return self.answers.pop(0) if self.answers else None

    ok_cam = Cam([None, b"j", b"j"])
    h = br.CameraHolder(ok_cam)
    assert h.warm_up(say=lambda s: None) is True and ok_cam.clicks_during == [False, False, False] and ok_cam._click is True        # silent warm-up, click restored
    dead = Cam([])
    assert br.CameraHolder(dead).warm_up(tries=1, say=lambda s: None) is False and dead._click is True                             # a dead camera: the run does not start
    import inspect
    assert "warm_up" in inspect.getsource(br.main)


def test_after_the_throw_he_does_the_ball_goals_own_claw_look_and_the_readings_are_merged(monkeypatch):
    from pi_pipeline.behavior import ball_chase as chase
    from pi_pipeline.behavior import claw_survey
    from pi_pipeline.vision import basket_finder as bf
    from pi_pipeline.vision import puck_finder as pf
    order = []
    shown = []
    monkeypatch.setattr(bf, "find_basket", lambda j: bf.BasketReading(120.0, 110.0, 36, 28, 1.0, 18.0, 16.0, False))
    monkeypatch.setattr(pf, "find_puck", lambda j, b=None, by="row": pf.PuckReading(120.0, 130.0, 14, 14, 150, 5.0, 14.0) if j == b"left" else None)

    def fake_look(link, snapshot, kind, robot=None, **k):
        order.append(("look", kind, robot is not None))
        for label in ("look_left", "look_right", "centre"):
            snapshot(label)
        return "ok"
    monkeypatch.setattr(claw_survey, "run_claw_look", fake_look)

    class Cam:
        def __init__(self):
            self.n = 0

        def look(self):
            self.n += 1
            return [b"left", b"right", b"centre"][self.n - 1]

    class Robot:
        last_fall = None

        def expect_lob_end(self):
            order.append("expect_lob_end")

    env = br.RealEnv.__new__(br.RealEnv)
    env.robot, env.link, env._cam, env.show_picture, env.attempt = Robot(), object(), Cam(), False, 1
    basket, puck = env.after_throw()
    assert order == ["expect_lob_end", ("look", "centre", True)]                                         # the lob's end pose is announced, then the ball goal's own look
    assert env.picture_ok is True and basket.claw_in == 16.0 and abs(basket.bearing_deg - 1.0) < 1e-9     # the centre picture's basket first
    assert puck is not None and puck.claw_in == 14.0 and puck.bearing_deg != 5.0                           # the puck seen in the left picture, in the body frame
    import inspect
    src = inspect.getsource(br.RealEnv.after_throw).split('"""')[2]                                        # the code, not the docstring
    assert "claw_pose(" not in src and "sit_down" not in src and "ensure_rest" not in src and "_tx(" not in src       # nothing of my own: no claw steps, no entry, no rest, no raw writes


def test_a_look_that_returns_no_centre_picture_is_a_failed_picture(monkeypatch):
    from pi_pipeline.behavior import claw_survey
    monkeypatch.setattr(claw_survey, "run_claw_look", lambda link, snapshot, kind, robot=None, **k: "ok")

    class Robot:
        last_fall = None

        def expect_lob_end(self):
            pass

    env = br.RealEnv.__new__(br.RealEnv)
    env.robot, env.link, env._cam, env.show_picture, env.attempt = Robot(), object(), object(), False, 1
    basket, puck = env.after_throw()
    assert env.picture_ok is False and basket is None and puck is None                                       # no picture: the run stops as no_picture, never counted as a make



def test_a_make_lies_down_at_once_and_a_miss_starts_the_retrieval_from_the_looks_own_reading():
    lies, looks = [], []

    class E(Env):
        def lie_down(self):
            lies.append(1)

        def look(self):
            looks.append(1)
            return super().look()

    env = E([ok()], puck_after=[None])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made" and lies == [1]                                                           # lie-down straight after the decision, before anything else
    lies.clear()
    looks.clear()
    env = E([ok(), ok()], puck_after=[(24.0, 25.0), None])
    br.run_sequence(env, say=lambda s: None)
    kinds = [m[0] for m in env.w.moves]
    assert kinds and kinds[0] in ("pivot", "nudge", "forward") and len(lies) == 1                           # the retrieval began moving at once, and only the final make lay him down
    first_look_index = len(looks)
    assert first_look_index >= 1
    got = []
    st = {"calls": 0}

    class E2(Env):
        def look(self):
            st["calls"] += 1
            return super().look()

    e2 = E2([ok()], puck_after=[(6.0, 0.0)])
    e2.w.puck = (6.0, 0.0)
    br.retrieve(e2, say=lambda s: None, first=(None, P(6.0, 0.0)))
    assert st["calls"] >= 1 and e2.w.moves[0][0] in ("forward",)                                            # the supplied first reading decided the first move; no look came before it
    assert got == []
