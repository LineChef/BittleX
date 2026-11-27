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
    a = act(P(14.0, 2.0))
    assert a.kind == "forward" and abs(a.value - (14.0 - br.FORWARD_LEAVES_IN)) < 1e-9
    a = act(P(8.5, 2.0))
    assert a.kind == "pick" and abs(a.value - (8.5 - br.PICK_UNDERSHOOT_IN)) < 1e-9                  # inside the band (4.5 to 11): the last walk
    for d in (4.6, 5.3, 6.0, 10.9):                                                                  # the band is 4.5 to 11 inches (2026-11-27: a 3 inch band made him back, turn, walk and back again for 50 steps)
        a = act(P(d, 1.4))
        assert a.kind == "pick" and abs(a.value - (d - br.PICK_UNDERSHOOT_IN)) < 1e-9
    a = act(P(4.2, 1.4))
    assert a.kind == "back" and abs(a.value - (br.PICK_STAND_IN - 4.2)) < 1e-9                        # the 2026-11-25 pick-up: 5.3 inches is too near for a walk that moves about 8: back up first
    assert act(P(0.2, 0.0)).value == 0.0
    assert act(P(20.0, 0.0), B(7.0, 0.0)).kind == "forward"                                          # a tub close beside him never ends the retrieval (owner, 2026-11-27): the walk goes on
    c = P(7.9, 0.4)
    c.clipped = True
    a = act(c)
    assert a.kind == "pick" and a.value == br.BLIND_STEP_IN                                          # a puck at the claw tip: the finder's distance is not used
    assert act(c.__class__(7.9, 12.0)).kind == "nudge"                                               # but a puck off to one side is still turned onto first
    st = br.RState(scans=br.MAX_SCANS - 1)
    assert act(None, None, st).kind == "scan" and act(None, None, st).why == "puck_not_found"        # scans have their own cap and use no walking steps
    st = br.RState()
    for _ in range(10):
        assert act(None, None, st).kind == "scan"
    assert st.steps == 0
    st = br.RState(steps=br.MAX_RETRIEVAL_STEPS)
    assert act(P(20.0, 0.0), None, st).why == "could_not_reach_puck"


def test_the_throw_is_classified_from_the_look_afterwards():
    basket = B(16.0, 0.0)
    assert br.classify_after(basket, None)[0] == bo.NOT_SEEN                                         # nothing seen: a make or a lost puck
    assert br.classify_after(basket, P(18.0, 20.0))[0] == bo.MISSED                                  # on the floor outside the basket
    inside = P(16.0, 0.0, 6, 6)
    inside.x, inside.y = basket.x, basket.y
    assert br.classify_after(basket, inside)[0] == bo.MISSED                                         # a puck that is seen is on the floor: the basket is opaque, so one inside it is never seen
    assert br.classify_after(None, P(10.0, 5.0))[0] == bo.MISSED                                     # a puck on the floor and no basket in view is still a miss
    assert br.classify_after(None, None)[0] == bo.NO_BASKET


class World:
    """One puck on the floor and one basket, seen from G2 (distances from the claw tip, bearings to the right)."""

    def __init__(self, puck=None, basket=(16.0, 0.0)):
        self.puck, self.basket = puck, basket
        self.moves = []
        self.inside = False                 # the puck is in the tub (the confirm look sees it)
        self.hidden = None                  # the puck is behind the tub, seen only after `reveal_legs` circling legs
        self.reveal_legs, self.legs = 3, 0
        self.walkup = False                 # between the after-throw look and the confirm look a forward walk brings him nearer to the tub

    def mover_call(self, kind, v):
        self.moves.append((kind, round(v, 1)))
        if kind == "arc":
            self.legs += 1
        elif kind == "forward" and self.walkup and self.basket is not None:
            self.basket = (max(0.0, self.basket[0] - v), self.basket[1])
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
        for k in ("scan", "pivot", "nudge", "forward", "back", "arc"):
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
        p = self.puck_after.pop(0) if t.get("ok") and self.puck_after else None
        self.w.inside, self.w.hidden = p == "in", (14.0, 20.0) if p == "behind" else None
        self.w.puck = None if p in ("in", "behind") else p
        return t

    def after_throw(self):
        basket, puck = self.look()
        self.w.walkup = puck is None                                                                        # the confirm look follows
        return basket, puck

    def look(self):
        from pi_pipeline.behavior.basket_run import Fell
        if self.fell_in_look:
            raise Fell()
        basket = B(*self.w.basket) if self.w.basket else None
        puck = P(*self.w.puck) if self.w.puck else None
        if puck is None and self.w.hidden and self.w.legs >= self.w.reveal_legs:
            self.w.puck, self.w.hidden = self.w.hidden, None                                                   # seen from this side now: an ordinary puck on the floor
            puck = P(*self.w.puck)
        return basket, puck

    def confirm_look(self):
        from types import SimpleNamespace
        self.claw_up_looks = getattr(self, "claw_up_looks", 0) + 1
        self.confirm_looks = getattr(self, "confirm_looks", 0) + 1
        self.w.walkup = False
        basket = B(*self.w.basket) if self.w.basket else None
        floor = P(*self.w.puck) if self.w.puck else None
        return basket, floor, SimpleNamespace(x=120.0, y=116.0, count=30) if self.w.inside else None

    @property
    def quick_count(self):
        return getattr(self, "quick_calls", 0)

    def quick_basket(self):
        self.quick_calls = getattr(self, "quick_calls", 0) + 1
        return B(*self.w.basket) if self.w.basket else None

    def quick_confirm(self):
        """The reading of the picture just taken at the end of the walk-up."""
        from types import SimpleNamespace
        self.confirm_looks = getattr(self, "confirm_looks", 0) + 1
        self.w.walkup = False
        self.last_quick = True
        basket = B(*self.w.basket) if self.w.basket else None
        floor = P(*self.w.puck) if self.w.puck else None
        return basket, floor, SimpleNamespace(x=120.0, y=116.0, count=30) if self.w.inside else None

    def pick(self):
        self.picks += 1
        if self.pick_works:
            self.w.puck = None
        return "ok"


