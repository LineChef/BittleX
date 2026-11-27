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


TAPE = (200, 60, 50)


def tub_picture(*extra):
    """The tub as the 8 inch picture shows it: the tape from column 80 to 168 on rows 96 to 104 (the footprint is columns 90 to 158, rows 107 to 125), plus extra boxes."""
    return picture((80, 96, 169, 105, TAPE), *extra)


def test_the_tub_is_not_the_puck_but_a_puck_beside_it_is():
    img = tub_picture((20, 116, 36, 130, RED))
    basket = bf.find_basket_array(img)
    assert basket is not None
    p = pf.find_puck_array(img, basket)
    assert p is not None and p.bearing_deg < -8                                      # the puck to the left, not the tape
    assert pf.find_puck_array(tub_picture(), bf.find_basket_array(tub_picture())) is None   # the tape's own red is not a puck


def test_a_puck_inside_the_tub_is_read_inside_and_not_on_the_floor():
    img = tub_picture((115, 112, 127, 121, RED))                                    # in the middle of the tub
    basket = bf.find_basket_array(img)
    inside = pf.find_puck_in_tub_array(img, basket)
    assert inside is not None and inside.count >= pf.MIN_INSIDE_PX and 110 <= inside.x <= 130
    assert pf.find_puck_array(img, basket) is None                                   # not a puck on the floor
    assert pf.find_puck_in_tub_array(tub_picture(), bf.find_basket_array(tub_picture())) is None          # an empty tub
    assert pf.find_puck_in_tub_array(img, None) is None                              # no tub, no inside


def test_a_puck_touching_the_tub_outside_is_not_inside():
    for box in ((72, 112, 86, 124),                                                  # against the outer wall: its centre sits on the tape's end column
                (127, 124, 142, 140),                                                # on the floor against the near side: its centre is under the base
                (160, 112, 176, 124)):                                               # against the other wall
        img = tub_picture(box + (RED,))
        basket = bf.find_basket_array(img)
        assert pf.find_puck_in_tub_array(img, basket) is None, box
        assert pf.find_puck_array(img, basket) is not None, box                      # it is a puck on the floor


def test_a_small_puck_in_the_tub_still_counts_and_a_speck_does_not():
    img = tub_picture((100, 114, 104, 119, RED))                                    # 20 pixels, a puck against the far wall
    assert pf.find_puck_in_tub_array(img, bf.find_basket_array(img)) is not None
    speck = tub_picture((100, 114, 102, 117, RED))                                  # 6 pixels
    assert pf.find_puck_in_tub_array(speck, bf.find_basket_array(speck)) is None


def test_the_distance_curve_is_steady_and_the_biggest_blob_wins():
    rows = (96, 100, 106, 116, 124, 133)
    d = [pf.distance_from_row(r) for r in rows]
    assert all(a > b for a, b in zip(d, d[1:])) and pf.distance_from_row(90) == float("inf")
    both = pf.find_puck_array(picture((112, 124, 128, 143, RED), (170, 98, 176, 104, RED)))
    assert both is not None and both.area > 100


def test_a_quick_claw_down_picture_reads_the_distance_from_the_row():
    """2026-11-26: the claw-down picture's distance is read from the blob's centre row (72 + 288 / distance, fitted to the puck centred at 6 to 20 inches); the old width formula read 8 inches as 5."""
    near = pf.find_puck_array(picture((113, 124, 127, 143, RED)), by="width")                # centre row 133: 288 / (133.5 - 72) = 4.7 inches
    assert near is not None and 4.0 <= near.claw_in <= 5.5
    mid = pf.find_puck_array(picture((113, 104, 125, 113, RED)), by="width")                 # centre row 108: 8 inches
    assert mid is not None and 7.2 <= mid.claw_in <= 8.8 and mid.claw_in > near.claw_in
    far = pf.find_puck_array(picture((115, 85, 122, 88, RED)), by="width")                   # centre row 86: 20 inches
    assert far is not None and 17.0 <= far.claw_in <= 24.0


def test_a_small_pale_puck_is_found_by_the_relaxed_pass_and_marked_relaxed():
    PALE = (116, 92, 78)                                                                      # a puck 12 inches out as the camera showed it: saturation 0.33, hue 19
    img = picture((114, 94, 122, 100, PALE))                                                  # 8 by 6 pixels
    assert pf.find_puck_array(img, by="row") is None                                          # the claw-120 look keeps the strict pass
    p = pf.find_puck_array(img, by="width")
    assert p is not None and p.relaxed and 10.0 <= p.claw_in <= 14.0
    strong = pf.find_puck_array(picture((113, 124, 127, 143, RED)), by="width")
    assert strong is not None and not strong.relaxed                                          # a clear puck is read by the strict pass, as before


def test_the_hardwood_grain_is_not_a_puck_by_hue_and_a_bright_yellow_face_is():
    GRAIN = (96, 86, 63)                                                                      # hue 40, dark: the false reads on the puck-free tub pictures
    assert pf.find_puck_array(picture((113, 104, 125, 113, GRAIN)), by="width") is None
    YELLOW_FACE = (153, 144, 102)                                                             # a yellow face at 6 inches in an older picture: hue 49, bright
    assert pf.find_puck_array(picture((113, 124, 127, 143, YELLOW_FACE)), by="width") is not None
    GREEN = (77, 109, 83)                                                                     # a green face 9 inches out
    assert pf.find_puck_array(picture((113, 104, 125, 113, GREEN)), by="width") is not None


