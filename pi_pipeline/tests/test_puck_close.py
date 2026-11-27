"""The puck at the pick-up spot (vision/puck_close.py) and the basket run's close alignment before the pick-up."""
import numpy as np

from pi_pipeline.behavior import basket_run as br
from pi_pipeline.vision import puck_close as pc


def picture(left=98, right=138, top=160, bottom=192, colour=(230, 110, 40)):
    a = np.full((240, 240, 3), (110, 108, 105), dtype=np.uint8)               # grey floor
    a[top:bottom + 1, left:right + 1] = colour
    return a


def test_a_puck_at_the_spot_reads_as_at_the_spot():
    r = pc.find_close_array(picture())
    assert r is not None and r.at_spot and 38 <= r.width_px <= 46 and r.base_row == 192 and abs(r.col_err_px) <= 1
    green = pc.find_close_array(picture(colour=(60, 190, 70)))
    assert green is not None and green.at_spot                                  # any face, not one colour


def test_errors_say_which_way_the_puck_is_off_the_spot():
    right = pc.find_close_array(picture(left=118, right=158))
    assert right.col_err_px > pc.COL_TOL_PX and right.bearing_err_deg > 0 and not right.at_spot
    far = pc.find_close_array(picture(top=140, bottom=172))
    assert far.row_err_px < -pc.ROW_TOL_PX and not far.at_spot                  # beyond the spot: higher in the picture
    near = pc.find_close_array(picture(top=170, bottom=208))
    assert near.row_err_px > pc.ROW_TOL_PX
    assert pc.find_close_array(np.full((240, 240, 3), 110, dtype=np.uint8)) is None    # nothing coloured: no reading


def test_the_correction_is_a_turn_first_then_a_short_step_or_back_up_and_nothing_at_the_spot():
    mk = lambda **k: pc.find_close_array(picture(**k))                         # noqa: E731
    assert br.next_close_action(None) is None and br.next_close_action(mk()) is None
    a = br.next_close_action(mk(left=118, right=158))
    assert a.kind == "nudge" and a.value > 0
    assert br.next_close_action(mk(left=78, right=118)).value < 0
    assert br.next_close_action(mk(top=140, bottom=172)) is None               # too far: no forward correction yet (a walk moves about 8 inches)
    assert br.next_close_action(mk(top=170, bottom=208)).kind == "back"


class Mover:
    def __init__(self):
        self.moves = []

    def __getattr__(self, name):
        def f(v):
            self.moves.append((name, round(v, 1)))
            return "ok"
        return f


class Env:
    def __init__(self, readings):
        self.readings, self.mover, self.looks = list(readings), Mover(), 0

    def look(self):
        self.looks += 1
        return None, None

    def close_reading(self):
        return self.readings.pop(0) if len(self.readings) > 1 else self.readings[0]


def test_the_close_align_corrects_then_stops_at_the_spot():
    ok = pc.find_close_array(picture())
    off = pc.find_close_array(picture(left=118, right=158))
    st = br.RState()
    e = Env([off, ok])
    assert br.close_align(e, st, say=lambda s: None) == "aligned" and e.looks == 2 and [m[0] for m in e.mover.moves] == ["nudge"]
    e = Env([ok])
    assert br.close_align(e, br.RState(), say=lambda s: None) == "aligned" and e.mover.moves == []


def test_the_close_align_gives_up_after_its_tries_and_goes_on_when_nothing_is_read():
    off = pc.find_close_array(picture(top=170, bottom=208))                    # too near: a back-up each time
    e = Env([off])
    assert br.close_align(e, br.RState(), say=lambda s: None) == "tries" and len(e.mover.moves) == br.CLOSE_ALIGN_TRIES and e.looks == br.CLOSE_ALIGN_TRIES + 1
    e = Env([None])
    assert br.close_align(e, br.RState(), say=lambda s: None) == "unread" and e.mover.moves == []


def test_the_switch_and_an_env_without_a_close_reading_leave_the_pick_up_as_it_was(monkeypatch):
    class Plain:
        mover = Mover()

        def look(self):
            raise AssertionError("must not look")
    assert br.close_align(Plain(), br.RState(), say=lambda s: None) == "unread"
    monkeypatch.setenv("G2_PICK_CLOSE_ALIGN", "0")
    e = Env([pc.find_close_array(picture(left=118, right=158))])
    assert br.close_align(e, br.RState(), say=lambda s: None) == "unread" and e.looks == 0