def ok(**k):
    return {"ok": True, **k}


def test_a_throw_not_seen_from_sixteen_inches_is_confirmed_from_close_up_and_a_puck_inside_is_a_make():
    env = Env([ok()], puck_after=["in"])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made" and len(r["attempts"]) == 1 and env.thrown == [False]
    a = r["attempts"][0]
    assert env.confirm_looks == 1 and a["after"]["code"] == bo.MADE and a["after"]["first_look"]["code"] == bo.NOT_SEEN
    assert abs(env.w.basket[0] - bl.CONFIRM_READING_IN) <= bl.CONFIRM_TOL_IN                         # he walked up to about 8 inches (the finder reads 9.8) before the look
    assert a["confirm"]["walkup"]["outcome"] == "aligned" and a["confirm"]["look"]["tub_puck"] is not None
    assert env.quick_calls == 1 and a["confirm"]["standing_s"] >= 0                                  # the first decision used the after-throw look's reading: only the check after the walk took a picture


def test_a_puck_seen_outside_is_a_miss_with_no_walk_up_and_goes_straight_to_the_pick_up():
    env = Env([ok(), ok()], puck_after=[(24.0, 25.0), "in"])
    r = br.run_sequence(env, say=lambda s: None)
    a = r["attempts"][0]
    assert a["after"]["code"] == bo.MISSED and "confirm" not in a                                           # a puck on the floor is already a certain miss (owner, 2026-11-24)
    assert a["retrieval"]["outcome"] == "retrieved" and env.picks == 1 and env.confirm_looks == 1             # the only confirm look is the second throw's


def test_nothing_inside_is_a_miss_and_he_circles_the_tub_until_he_sees_the_puck_then_fetches_it():
    env = Env([ok(), ok()], puck_after=["behind", "in"])
    r = br.run_sequence(env, say=lambda s: None)
    a = r["attempts"][0]
    assert a["after"]["code"] == bo.MISSED and a["circle"]["outcome"] == "found" and a["retrieval"]["outcome"] == "retrieved"
    assert any(s["action"] == "arc" and s["value"] == br.CIRCLE_ARC_DEG for s in a["circle"]["steps"])
    assert r["outcome"] == "made" and env.thrown == [False, True]                                          # then lined up and threw again without a pick-up


def test_two_laps_without_the_puck_end_the_session_at_rest():
    class E(Env):
        lies = 0

        def lie_down(self):
            E.lies += 1
    env = E([ok()], puck_after=[None])                                                                      # in no picture: not inside, not on the floor, not behind
    r = br.run_sequence(env, say=lambda s: None)
    a = r["attempts"][0]
    assert r["outcome"] == "circled_twice" and a["circle"]["outcome"] == "circled_twice" and E.lies == 1
    arcs = [s for s in a["circle"]["steps"] if s["action"] == "arc"]
    assert len(arcs) == 16 and a["circle"]["steps"][-1]["angle_deg"] >= 720                                  # two laps are 16 arcs of 45 degrees


def test_no_tub_after_the_throw_makes_him_walk_forward_in_short_bursts_and_look_until_he_sees_it():
    """Owner, 2026-11-25: the tub is always right in front of him at the start; if the look does not read it he walks forward a burst at a time, looking after each, then looks into it."""
    env = Env([ok()], puck_after=["in"])
    env.w.basket = None                                                                                     # not in view at the after-throw look
    forwards = []
    real = env.mover.forward

    def forward(v):
        forwards.append(v)
        if len(forwards) == 2:
            env.w.basket, env.w.walkup = (14.0, 0.0), True                                                   # in view after the second burst
        return real(v)
    env.mover.forward = forward
    r = br.run_sequence(env, say=lambda s: None)
    a = r["attempts"][0]
    assert r["outcome"] == "made" and a["after"]["tub_found_after_bursts"] == 2 and forwards[:2] == [br.BLIND_BURST_IN] * 2     # two bursts, then the confirm look read the puck inside
    env = Env([ok()], puck_after=["in"])
    env.w.basket = None                                                                                     # never seen: BLIND_BURSTS walks, then he gives up at rest
    n = []
    env.mover.forward = lambda v: (n.append(v), "ok")[1]
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "no_basket" and len(n) == br.BLIND_BURSTS and r["attempts"][0]["after"]["tub_found_after_bursts"] is None
    env = Env([ok()], puck_after=["in"])
    env.w.basket = None
    env.mover.forward = lambda v: "fell"
    assert br.run_sequence(env, say=lambda s: None)["outcome"] == "fell"


