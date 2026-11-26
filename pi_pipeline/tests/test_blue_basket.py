"""The blue-tape basket (basket_finder's blue test, from the 12 `basket-blue` calibration pictures, 2026-11-26) and the puck finder's blue rejection."""
import numpy as np

from pi_pipeline.vision import basket_finder as bf
from pi_pipeline.vision import puck_finder as pf


def floor():
    return np.full((240, 240, 3), (110, 108, 105), dtype=np.uint8)


def with_band(a, left, right, top, bottom, colour):
    a[top:bottom + 1, left:right + 1] = colour
    return a


def test_a_blue_band_reads_as_the_basket_at_the_distance_its_width_gives():
    a = with_band(floor(), 95, 144, 98, 110, (79, 100, 126))                 # 50 px wide: about 12 inches (the 12 inch picture read 50)
    r = bf.find_basket_array(a)
    assert r is not None and r.width_px == 50 and abs(r.claw_in - 12.0) <= 1.5 and abs(r.bearing_deg) < 3
    far = bf.find_basket_array(with_band(floor(), 110, 130, 110, 114, (90, 104, 128)))    # 21 px wide: about 22 inches
    assert far is not None and abs(far.claw_in - 22.0) <= 2.0


def test_pale_blue_grey_things_up_the_picture_are_not_the_basket():
    for colour, rows in (((187, 201, 211), (98, 110)), ((136, 148, 159), (98, 110)), ((79, 100, 126), (55, 66))):         # a window, a wall tint, a sofa high up the picture
        assert bf.find_basket_array(with_band(floor(), 60, 110, rows[0], rows[1], colour)) is None, colour


def test_the_red_tape_still_reads_as_before():
    a = with_band(floor(), 90, 150, 100, 105, (240, 115, 105))
    r = bf.find_basket_array(a)
    assert r is not None and r.width_px >= 55 and r.claw_in > 0


def test_the_puck_finder_never_reads_the_blue_tape_but_still_reads_the_puck():
    blue = with_band(floor(), 95, 120, 150, 165, (60, 90, 190))
    assert pf.find_puck_array(blue, None, by="width") is None and pf.find_puck_array(blue, None) is None
    orange = with_band(floor(), 95, 105, 150, 160, (230, 110, 40))
    assert pf.find_puck_array(orange, None, by="width") is not None


def test_a_blue_band_up_to_row_67_is_the_basket_but_the_wall_and_a_pale_grey_blue_one_are_not():
    """2026-11-26: the tub 12 to 18 inches out sits at rows 65 to 75 in the goal run's pictures, the tub at 8 inches at 82 to 87 (the gate was 85, then 82, and hid every tub beyond about 9 inches); a pale grey-blue pet bed or wall read as a tub in old pictures."""
    tape = (71, 88, 115)                                                       # the tape as the camera showed it: dark, purity 0.38
    for bottom in (87, 82, 75, 67):
        assert bf.find_basket_array(with_band(floor(), 90, 152, bottom - 12, bottom, tape)) is not None, bottom
    assert bf.find_basket_array(with_band(floor(), 90, 152, 54, 66, tape)) is None          # still the wall's rows
    assert bf.find_basket_array(with_band(floor(), 90, 152, 72, 84, (127, 158, 171))) is None   # the pale pet bed: bright, purity 0.26
    dark_far = (57, 63, 78)                                                    # the far tub in dim light: purity 0.27
    assert bf.find_basket_array(with_band(floor(), 112, 150, 65, 75, dark_far)) is not None


def test_the_blue_tub_reads_its_base_further_down_and_a_puck_inside_it_is_read_through_the_plastic():
    img = with_band(floor(), 90, 152, 70, 83, (71, 88, 115))
    img[104:112, 110:122] = (96, 112, 80)                                      # a puck seen through the clear wall: channel spread 28 to 40
    tub = bf.find_basket_array(img)
    assert tub is not None and tub.blue and tub.base_row == 83 + bf.BLUE_BASE_RATIO * tub.width_px
    inside = pf.find_puck_in_tub_array(img, tub)
    assert inside is not None and 108 <= inside.x <= 124
    assert pf.find_puck_in_tub_array(with_band(floor(), 90, 152, 70, 83, (71, 88, 115)), tub) is None      # empty


def test_a_thin_blue_line_at_the_walls_base_is_not_the_tub_but_a_far_band_is():
    """2026-11-26 goal run: a 3 row tall blue line 24 to 33 wide at rows 66 to 68 read as a tub 16 to 21 inches out in 3 pictures; the far tub's band is 5 rows or more."""
    tape = (71, 89, 105)
    assert bf.find_basket_array(with_band(floor(), 0, 32, 66, 68, tape)) is None
    assert bf.find_basket_array(with_band(floor(), 128, 149, 64, 70, (54, 65, 77))) is not None
