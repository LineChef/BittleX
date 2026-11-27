"""The basket finder (vision/basket_finder.py) and the line-up logic (behavior/basket_lineup.py), on pictures made up in code and a simulated floor."""
import numpy as np

from pi_pipeline.behavior import basket_lineup as bl
from pi_pipeline.vision import basket_finder as bf

TAPE = (200, 60, 50)                  # the tub's red tape


def picture(*boxes):
    img = np.full((240, 240, 3), 110, dtype=np.int16)
    for x0, y0, x1, y1, c in boxes:
        img[y0:y1, x0:x1] = c
    return img


def tape(left, right, rim=100, thick=7, c=TAPE):
    """The tub's tape: a red band from column `left` to `right` ending on row `rim`."""
    return (left, rim - thick, right + 1, rim + 1, c)


def test_the_tub_is_found_by_its_tape_with_a_bearing_and_a_distance_from_its_width():
    r = bf.find_basket_array(picture(tape(86, 144)))                                      # 59 px wide: about 15.8 inches from the claw tip
    assert r is not None and abs(r.width_px - 59) <= 2 and abs(r.bearing_deg) < 3
    assert 15 <= r.claw_in <= 16.6 and abs(r.claw_in - (r.lens_in - bf.LENS_OFFSET_IN)) < 1e-9
    assert (r.left, r.right) == (86, 144) and r.rim_row == 100 and r.base_row > r.rim_row                  # the footprint the puck finders read
    right = bf.find_basket_array(picture(tape(150, 190)))
    left = bf.find_basket_array(picture(tape(50, 90)))
    assert right.bearing_deg > 8 and left.bearing_deg < -8                                # + is to G2's right
    assert bf.find_basket_array(picture(tape(86, 144, c=(80, 160, 90)))) is None          # the wrong colour
    assert bf.find_basket_array(picture(tape(100, 108))) is None                          # a speck
    assert bf.find_basket_array(picture((100, 90, 118, 108, TAPE))) is None               # a puck's red block: not wide and thin
    assert bf.find_basket_array(picture(tape(5, 235))) is None                            # far too wide to be the tub's tape
    assert bf.find_basket_array(picture(tape(86, 144, rim=30))) is None                   # above the horizon


class Read:
    def __init__(self, d, b):
        self.claw_in, self.bearing_deg = d, b


def act(d, b, st=None):
    return bl.next_action(None if d is None else Read(d, b), st or bl.LineupState())


def test_the_decisions_for_distance_bearing_and_the_buffer():
    assert act(16.0, 0.5).kind == "shoot" and act(17.5, -2.0).kind == "shoot"                                 # inside the tolerances
    a = act(26.0, 0.0)
    assert a.kind == "forward" and 1.5 <= a.value <= 10.0                                                     # too far: walk closer
    a = act(40.0, 0.0)
    assert a.kind == "forward" and a.value == bl.FAR_STEP_MAX_IN                                              # far off: a bigger step
    a = act(10.0, 0.0)
    assert a.kind == "back" and a.value <= bl.BACK_STEP_MAX_IN                                                # too close: back up
    a = act(7.0, 25.0)
    assert a.kind == "back"                                                                                    # inside the buffer: back first, never turn next to the basket
    assert act(16.0, 40.0).kind == "pivot" and act(16.0, 40.0).value == 27.0 * round(40 / 27) and act(16.0, -40.0).value < 0
    a = act(16.0, 6.0)
    assert a.kind == "nudge" and a.value == 6.0                                                               # a small turn
    for d in (6.5, 9.0, 12.0, 14.0, 18.0):
        for b in (-20, 0, 20):
            a = act(d, b)
            assert not (a.kind == "forward" and d - a.value < bl.BUFFER_IN + bl.CLOSE_MARGIN_IN), (d, b, a)    # a step forward never ends inside the buffer