def test_the_confirm_walk_up_failing_or_the_tub_lost_ends_the_attempt_without_a_make():
    env = Env([ok()], puck_after=["in"])
    env.w.basket = None                                                                                     # the tub is out of view and never found
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "no_basket"                                                                      # the first look cannot see the tub: no confirm, never a make
    env = Env([ok()], puck_after=["in"])
    env.mover.forward = lambda v: "fell"
    assert br.run_sequence(env, say=lambda s: None)["outcome"] == "fell"


def test_a_miss_is_searched_picked_up_lined_up_and_thrown_again_without_a_pick_up():
    env = Env([ok(), ok()], puck_after=[(24.0, 25.0), "in"])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made" and len(r["attempts"]) == 2
    assert env.thrown == [False, True]                                                           # the second throw is from a puck already held
    a1 = r["attempts"][0]
    assert a1["after"]["code"] == bo.MISSED and a1["retrieval"]["outcome"] == "retrieved" and a1["lineup"]["outcome"] == "aligned"
    kinds = [m[0] for m in env.w.moves]
    assert "pivot" in kinds and "forward" in kinds and env.picks == 1
    assert abs(a1["lineup"]["steps"][-1]["claw_in"] - bl.TARGET_IN) <= bl.DIST_TOL_IN               # the line-up ended at the shot distance


def test_the_stops():
    assert br.run_sequence(Env([ok()], battery=False), say=lambda s: None)["outcome"] == "battery"
    assert br.run_sequence(Env([{"ok": True, "fell": True}]), say=lambda s: None)["outcome"] == "fell"
    assert br.run_sequence(Env([{"ok": False}]), say=lambda s: None)["outcome"] == "throw_failed"
    assert br.run_sequence(Env([ok()], fell_in_look=True), say=lambda s: None)["outcome"] == "fell"
    r = br.run_sequence(Env([ok()], puck_after=[(24.0, 0.0)], pick_works=False), say=lambda s: None)
    assert r["outcome"] == "pick_failed" and r["attempts"][0]["retrieval"]["steps"][-1]["why"] == "puck still on the floor"
    r = br.run_sequence(Env([ok(), ok(), ok()], puck_after=[(24.0, 0.0)] * 3), max_attempts=2, say=lambda s: None)
    assert r["outcome"] == "max_attempts" and len(r["attempts"]) == 2
    r = br.run_sequence(Env([ok()], puck_after=[(20.0, 0.0)], basket_start=(6.0, 0.0)), max_attempts=1, say=lambda s: None)
    assert r["outcome"] == "max_attempts" and r["attempts"][0]["retrieval"]["steps"][0]["action"] != "give_up"     # a puck in front of a tub that close is still walked to and picked up (owner, 2026-11-27)


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
    assert p.claw_in == 20.0 and p.bearing_deg == 2.0                                                         # the centre picture's puck wins (the side pictures only say which side), its own bearing
    b, p = br.merge_looks({"look_left": (None, puck(14.0, 5.0)), "look_right": (None, puck(18.0, -3.0)), "centre": (basket(18.0, 1.0), None)}, offsets)
    assert p.claw_in == 14.0 and p.bearing_deg == -30.0                                                       # none in the centre: the nearest side picture's, in the body frame (5 degrees right of a picture pointing 35 left)
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


def test_a_basket_cut_off_by_the_frame_never_ends_the_retrieval():
    for dist, wpx in ((11.0, 40), (30.0, 90), (17.0, 43)):
        bsk = B(dist, 0.0)
        bsk.touches_edge, bsk.width_px = True, wpx
        assert act(P(20.0, 0.0), bsk).kind == "forward"                                              # the 2026-11-27 runs ended on a tub read 11 inches off and cut by the frame, with the puck 4 to 6 inches from the claw
        assert act(P(3.6, -4.1), bsk).kind != "give_up"                                              # a puck 3.6 inches from the claw is worked on (here a back-up first), never given up on


def test_the_save_hook_sees_the_run_as_it_goes_and_a_retrieval_step_is_saved_when_taken():
    seen = []
    env = Env([ok(), ok()], puck_after=[(24.0, 25.0), "in"])
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
    assert order == ["expect_lob_end", ("look", "centre", True)]                                         # the lob's end pose is announced, then the ball goal's own look, complete (it ends standing)
    assert env.picture_ok is True and basket.claw_in == 16.0 and abs(basket.bearing_deg - 1.0) < 1e-9     # the centre picture's basket first
    assert puck is not None and puck.claw_in == 14.0 and puck.bearing_deg != 5.0                           # the puck seen in the left picture, in the body frame
    assert set(env.look_readings) == {"look_left", "look_right", "centre"} and env.look_readings["look_left"]["puck"][0] == 14.0    # what each picture read is kept for the run log
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

    env = E([ok()], puck_after=["in"])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made" and lies == [1]                                                           # lie-down straight after the decision, before anything else
    lies.clear()
    looks.clear()
    env = E([ok(), ok()], puck_after=[(24.0, 25.0), "in"])
    br.run_sequence(env, say=lambda s: None)
    kinds = [m[0] for m in env.w.moves]
    assert kinds and kinds[0] in ("pivot", "nudge", "forward") and len(lies) == 1                           # the miss did not lie down (the look ends standing), the retrieval began moving at once, and only the final make lay him down
    first_look_index = len(looks)
    assert first_look_index >= 1
    got = []
    st = {"calls": 0}

    class E2(Env):
        def look(self):
            st["calls"] += 1
            return super().look()

    e2 = E2([ok()], puck_after=[(14.0, 0.0)])
    e2.w.puck = (14.0, 0.0)
    br.retrieve(e2, say=lambda s: None, first=(None, P(14.0, 0.0)))
    assert st["calls"] >= 1 and e2.w.moves[0][0] in ("forward",)                                            # the supplied first reading decided the first move; no look came before it
    assert got == []


