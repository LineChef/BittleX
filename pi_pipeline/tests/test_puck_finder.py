"""The puck finder (vision/puck_finder.py) on pictures made up in code: a grey floor and wall with a coloured block on it."""
import numpy as np

from pi_pipeline.vision import basket_finder as bf
from pi_pipeline.vision import puck_finder as pf


def picture(*boxes):
    img = np.full((240, 240, 3), 110, dtype=np.int16)
    for x0, y0, x1, y1, c in boxes:
        img[y0:y1, x0:x1] = c
    return img


RED = (169, 91, 66)


def test_the_puck_is_found_with_a_bearing_and_a_distance_that_falls_with_its_row():
    near = pf.find_puck_array(picture((112, 124, 128, 143, RED)))                  # about 16 x 19: the 6 inch size, centred
    assert near is not None and abs(near.bearing_deg) < 2 and 5.0 <= near.claw_in <= 8.0
    far = pf.find_puck_array(picture((113, 96, 119, 103, RED)))                    # a 6 x 7 speck low on the wall's base: the 24 inch size
    assert far is not None and 20.0 <= far.claw_in <= 32.0 and far.claw_in > near.claw_in
    right = pf.find_puck_array(picture((150, 124, 166, 143, RED)))
    left = pf.find_puck_array(picture((70, 124, 86, 143, RED)))
    assert right.bearing_deg > 8 and left.bearing_deg < -8                           # + is to G2's right


def test_what_is_not_the_puck_is_ignored():
    assert pf.find_puck_array(picture()) is None                                     # an empty floor
    assert pf.find_puck_array(picture((60, 40, 80, 60, RED))) is None                # on the wall, above its base
    assert pf.find_puck_array(picture((112, 205, 128, 225, RED))) is None            # in the jaws
    assert pf.find_puck_array(picture((2, 124, 10, 143, RED))) is None               # at the side edge
    assert pf.find_puck_array(picture((100, 124, 103, 127, RED))) is None            # a speck
    assert pf.find_puck_array(picture((70, 124, 170, 135, RED))) is None            # far too wide
    assert pf.find_puck_array(picture((80, 120, 160, 128, RED))) is None            # a long sliver


def test_the_basket_is_not_the_puck_but_a_puck_beside_it_is():
    img = picture((98, 100, 145, 133, bf.BASKET_RGB), (60, 124, 76, 143, RED))
    basket = bf.find_basket_array(img)
    assert basket is not None
    p = pf.find_puck_array(img, basket)
    assert p is not None and p.bearing_deg < -8                                      # the puck to the left, not the basket
    only_basket = picture((98, 120, 124, 140, bf.BASKET_RGB))
    reading = type("B", (), {"x": 111.0, "y": 130.0, "width_px": 26, "height_px": 20})()
    assert pf.find_puck_array(only_basket, reading) is None                          # the basket's own box is skipped


def test_the_distance_curve_is_steady_and_the_biggest_blob_wins():
    rows = (96, 100, 106, 116, 124, 133)
    d = [pf.distance_from_row(r) for r in rows]
    assert all(a > b for a, b in zip(d, d[1:])) and pf.distance_from_row(90) == float("inf")
    both = pf.find_puck_array(picture((112, 124, 128, 143, RED), (170, 98, 176, 104, RED)))
    assert both is not None and both.area > 100


def test_a_quick_claw_down_picture_reads_the_distance_from_the_width():
    p = pf.find_puck_array(picture((113, 124, 127, 143, RED)), by="width")                   # 14 pixels wide: about 6.8 inches
    assert p is not None and 6.0 <= p.claw_in <= 7.6
    q = pf.find_puck_array(picture((113, 124, 122, 134, RED)), by="width")                   # 9 pixels wide: about 10.6 inches
    assert q is not None and 9.5 <= q.claw_in <= 11.5 and q.claw_in > p.claw_in
    assert pf.find_puck_array(picture((113, 124, 127, 143, RED)), by="row").claw_in != p.claw_in


def test_a_puck_cut_off_at_the_bottom_of_the_floor_rows_is_marked_clipped():
    at_tip = pf.find_puck_array(picture((112, 186, 128, 215, RED)), by="width")        # runs on into the jaws: its lowest rows are hidden
    assert at_tip is not None and at_tip.clipped
    assert not pf.find_puck_array(picture((112, 124, 128, 143, RED))).clipped