def test_the_base_row_gives_the_distance_past_the_floor_line_between_0_and_6_inches():
    for row, inches in ((192, 0.0), (183, 1.0), (164, 3.0), (153, 4.0), (133, 6.0)):                # the owner's pictures: lined up from the floor line
        assert abs(pc.CloseReading(40, 30, row, 118).distance_in - inches) <= 0.05, row
    assert 0.0 < pc.CloseReading(40, 30, 188, 118).distance_in < 1.0 and pc.CloseReading(40, 30, 215, 118).distance_in == 0.0


def test_a_blob_too_narrow_for_a_puck_is_not_a_close_reading_and_the_floor_finder_can_overrule_at_the_spot():
    clutter = pc.CloseReading(13, 20, 166, 121)                                # 2026-11-27 run: a 13 px blob "at the pick-up spot"
    assert not clutter.puck_sized and pc.CloseReading(44, 30, 192, 118).puck_sized and pc.CloseReading(57, 30, 211, 118).puck_sized
    e = Env([clutter])
    assert br.close_align(e, br.RState(), say=lambda s: None) == "unread" and e.mover.moves == []              # not turned by, not called "at the spot"
    from types import SimpleNamespace
    ok = pc.find_close_array(picture())
    e = Env([ok, ok])
    e.last_floor_puck = SimpleNamespace(claw_in=4.7, bearing_deg=22.0)                                       # at the spot by the close finder, 22 degrees off by the floor finder
    assert br.close_align(e, br.RState(), say=lambda s: None) == "tries" and e.mover.moves[0][0] == "nudge" and e.mover.moves[0][1] == 22.0


class Sim(__import__("pi_pipeline.tests.test_basket_run", fromlist=["Env"]).Env):
    """The basket run's simulated floor, with a close reading: clutter before the pick-up, then what `after` says."""
    def __init__(self, after, *a, **k):
        super().__init__(*a, **k)
        self.after, self.backs = after, []
        orig = self.mover.back
        self.mover.back = lambda v: (self.backs.append(round(v, 1)), orig(v))[1]

    def close_reading(self):
        return pc.CloseReading(13, 20, 166, 121) if self.picks == 0 else self.after


def test_the_retrieval_backs_off_instead_of_picking_blind_and_checks_the_puck_is_in_the_jaw():
    from pi_pipeline.tests.test_basket_run import P
    e = Sim(pc.CloseReading(57, 30, 211, 118), [{"ok": True}], puck_after=[(8.0, 0.0)])
    e.w.puck = (8.0, 0.0)
    r = br.retrieve(e, say=lambda s: None, first=(None, P(8.0, 0.0)))
    assert r["outcome"] == "retrieved" and e.picks == 1
    assert e.backs.count(br.CLOSE_REAPPROACH_BACK_IN) == br.CLOSE_REAPPROACH_MAX                                  # twice backed off and looked again, then the pick-up
    assert not any(b == br.HELD_CHECK_BACK_IN for b in e.backs)                                                   # a puck in the jaw (57 px wide, row 211) needs no check


def test_a_pick_that_leaves_the_puck_beside_him_is_not_called_picked_up():
    from pi_pipeline.tests.test_basket_run import P
    e = Sim(None, [{"ok": True}], puck_after=[(8.0, 0.0)])                                                        # nothing read after the pick-up: the puck is beside the claw, cropped out of the frame
    e.w.puck = (8.0, 0.0)
    real_look, real_pick = e.look, e.pick
    beside = {"on": False}

    def pick():
        real_pick()
        beside["on"] = e.picks == 1                                                                               # the first pick-up misses: the puck lies at 3 inches, 20 degrees off, out of view
        e.w.puck = None
        return "ok"

    def look():
        b, p = real_look()
        if beside["on"] and e.backs and e.backs[-1] == br.HELD_CHECK_BACK_IN:
            return b, P(3.0, 20.0)                                                                                # one short back-up and it is in view on the floor
        return b, p
    e.pick, e.look = pick, look
    r = br.retrieve(e, say=lambda s: None, first=(None, P(8.0, 0.0)))
    assert any("not in the claw" in s["why"] for s in r["steps"] if s["action"] == "picked_check")
    assert e.backs.count(br.HELD_CHECK_BACK_IN) >= 1