def test_a_make_lies_down_from_the_stand_and_a_miss_starts_walking_with_no_rest_in_between():
    events = []

    class E(Env):
        def lie_down(self):
            events.append("lie_down")

        def stand_up_from_rest(self):
            events.append("stand_up_from_rest")                                              # must never be called: the look ends standing
            return True

    r = br.run_sequence(E([ok()], puck_after=["in"]), say=lambda s: None)
    assert r["outcome"] == "made" and events == ["lie_down"]                                # a make: rest, from the stand
    events.clear()
    env = E([ok(), ok()], puck_after=[(24.0, 25.0), "in"])
    br.run_sequence(env, say=lambda s: None)
    assert events == ["lie_down"] and env.w.moves                                           # a miss: no lie-down, no stand-up, walking; only the final make lay him down
    events.clear()
    bad = E([ok()], puck_after=["in"])
    bad.picture_ok = False
    assert br.run_sequence(bad, say=lambda s: None)["outcome"] == "no_picture" and events == ["lie_down"]


def test_the_shared_claw_look_has_no_tail_option_and_still_ends_standing():
    import inspect
    from pi_pipeline.behavior import ball_chase as chase, claw_survey
    assert "tail" not in inspect.signature(chase.claw_look_sequence).parameters and "tail" not in inspect.signature(claw_survey.run_claw_look).parameters



def test_a_puck_seen_in_any_picture_is_a_miss_and_not_seen_is_a_make():
    from pi_pipeline.vision import basket_finder as bf, puck_finder as pf
    basket = bf.BasketReading(120.0, 110.0, 36, 28, 0.0, 18.0, 16.0, False)
    puck = pf.PuckReading(120.0, 110.0, 14, 14, 150, 4.0, 8.0)                                                # the same pixel position as the basket's centre, but in the right-hand picture
    offsets = {"look_right": 27.0, "centre": 0.0}
    b, p = br.merge_looks({"centre": (basket, None), "look_right": (None, puck)}, offsets)
    assert br.classify_after(b, p)[0] == bo.MISSED and p.bearing_deg == 31.0
    false_speck = pf.PuckReading(125.0, 136.0, 4, 3, 12, 2.0, 5.9)                                            # 2026-11-23: a 4 pixel false blob in the left picture, the real puck in the centre one
    real = pf.PuckReading(189.0, 124.0, 6, 6, 40, 26.2, 8.2)
    b, p = br.merge_looks({"look_left": (basket, false_speck), "centre": (basket, real)}, {"look_left": -35.0, "centre": 0.0})
    assert p.bearing_deg == 26.2 and p.claw_in == 8.2
    b, p = br.merge_looks({"centre": (basket, puck)}, offsets)
    assert br.classify_after(b, p)[0] == bo.MISSED
    b, p = br.merge_looks({"centre": (basket, None)}, offsets)
    assert br.classify_after(b, p)[0] == bo.NOT_SEEN


def test_the_scan_keeps_turning_the_way_the_last_turn_toward_the_puck_went():
    st = br.RState()
    assert act(None, None, st).value == br.SCAN_STEP_DEG                                           # nothing seen yet: to the right
    assert act(P(8.0, -33.0), None, st).kind == "pivot"                                            # a turn left toward it...
    assert act(None, None, st).kind == "back"                                                       # it drops out of view: back up and look again first (owner, 2026-11-27)
    a = act(None, None, st)
    assert a.kind == "scan" and a.value == -br.SCAN_STEP_DEG                                        # ...and still nothing: the scan goes on to the left, not back
    act(P(12.0, 14.0), None, st)
    assert act(None, None, st).kind == "back"
    assert act(None, None, st).value == br.SCAN_STEP_DEG


def test_every_look_picture_is_kept_with_what_the_finders_read(tmp_path):
    from types import SimpleNamespace as NS
    from pi_pipeline.vision import basket_finder as bf, puck_finder as pf
    tub = bf.BasketReading(124.0, 100.0, 89, 9, 1.6, 11.8, 9.8, False, 80, 168, 104.0, 128.0)
    floor = pf.PuckReading(120.0, 130.0, 14, 14, 150, 5.0, 9.0)
    inside = pf.PuckInTub(122.0, 116.0, 48, 8, 8)
    path = br.save_picture("20261124_120000", 2, "confirm", b"jpegbytes", tub, floor, inside, {"walkup_final": (9.8, 89)}, log_dir=str(tmp_path))
    assert path and open(path, "rb").read() == b"jpegbytes" and path.endswith("a02_confirm.jpg")
    import json
    line = json.loads((tmp_path / "pictures" / "20261124_120000" / "pictures.jsonl").read_text().splitlines()[0])
    assert line["label"] == "confirm" and line["attempt"] == 2 and line["tub"]["left"] == 80 and line["tub"]["base_row"] == 128.0
    assert line["floor_puck"]["claw_in"] == 9.0 and line["tub_puck"]["count"] == 48 and line["walkup_final"] == [9.8, 89]
    assert br.save_picture("x", 1, "none", b"j", None, None, None, log_dir=str(tmp_path))                      # nothing read: still kept, with nulls
    assert br.reading_dict(None) is None and br.reading_dict(NS(a=1, b="x", c=[1])) == {"a": 1, "b": "x"}
    assert br.save_picture("x", 1, "bad", b"j", log_dir="/proc/definitely/not/writable") is None               # a full or missing disk never stops a run


