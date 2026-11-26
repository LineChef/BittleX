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


def test_the_close_align_corrects_then_stops_at_the_spot(monkeypatch):
    monkeypatch.setenv("G2_PICK_CLOSE_ALIGN", "1")
    ok = pc.find_close_array(picture())
    off = pc.find_close_array(picture(left=118, right=158))
    st = br.RState()
    e = Env([off, ok])
    assert br.close_align(e, st, say=lambda s: None) == "aligned" and e.looks == 2 and [m[0] for m in e.mover.moves] == ["nudge"]
    e = Env([ok])
    assert br.close_align(e, br.RState(), say=lambda s: None) == "aligned" and e.mover.moves == []


def test_the_close_align_gives_up_after_its_tries_and_goes_on_when_nothing_is_read(monkeypatch):
    monkeypatch.setenv("G2_PICK_CLOSE_ALIGN", "1")
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
    e = Env([pc.find_close_array(picture(left=118, right=158))])
    assert br.close_align(e, br.RState(), say=lambda s: None) == "unread" and e.looks == 0      # off by default: the pick-up spot is 1 inch, not the 2 inches it was built on
    monkeypatch.setenv("G2_PICK_CLOSE_ALIGN", "1")
    assert br.close_align(e, br.RState(), say=lambda s: None) != "unread" or e.looks > 0


def test_the_base_row_gives_the_distance_from_the_claw_tip_between_2_and_6_inches():
    for row, inches in ((192, 2.0), (164, 3.0), (153, 4.0), (133, 6.0)):                # the owner's pictures
        r = pc.CloseReading(40, 30, row, 118)
        assert abs(r.distance_in - inches) <= 0.4, (row, r.distance_in)