def test_the_pivot_scan_runs_up_to_a_full_circle_and_gives_up_and_a_found_basket_resets_it():
    st = bl.LineupState()
    n = int(bl.SCAN_MAX_DEG // bl.SCAN_STEP_DEG)
    kinds = [bl.next_action(None, st).kind for _ in range(n + 1)]
    assert n == 16 and kinds[:n] == ["scan"] * n and kinds[n] == "give_up"                                     # 16 x 54 degrees asked (864): about 45 each really, two full circles
    st = bl.LineupState()
    bl.next_action(None, st)
    bl.next_action(Read(16.0, 0.0), st)
    assert st.scanned_deg == 0.0


def test_a_whole_line_up_in_a_simulated_room_never_bumps_the_basket_and_ends_aligned():
    class World:
        def __init__(self, d, b, visible=True, scan_to_see=0):
            self.d, self.b, self.visible, self.min_d, self.scans, self.need = d, b, visible, d, 0, scan_to_see

        def look(self):
            return Read(self.d, self.b) if self.visible else None

        def scan(self, deg):
            self.scans += 1
            self.visible = self.scans >= self.need

        def pivot(self, deg):
            self.b -= deg

        nudge = pivot

        def forward(self, inches):
            self.d -= inches
            self.min_d = min(self.min_d, self.d)

        def back(self, inches):
            self.d += inches

    for d0, b0 in ((8.0, 4.0), (9.0, 12.0), (30.0, 0.0), (45.0, 15.0), (16.0, 25.0), (12.0, -30.0), (20.0, 9.0)):
        w = World(d0, b0)
        r = bl.lineup(w.look, w, say=lambda s: None)
        assert r["outcome"] == "aligned" and abs(w.d - bl.TARGET_IN) <= bl.DIST_TOL_IN and abs(w.b) <= bl.ALIGN_TOL_DEG, (d0, b0, r["outcome"], w.d, w.b)
        assert w.min_d >= bl.BUFFER_IN, (d0, b0, w.min_d)
    w = World(20.0, 0.0, visible=False, scan_to_see=4)                                                          # not in view: scan until it is, then line up
    assert bl.lineup(w.look, w, say=lambda s: None)["outcome"] == "aligned" and w.scans == 4
    w = World(20.0, 0.0, visible=False, scan_to_see=99)
    assert bl.lineup(w.look, w, say=lambda s: None)["outcome"] == "basket_not_found"
    calls = []
    w = World(16.0, 0.0)
    bl.lineup(lambda: calls.append(1) or w.look(), w, say=lambda s: None)
    assert calls                                                                                                # a fresh look comes before every decision, the first included


def test_a_basket_that_never_gets_closer_stops_for_a_reset_after_the_step_limit():
    class Stuck:
        def look(self):
            return Read(30.0, 0.0)

        def forward(self, inches):
            pass

    r = bl.lineup(Stuck().look, Stuck(), say=lambda s: None)
    assert r["outcome"] == "could_not_align" and len(r["steps"]) == bl.MAX_CORRECTIONS + 1


def test_the_tub_fit_reads_the_measured_distances():
    measured = ((82, 12), (68, 14), (59, 16), (55, 17), (52, 18), (47, 19), (47, 20), (46, 22))        # (the tape's width in pixels, inches from the claw tip), the `tub` set 2026-11-24, claw at lift 120
    for w, d in measured:
        assert abs(bf.distance_from_width(w) - bf.LENS_OFFSET_IN - d) <= 1.5, (w, d)
    assert abs(bf.distance_from_width(89) - bf.LENS_OFFSET_IN - 8) <= 2.0                                # the 8 inch pictures
    assert bf.distance_from_width(0) == float("inf")
    assert bf.distance_from_width(30) > bf.distance_from_width(60) > bf.LENS_OFFSET_IN


def test_a_fall_in_a_mover_ends_the_line_up():
    class Falls:
        def look(self):
            return Read(30.0, 0.0)

        def forward(self, inches):
            return "fell"

    r = bl.lineup(Falls().look, Falls(), say=lambda s: None)
    assert r["outcome"] == "fell" and len(r["steps"]) == 1


def test_a_tub_closer_than_eight_inches_is_still_read_so_the_guard_can_fire():
    near = bf.find_basket_array(picture(tape(30, 200, rim=130, thick=14)))                # 171 px wide: about 4 inches from the claw tip
    assert near is not None and near.claw_in < bl.BUFFER_IN and bl.next_action(near, bl.LineupState()).kind == "back"
    assert bf.find_basket_array(picture(tape(5, 235, rim=130, thick=14))) is None          # a stripe across the whole frame is still not the tape


def test_a_back_up_is_one_move_to_the_shot_distance_allowing_for_the_sideways_drift():
    import math
    for d, b in ((10.0, 0.0), (5.4, 17.3), (6.8, -4.1), (11.6, 25.0)):
        inches = bl.back_inches_to_target(d, b)
        th = math.radians(b)
        end = math.hypot(d * math.cos(th) + inches, d * math.sin(th) - bl.BACK_DRIFT_RATIO * inches)
        assert abs(end - bl.TARGET_IN) < 0.05 and inches <= bl.BACK_STEP_MAX_IN                              # ends at the shot distance, in one step
    assert bl.back_inches_to_target(10.0, 0.0) < bl.TARGET_IN - 10.0                                          # the drift lengthens the line, so a little less than straight back
    assert bl.back_inches_to_target(1.0, 0.0) == bl.BACK_STEP_MAX_IN                                          # the mover's one-step cap
    assert act(5.4, 17.3).value > 6.0                                                                          # the inside-the-buffer back-up is no longer capped at 6


def test_an_aim_offset_lines_him_up_to_one_side_of_the_basket_centre(monkeypatch):
    assert act(16.0, 0.0).kind == "shoot"
    monkeypatch.setattr(bl, "AIM_OFFSET_DEG", 2.0)                                                            # aim 2 degrees right of centre: the basket should read 2 degrees to his left
    assert act(16.0, 0.0).kind == "shoot" and act(16.0, 5.0).kind == "nudge" and act(16.0, 5.0).value == 7.0 and act(16.0, -2.0).kind == "shoot"


def test_the_confirm_walk_up_is_the_line_up_aimed_at_the_close_look_with_the_same_buffer():
    from types import SimpleNamespace as NS
    st = bl.LineupState()
    far = bl.next_action(NS(claw_in=16.0, bearing_deg=0.0), st, bl.CONFIRM_READING_IN, bl.CONFIRM_TOL_IN, bl.CONFIRM_ALIGN_TOL_DEG)
    assert far.kind == "forward" and 5.0 <= far.value <= bl.FWD_STEP_MAX_IN                      # walks up to the tub
    assert bl.next_action(NS(claw_in=9.8, bearing_deg=0.0), bl.LineupState(), bl.CONFIRM_READING_IN, bl.CONFIRM_TOL_IN, bl.CONFIRM_ALIGN_TOL_DEG).kind == "shoot"      # about 8 inches really: look
    assert bl.next_action(NS(claw_in=10.9, bearing_deg=7.0), bl.LineupState(), bl.CONFIRM_READING_IN, bl.CONFIRM_TOL_IN, bl.CONFIRM_ALIGN_TOL_DEG).kind == "shoot"        # a look from 10 inches is fine, the tub within 8 degrees
    assert bl.next_action(NS(claw_in=7.0, bearing_deg=0.0), bl.LineupState(), bl.CONFIRM_READING_IN, bl.CONFIRM_TOL_IN, bl.CONFIRM_ALIGN_TOL_DEG).kind == "back"      # inside the 6 inch buffer plus its margin: back up before anything else
    assert bl.next_action(NS(claw_in=16.0, bearing_deg=0.0), bl.LineupState()).kind == "shoot"                                                                              # the shot's defaults are unchanged


def test_a_reading_he_already_has_decides_the_first_step_with_no_picture():
    from types import SimpleNamespace as NS
    looks, moves = [], []

    class Mover:
        def forward(self, v):
            moves.append(("forward", round(v, 1)))
            return "ok"

    def look():
        looks.append(1)
        return NS(claw_in=9.8, bearing_deg=0.0)
    r = bl.lineup(look, Mover(), target_in=bl.CONFIRM_READING_IN, dist_tol=bl.CONFIRM_TOL_IN, align_tol=bl.CONFIRM_ALIGN_TOL_DEG, first=NS(claw_in=16.0, bearing_deg=0.0))
    assert r["outcome"] == "aligned" and moves and moves[0][0] == "forward" and len(looks) == 1            # the first decision came from `first`, the one picture after the walk checked it
    looks.clear()
    bl.lineup(look, Mover(), target_in=bl.CONFIRM_READING_IN, dist_tol=bl.CONFIRM_TOL_IN, align_tol=bl.CONFIRM_ALIGN_TOL_DEG)
    assert len(looks) == 1                                                                                  # without it the first decision takes a picture, as before


def test_after_a_back_up_he_squares_up_to_the_tub_before_walking_forward():
    from types import SimpleNamespace as NS
    st = bl.LineupState()
    back = bl.next_action(NS(claw_in=5.0, bearing_deg=3.0), st)
    assert back.kind == "back" and st.backed
    a = bl.next_action(NS(claw_in=22.0, bearing_deg=12.0), st)                                       # backed up, now too far and 12 degrees off: a small turn first
    assert a.kind == "nudge" and a.value == 12.0 and "re-align" in a.why and st.backed
    a = bl.next_action(NS(claw_in=22.0, bearing_deg=-24.0), st)                                      # 24 degrees off: a pivot
    assert a.kind == "pivot" and a.value < 0                                                         # (the line-up already pivots at 18 degrees or more)
    a = bl.next_action(NS(claw_in=22.0, bearing_deg=2.0), st)                                        # squared up: now the walk forward
    assert a.kind == "forward" and not st.backed
    st2 = bl.LineupState()                                                                           # no back-up first: a small bearing error does not stop the walk
    assert bl.next_action(NS(claw_in=22.0, bearing_deg=6.0), st2).kind == "forward"
    st3 = bl.LineupState()
    assert bl.next_action(NS(claw_in=10.0, bearing_deg=0.0), st3).kind == "back" and st3.backed      # too close also counts


def test_a_strip_that_gets_wider_after_a_back_up_is_a_corner_view_and_he_faces_the_tub_before_trusting_its_distance():
    from types import SimpleNamespace as NS
    st = bl.LineupState()
    a = bl.next_action(NS(claw_in=9.9, bearing_deg=0.0, width_px=88), st)                           # too close: back up
    assert a.kind == "back" and st.backed
    a = bl.next_action(NS(claw_in=12.6, bearing_deg=-14.6, width_px=72), st)                        # after the back-up: narrower is expected, 72 is not wider than 88
    assert a.kind != "back" or "corner" not in a.why
    st = bl.LineupState()
    st.last_width, st.backed = 51.0, True
    a = bl.next_action(NS(claw_in=12.6, bearing_deg=-14.6, width_px=72), st)                        # the 2026-11-25 readings: 51 pixels, a back-up, then 72 at 14.6 degrees left
    assert a.kind in ("nudge", "pivot") and a.value < 0 and "corner" in a.why and not st.backed
    st = bl.LineupState()
    st.last_width, st.backed = 51.0, True
    assert "corner" not in bl.next_action(NS(claw_in=14.0, bearing_deg=3.0, width_px=72), st).why   # squarely in front: the width is believed
    st = bl.LineupState()
    st.last_width = 51.0                                                                             # no back-up first: not a corner call
    assert "corner" not in bl.next_action(NS(claw_in=14.0, bearing_deg=-14.0, width_px=72), st).why


def test_a_stop_request_ends_the_lineup_the_retrieval_and_the_circle_search_within_one_step(tmp_path, monkeypatch):
    from pi_pipeline.behavior import basket_run as br
    flag = tmp_path / "goal_stop"
    monkeypatch.setattr(bl, "STOP_FILES", (str(flag),))
    assert not bl.stop_requested()
    flag.write_text("")
    assert bl.stop_requested()

    class Boom:
        def __getattr__(self, name):
            raise AssertionError("nothing may move or look once a stop is asked for")
    assert bl.lineup(lambda: None, Boom())["outcome"] == "stopped"
    assert br.retrieve(Boom(), say=lambda s: None)["outcome"] == "stopped"
    assert br.circle_search(Boom(), say=lambda s: None)["outcome"] == "stopped"


def test_a_tub_3_to_5_inches_out_reads_wide_and_high_up_but_a_pale_wide_band_is_still_the_wall():
    """2026-11-27 16:21 run: the real tub close up was a deep blue band 108 to 118 px wide ending at row 91 or 92 (purity 0.44), thrown out by the far-wall rule for 19 scans."""
    deep, pale = (20, 70, 120), (90, 105, 120)                                                    # purity 0.83 and 0.25
    near = bf.find_basket_array(picture((60, 68, 170, 92, deep)))                                  # 110 px wide, rows 68 to 91
    assert near is not None and near.width_px >= 108 and near.claw_in < 9.0
    assert bf.find_basket_array(picture((60, 68, 170, 92, pale))) is None                           # a pale wide band up the picture: the wall merged with the sofa