def test_the_walk_ups_own_last_picture_is_the_confirm_picture_and_a_make_lies_down_with_nothing_after_it():
    events = []

    class E(Env):
        def lie_down(self):
            events.append("lie_down")

        def quick_basket(self):
            events.append("picture")
            return super().quick_basket()
    env = E([ok()], puck_after=["in"])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "made" and getattr(env, "claw_up_looks", 0) == 0                                 # no attention-pose cycle: the quick picture was the confirm
    assert r["attempts"][0]["confirm"]["look"]["mode"] == "quick"
    assert events[-1] == "lie_down" and events.count("lie_down") == 1                                       # lying down is the last thing: he does not stand about with the answer


def test_the_claw_up_confirm_is_still_available_by_name():
    env = Env([ok()], puck_after=["in"])
    env.throw(False)
    env.w.walkup = True                                                                                     # the world: between the after-throw look and the confirm look
    rec = {"attempt": 1, "after": {"code": bo.NOT_SEEN}}
    res = br.confirm_throw(env, rec, say=lambda s: None, first=B(16.0, 0.0), look="claw_up")
    assert res["stop"] == "made" and env.claw_up_looks == 1 and rec["confirm"]["look"]["mode"] == "claw_up"


def test_a_camera_that_stops_answering_while_he_stands_lies_him_down_after_two_misses():
    lies, asked = [], []

    class Dead(Env):
        last_quick_failed = True

        def lie_down(self):
            lies.append(1)

        def quick_basket(self):
            asked.append(1)
            return None
    env = Dead([ok()], puck_after=["in"])
    r = br.run_sequence(env, say=lambda s: None)
    assert r["outcome"] == "no_picture" and lies == [1] and len(asked) == br.CAMERA_MISSES_MAX              # not a make, not a search: he lies down rather than stand turning on the spot
    assert r["attempts"][0]["confirm"]["walkup"]["outcome"] == "camera_stalled"


def test_every_way_an_attempt_can_stop_but_a_fall_ends_with_him_lying_down():
    lies = []

    class E(Env):
        def lie_down(self):
            lies.append(1)
    for kwargs, why in (({"puck_after": [(24.0, 0.0)], "pick_works": False}, "pick_failed"),                  # a retrieval that gave up
                        ({"puck_after": [None]}, "circled_twice")):
        lies.clear()
        r = br.run_sequence(E([ok()], **kwargs), say=lambda s: None)
        assert r["outcome"] == why and lies == [1], (why, lies)                                                  # once: never standing about with the legs sagging, never twice
    lies.clear()
    assert br.run_sequence(E([ok()], fell_in_look=True), say=lambda s: None)["outcome"] == "fell" and lies == []   # a fall is the guards' to handle: no command is sent to a fallen G2


def test_he_says_target_acquired_when_he_finds_the_puck_and_only_then():
    said = []
    env = Env([ok()], puck_after=[(14.0, 0.0)])                                                               # the puck seen on the floor right after the throw
    r = br.attempt_once(env, {"attempt": 1}, False, say=lambda s: None, announce=said.append)
    assert said and said.count("target acquired") == 1 and "target acquired" in said
    said.clear()
    env = Env([ok()], puck_after=["behind"])                                                                  # not seen: the circle finds it
    env.w.hidden = (14.0, 20.0)
    r = br.attempt_once(env, {"attempt": 1}, False, say=lambda s: None, announce=said.append)
    assert said.count("target acquired") == 1                                                                 # once, not again when the retrieval starts from that very reading
    env = Env([ok()], puck_after=[(14.0, 0.0)])
    br.attempt_once(env, {"attempt": 1}, False, say=lambda s: None)                                           # no announce given: nothing said, nothing breaks
    env = Env([ok()], puck_after=[(14.0, 0.0)])

    def boom(text):
        raise RuntimeError("no speaker")
    br.attempt_once(env, {"attempt": 1}, False, say=lambda s: None, announce=boom)                           # a speaker that fails never stops the attempt
    # a puck lost during the retrieval and found again after a scan is announced when it comes back
    said2 = []
    looks = iter([(None, None), (None, P(10.0, 0.0))])
    env = Env([ok()], puck_after=[(14.0, 0.0)])
    env.look = lambda: next(looks, (None, P(10.0, 0.0)))
    br.retrieve(env, say=lambda s: None, announce=said2.append)
    assert said2 == ["searching for the puck", "target acquired"]


