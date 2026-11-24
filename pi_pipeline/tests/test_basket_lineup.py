"""The basket finder (vision/basket_finder.py) and the line-up logic (behavior/basket_lineup.py), on pictures made up in code and a simulated floor."""
import numpy as np

from pi_pipeline.behavior import basket_lineup as bl
from pi_pipeline.vision import basket_finder as bf

ORANGE = bf.BASKET_RGB


def picture(*boxes):
    img = np.full((240, 240, 3), 110, dtype=np.int16)
    for x0, y0, x1, y1, c in boxes:
        img[y0:y1, x0:x1] = c
    return img


def test_the_basket_is_found_with_its_bearing_and_a_distance_from_its_width():
    r = bf.find_basket_array(picture((98, 88, 145, 121, ORANGE)))                      # 47 px wide: about 15.5 inches from the claw tip
    assert r is not None and abs(r.width_px - 47) <= 2 and abs(r.bearing_deg) < 3
    assert 15 <= r.claw_in <= 16.5 and abs(r.claw_in - (r.lens_in - bf.LENS_OFFSET_IN)) < 1e-9
    right = bf.find_basket_array(picture((136, 88, 170, 108, ORANGE)))
    left = bf.find_basket_array(picture((70, 88, 104, 108, ORANGE)))
    assert right.bearing_deg > 8 and left.bearing_deg < -8                                # + is to G2's right
    assert bf.find_basket_array(picture((98, 88, 145, 121, (80, 160, 90)))) is None       # the wrong colour
    assert bf.find_basket_array(picture((100, 90, 106, 96, ORANGE))) is None             # a speck
    assert bf.find_basket_array(picture((10, 70, 230, 130, ORANGE))) is None             # far too wide to be the cup
    assert bf.find_basket_array(picture((98, 10, 145, 40, ORANGE))) is None              # above the horizon


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
    kinds = [bl.next_action(None, st).kind for _ in range(15)]
    assert kinds[:14] == ["scan"] * 14 and kinds[14] == "give_up"                                             # 14 x 27 degrees (378) covers a full circle
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


def test_the_refit_reads_the_eight_measured_distances_within_an_inch():
    measured = ((63, 12), (54, 14), (49, 15), (44, 16), (42, 17), (41, 18), (37, 20), (33, 22))      # (width in pixels, inches from the claw tip), 2026-11-23, claw at lift 120
    for w, d in measured:
        assert abs(bf.distance_from_width(w) - bf.LENS_OFFSET_IN - d) <= 0.7, (w, d)
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


def test_a_basket_closer_than_eight_inches_is_still_read_so_the_guard_can_fire():
    near = bf.find_basket_array(picture((60, 90, 190, 180, ORANGE)))                   # 130 px wide: about 5.6 inches from the claw tip
    assert near is not None and near.claw_in < bl.BUFFER_IN and bl.next_action(near, bl.LineupState()).kind == "back"
    assert bf.find_basket_array(picture((10, 70, 230, 130, ORANGE))) is None             # a stripe across the whole frame is still not the cup


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