def test_a_relaxed_reading_must_be_confirmed_by_a_second_picture_that_agrees():
    a = pf.PuckReading(120, 108, 12, 9, 80, 0.0, 8.0, relaxed=True)
    assert pf.readings_agree(a, pf.PuckReading(124, 106, 11, 9, 80, 4.0, 9.0))
    assert not pf.readings_agree(a, pf.PuckReading(150, 106, 11, 9, 80, 12.0, 8.0))            # 12 degrees off
    assert not pf.readings_agree(a, pf.PuckReading(120, 96, 8, 6, 40, 0.0, 14.0))              # 6 inches farther
    assert not pf.readings_agree(a, None) and not pf.readings_agree(None, a)


def test_a_puck_cut_off_at_the_bottom_of_the_floor_rows_is_marked_clipped():
    at_tip = pf.find_puck_array(picture((112, 186, 128, 215, RED)), by="width")        # runs on into the jaws: its lowest rows are hidden
    assert at_tip is not None and at_tip.clipped
    assert not pf.find_puck_array(picture((112, 124, 128, 143, RED))).clipped


def test_the_glare_and_specks_are_not_the_puck_and_a_far_puck_is_seen_in_a_claw_down_picture():
    GLARE = (150, 125, 92)                                                                  # hardwood glare: saturation 0.38, hue 34 (yellow-brown)
    assert pf.find_puck_array(picture((112, 124, 128, 143, GLARE))) is None                 # a puck-sized blob of it
    assert pf.find_puck_array(picture((124, 134, 128, 138, RED))) is None                   # 4 pixels wide at a row that means 6 inches: a speck
    far = pf.find_puck_array(picture((130, 86, 136, 92, RED)), by="width")                  # at the wall's base in a claw-down picture (rows 84 to 93)
    assert far is not None and far.claw_in >= 14.0
    assert pf.find_puck_array(picture((130, 86, 136, 92, RED))) is None                     # the claw-120 picture's floor starts at row 94


def test_a_sliver_or_a_blob_the_wrong_size_for_the_tub_is_not_a_puck_inside():
    """2026-11-25: a 14 by 1 sliver and a 1 by 8 sliver were read as pucks inside the tub (a glint, a tape edge)."""
    for box in ((98, 114, 112, 115, RED), (100, 112, 101, 120, RED)):                  # 14 by 1, 1 by 8
        img = tub_picture(box)
        assert pf.find_puck_in_tub_array(img, bf.find_basket_array(img)) is None, box
    big = tub_picture((92, 110, 160, 130, RED))                                         # wider than a puck can be on this tape (68 of 89)
    assert pf.find_puck_in_tub_array(big, bf.find_basket_array(big)) is None
    ok = tub_picture((105, 112, 115, 121, RED))                                        # 10 by 9: a puck
    assert pf.find_puck_in_tub_array(ok, bf.find_basket_array(ok)) is not None


def test_a_clear_puck_a_little_under_the_strict_saturation_is_read_compactly_by_the_first_relaxed_pass():
    """2026-11-26 goal run: pucks at 4 to 8 inches read 0.34 to 0.39 mean saturation against the strict 0.40, and the pixel threshold of the last pass grew them past the size limit; 6 of 8 were missed."""
    DULL = (123, 96, 78)                                                         # saturation 0.37, hue 24
    p = pf.find_puck_array(picture((112, 120, 126, 138, DULL)), by="width")      # 14 by 18 pixels
    assert p is not None and p.relaxed and p.width_px == 14 and p.height_px == 18


def test_a_big_blob_is_a_puck_only_close_up_in_a_claw_down_picture():
    # 2026-11-27 run: the puck 4 to 6 inches ahead was 22 by 32 and 32 by 37 pixels and read nothing against the 26 pixel side limit
    green = (60, 170, 70)
    near = pf.find_puck_array(picture((100, 130, 122, 162, green)), None, by="width")                # 22 x 32, centre row 146: about 4 inches
    assert near is not None and near.claw_in <= 6.0
    assert pf.find_puck_array(picture((100, 84, 122, 116, green)), None, by="width") is None         # the same size up the picture (a rug, a sofa at 11 inches or more)
    assert pf.find_puck_array(picture((100, 130, 122, 162, green))) is None                           # the claw-120 look keeps the old limit


def test_a_tall_big_blob_of_dull_colour_is_not_a_puck_but_a_flat_one_cropped_at_the_edge_is():
    # 2026-11-27 9:34 run: dark knots in the hardwood (22 by 32 to 21 by 40, found by the relaxed colour pass) were read as a puck 4 to 5 inches off
    dull = (160, 130, 100)
    assert pf.find_puck_array(picture((100, 130, 122, 162, dull)), None, by="width") is None         # 22 x 32: taller than wide by 1.45
    assert pf.find_puck_array(picture((100, 130, 130, 154, dull)), None, by="width") is not None     # 30 x 24: a puck seen near