def test_he_says_which_thing_he_is_searching_for_when_a_search_begins():
    said = []
    env = Env([ok()], puck_after=["behind"])                                                                  # not in the tub, not on the floor in view: the circle searches for the puck
    env.w.hidden = (14.0, 20.0)
    br.attempt_once(env, {"attempt": 1}, False, say=lambda s: None, announce=said.append)
    assert said[0] == "searching for the puck" and said[-1] == "target acquired" and said.count("searching for the puck") == 1
    said.clear()
    env = Env([ok()], puck_after=["in"])
    env.w.basket = None                                                                                       # no tub in the look: the bursts search for the basket, once
    br.attempt_once(env, {"attempt": 1}, False, say=lambda s: None, announce=said.append)
    assert said.count("searching for the basket") == 1
    from types import SimpleNamespace as NS
    from pi_pipeline.behavior import basket_lineup as bl
    said.clear()
    looks = iter([None, None, NS(claw_in=16.0, bearing_deg=10.0), None, None, NS(claw_in=16.0, bearing_deg=0.0)])
    m = type("M", (), {"scan": lambda s, v: "ok", "pivot": lambda s, v: "ok", "nudge": lambda s, v: "ok", "forward": lambda s, v: "ok", "back": lambda s, v: "ok"})()
    bl.lineup(lambda: next(looks), m, say=lambda s: None, announce=said.append, max_steps=7)
    assert said == ["searching for the basket", "searching for the basket"]                                    # once per search (a second search after the tub was seen again), not once per scan step


def test_after_the_back_up_he_looks_then_turns_onto_the_puck_before_any_walk():
    """Owner, 2026-11-25: the back-up curves him aside, so the last walk waits for the turn onto the puck."""
    st = br.RState()
    a = br.next_retrieval_action(P(4.2, 1.4), None, st)                                                       # too near: back up to the stand
    assert a.kind == "back" and abs(a.value - (br.PICK_STAND_IN - 4.2)) < 1e-9
    a = br.next_retrieval_action(P(br.PICK_STAND_IN, 10.0), None, st)                                         # the look after it: the puck drifted 10 degrees: a small turn first
    assert a.kind == "nudge" and a.value == 10.0
    a = br.next_retrieval_action(P(br.PICK_STAND_IN, 22.0), None, st)                                         # 22 degrees: a pivot
    assert a.kind == "pivot" and a.value > 0
    a = br.next_retrieval_action(P(br.PICK_STAND_IN, 2.0), None, st)                                          # squared up: now the last walk and the pick-up
    assert a.kind == "pick"
    assert br.PICK_STAND_IN - br.PICK_STAND_TOL_IN >= 6.0                                                    # the stand sits inside the finder's floor window at row 89 or so, never at its upper edge


def _tp(x, y, w=10, h=9):
    from types import SimpleNamespace as NS
    return NS(x=x, y=y, count=60, width_px=w, height_px=h)


def _bk(width=89, left=80, right=168, rim=104.0):
    from types import SimpleNamespace as NS
    return NS(width_px=width, left=left, right=right, rim_row=rim, claw_in=9.8, bearing_deg=0.0)


def test_two_pictures_must_agree_on_a_puck_inside_the_tub_before_it_is_a_make():
    a = (_bk(), None, _tp(120.0, 116.0))
    assert br.tub_puck_agrees(a, (_bk(), None, _tp(123.0, 118.0)))                                    # the same spot, as a fraction of the tape
    assert br.tub_puck_agrees(a, (_bk(width=60, left=95, right=155, rim=90.0), None, _tp(125.0, 100.0)))   # taken from farther: the same relative spot
    assert not br.tub_puck_agrees(a, (_bk(), None, _tp(160.0, 116.0)))                                # another place in the tub: not the same blob
    assert not br.tub_puck_agrees(a, (_bk(), None, None)) and not br.tub_puck_agrees(None, a) and not br.tub_puck_agrees(a, (None, None, _tp(120.0, 116.0)))

    env = br.RealEnv.__new__(br.RealEnv)
    env.last_quick = (_bk(), None, _tp(120.0, 116.0))
    env.quick_hist = [(_bk(), None, _tp(121.0, 117.0)), env.last_quick]
    taken = []
    env._quick = lambda by: taken.append(by)
    assert env.quick_confirm() is env.last_quick and not taken                                         # the last two pictures agree: no extra picture
    env.quick_hist = [env.last_quick]
    seconds = (_bk(), None, _tp(122.0, 117.0))
    env._quick = lambda by: (taken.append(by), setattr(env, "last_quick", seconds))[0]
    assert env.quick_confirm() is seconds and taken == ["width"]                                       # only one picture so far: he takes one more, and it agrees
    cur = (_bk(), None, _tp(120.0, 116.0))
    env.last_quick, env.quick_hist = cur, [cur]
    env._quick = lambda by: setattr(env, "last_quick", (_bk(), None, None))                            # the second picture shows nothing inside: not a make
    b, f, t = env.quick_confirm()
    assert t is None and b is cur[0]
    env.last_quick = (_bk(), None, None)
    assert env.quick_confirm()[2] is None                                                              # nothing inside to begin with: unchanged


def test_a_puck_inside_and_another_on_the_floor_is_not_a_make():
    from types import SimpleNamespace as NS
    from pi_pipeline.goals import basket_outcome as bo
    b = NS(claw_in=9.8, bearing_deg=0.0)
    assert bo.classify_throw(b, None, NS(x=1, y=1), confirm=True)[0] == bo.MADE
    code, words = bo.classify_throw(b, NS(claw_in=9.0, bearing_deg=20.0), NS(x=1, y=1), confirm=True)
    assert code == bo.MISSED and "outside" in words                                                    # a puck seen through the clear wall from outside is not a make


def test_a_relaxed_puck_reading_in_the_retrieval_look_needs_a_second_picture_that_agrees(monkeypatch):
    """2026-11-26: a puck found only by the relaxed pass (small or pale) is trusted when a second quick picture puts it in the same place; `G2_PUCK_RELAXED_CONFIRM=0` takes the first picture."""
    from pi_pipeline.vision import puck_finder as pf
    env = object.__new__(br.RealEnv)
    mk = lambda b, d, relaxed: pf.PuckReading(120.0, 108.0, 8, 6, 40, b, d, relaxed=relaxed)        # noqa: E731
    seq = []
    monkeypatch.setattr(br.RealEnv, "_quick", lambda self, by: seq.pop(0))
    seq[:] = [(None, mk(0.0, 12.0, True)), (None, mk(2.0, 12.5, True))]
    assert env.look()[1].claw_in == 12.5 and not seq                                                 # agreed: trusted
    seq[:] = [(None, mk(0.0, 12.0, True)), (None, mk(25.0, 12.0, True))]
    assert env.look()[1] is None                                                                     # a different place: not seen
    seq[:] = [(None, mk(0.0, 12.0, True)), (None, None)]
    assert env.look()[1] is None
    seq[:] = [(None, mk(0.0, 12.0, False))]
    assert env.look()[1].claw_in == 12.0                                                             # a strict reading is taken at once, one picture
    monkeypatch.setenv("G2_PUCK_RELAXED_CONFIRM", "0")
    seq[:] = [(None, mk(0.0, 12.0, True))]
    assert env.look()[1].claw_in == 12.0


def test_a_puck_dropped_during_the_line_up_is_fetched_again():
    class Drop(Env):
        """After the first pick-up the line-up's pictures show the puck on the floor 6 inches ahead (dropped); the second pick-up holds it."""
        def quick_basket(self):
            if self.picks == 1 and not getattr(self, "did_drop", False):
                self.did_drop, self.w.puck = True, (8.0, 0.0)                                         # it fell out of the claw
            super().quick_basket()
            self.last_floor_puck = P(*self.w.puck) if self.w.puck else None
            return B(16.0, 0.0) if self.picks >= 2 else B(16.0, 14.0)                                   # off to the side until the second pick-up: the line-up takes several pictures
    env = Drop([ok(), ok()], puck_after=[(20.0, 0.0)], basket_start=(16.0, 0.0))
    r = br.run_sequence(env, max_attempts=2, say=lambda s: None)
    att = r["attempts"][0]
    assert env.picks == 2 and len(att.get("dropped", [])) == 1                                        # fetched again, once
    assert att["lineup"]["outcome"] == "aligned" and att["retrieval"]["outcome"] == "retrieved"


def test_a_mock_env_without_a_floor_puck_reading_never_trips_the_drop_watch():
    env = Env([ok(), ok()], puck_after=[(20.0, 0.0)])
    r = br.run_sequence(env, max_attempts=2, say=lambda s: None)
    assert "dropped" not in r["attempts"][0]


def test_the_drop_watch_needs_two_pictures_of_the_last_three():
    class E:
        def __init__(self):
            self.seq = iter([P(30.0, 0.0), None, P(6.0, 0.0), None, P(5.0, 2.0)])
        def quick_basket(self):
            self.last_floor_puck = next(self.seq)
            return B(16.0, 0.0)
    look = br.watch_for_drop(E())
    for _ in range(4):
        look()                                                                                         # one near puck, then a far one (over 12 inches): not a drop
    try:
        look()
    except br.PuckDropped as e:
        assert e.puck.claw_in == 5.0                                                                   # the second near one within the last three
    else:
        raise AssertionError("no drop")


def test_a_centred_puck_a_little_out_is_picked_directly_only_when_the_reach_setting_allows_it(monkeypatch):
    monkeypatch.delenv("G2_PICK_DIRECT_MAX_IN", raising=False)
    assert act(P(4.0, 2.0)).kind == "back"                                                           # today: backed away from, the last walk moves about 8 inches
    monkeypatch.setenv("G2_PICK_DIRECT_MAX_IN", "4.5")
    assert act(P(4.0, 2.0)).kind == "pick" and act(P(4.0, 2.0)).value == br.BLIND_STEP_IN
    assert act(P(5.5, 2.0)).kind == "pick" and act(P(5.5, 2.0)).value != br.BLIND_STEP_IN and act(P(4.0, 9.0)).kind != "pick"                       # farther, or off to the side: as before


def test_a_puck_lost_from_close_range_is_looked_for_by_backing_up_not_by_scanning():
    st = br.RState()
    assert br.next_retrieval_action(P(3.0, 10.9), None, st).kind == "nudge"                         # seen 3 inches out, turned onto
    a = br.next_retrieval_action(None, None, st)                                                    # and now not seen: it is under the claw
    assert a.kind == "back" and a.value == br.CLOSE_REAPPROACH_BACK_IN and "lost from 3.0" in a.why
    assert br.next_retrieval_action(None, None, st).kind == "scan"                                  # still nothing after the back-up: the scan as before
    far = br.RState()
    br.next_retrieval_action(P(12.0, 0.0), None, far)
    assert br.next_retrieval_action(None, None, far).kind == "back"                                 # seen at 12 inches, then not seen: back up and look again too (owner, 2026-11-27)
    for _ in range(br.VANISH_BACKS_MAX - 1):                                                        # seen again and lost again, up to VANISH_BACKS_MAX times
        br.next_retrieval_action(P(12.0, 0.0), None, far)
        assert br.next_retrieval_action(None, None, far).kind == "back"
    br.next_retrieval_action(P(12.0, 0.0), None, far)
    assert br.next_retrieval_action(None, None, far).kind == "scan"                                 # then the scan as before
    never = br.RState()
    assert br.next_retrieval_action(None, None, never).kind == "scan"                               # never seen: nothing to back up from


def test_a_puck_clipped_at_the_bottom_of_the_picture_is_picked_not_turned_for_or_backed_from():
    """2026-11-27 run: three last walks left the puck at base row 211 behind the jaw; the close look turned for 20 px, read nothing and backed up each time."""
    from pi_pipeline.vision.puck_close import CloseReading
    assert br.next_close_action(CloseReading(45, 72, 211, 98)) is None                                       # 20 px off, clipped: pick
    assert br.next_close_action(CloseReading(62, 28, 211, 122)) is None                                      # 19 px nearer than the spot, clipped: no back-up
    assert br.next_close_action(CloseReading(53, 69, 211, 81)).kind == "nudge"                               # 37 px off is still turned for
    assert br.next_close_action(CloseReading(45, 40, 195, 98)).kind == "nudge"                               # not clipped: the old tolerance


def test_a_narrow_tall_blob_at_the_bottom_after_a_last_walk_is_the_puck_behind_the_jaw():
    from pi_pipeline.vision.puck_close import CloseReading

    class Env:
        mover = None
        last_floor_puck = None

        def __init__(self, r):
            self.r = r

        def look(self):
            return None, None

        def close_reading(self):
            return self.r
    st = br.RState()
    st.last_seen_in = 7.1
    assert br.close_align(Env(CloseReading(7, 41, 207, 104)), st, say=lambda s: None) == "aligned"           # the picture of 16:03:54
    assert br.close_align(Env(CloseReading(5, 4, 211, 93)), st, say=lambda s: None) == "unread"              # a 4 px high glint is not the puck
    st.last_seen_in = 20.0
    assert br.close_align(Env(CloseReading(7, 41, 207, 104)), st, say=lambda s: None) == "unread"


def test_a_wide_near_relaxed_puck_read_is_not_confirmed_with_a_second_picture():
    from types import SimpleNamespace as NS
    assert br.relaxed_read_is_clear(NS(width_px=14, claw_in=10.0)) and br.relaxed_read_is_clear(NS(width_px=30, claw_in=4.8))
    assert not br.relaxed_read_is_clear(NS(width_px=13, claw_in=9.0)) and not br.relaxed_read_is_clear(NS(width_px=20, claw_in=10.5))
    assert not br.relaxed_read_is_clear(NS())

    class E(br.RealEnv):
        def __init__(self, reads):
            self.reads, self.n = reads, 0

        def _quick(self, by):
            self.n += 1
            return None, self.reads.pop(0)
    near = NS(relaxed=True, width_px=16, claw_in=6.0, bearing_deg=0.0)
    e = E([near])
    assert e.look()[1] is near and e.n == 1                                                              # one picture
    far = NS(relaxed=True, width_px=9, claw_in=7.7, bearing_deg=22.0, y=5)
    e = E([far, far])
    e.look()
    assert e.n == 2                                                                                      # a small read is still confirmed


def test_overshoots_are_counted_a_puck_lost_after_a_forward_move_and_found_again_after_the_back_up():
    """Owner, 2026-11-27: keep track of how many times he overshoots the puck (sees it, moves in, loses it, backs up, sees it again)."""
    st = br.RState()
    assert br.next_retrieval_action(P(9.0, 1.0), None, st).kind == "pick"                           # the last walk is decided from a look at 9 inches
    a = br.next_retrieval_action(None, None, st)                                                    # after the walk the puck is gone: it is under the claw or past it
    assert a.kind == "back" and st.over["lost_after_forward"] == 1 and st.pending_lost["after"] == "pick"
    br.next_retrieval_action(P(5.5, 3.0), None, st)                                                 # the back-up's look sees it again
    assert st.over["refound_after_back"] == 1 and st.pending_lost is None
    assert [e["event"] for e in st.over_events] == ["lost after pick", "found again after the back-up"] and st.over_events[1]["now_in"] == 5.5
    t = br.RState()
    br.next_retrieval_action(P(10.0, 10.0), None, t)                                                # a nudge
    br.next_retrieval_action(None, None, t)
    assert t.over["lost_after_turn"] == 1 and t.over["lost_after_forward"] == 0                     # lost after a turn is a different count
    u = br.RState()
    assert br.next_retrieval_action(None, None, u).kind == "scan" and sum(u.over.values()) == 0      # never seen: nothing lost
    v = br.RState()
    br.next_retrieval_action(P(9.0, 1.0), None, v)
    br.next_retrieval_action(None, None, v)
    br.next_retrieval_action(None, None, v)                                                         # still nothing after the back-up: a scan, no recovery counted
    assert v.over["lost_after_forward"] == 1 and v.over["refound_after_back"] == 0 and v.pending_lost is None
