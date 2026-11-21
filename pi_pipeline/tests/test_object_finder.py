"""The colour finders for the cylinder and the basket (vision/object_finder.py) and the made-or-missed call (goals/basket_outcome.py), on synthetic pictures."""
import numpy as np

from pi_pipeline.goals import basket_outcome as bo
from pi_pipeline.vision import object_finder as of

RED, YELLOW = (200, 50, 50), (210, 190, 40)
BASKET = of.ObjectSpec("basket", RED, width_in=12.0)


def picture(*boxes):
    """A 240 x 240 gray floor with filled boxes (x0, y0, x1, y1, colour)."""
    img = np.full((240, 240, 3), 110, dtype=np.int16)
    for x0, y0, x1, y1, c in boxes:
        img[y0:y1, x0:x1] = c
    return img


def test_the_basket_is_found_by_its_colour_with_its_width_bearing_and_distance():
    r = of.find_object_array(picture((90, 120, 150, 170, RED)), BASKET)
    assert r is not None and abs(r.width_px - 60) <= 3
    assert abs(r.distance_in - of.FOCAL_PX * 12.0 / r.width_px) < 0.01 and 20 <= r.distance_in <= 24      # a 12 in basket 60 px wide is about 22 in away
    assert abs(r.bearing_deg) < 2 and not r.touches_edge
    right = of.find_object_array(picture((150, 120, 210, 170, RED)), BASKET)
    assert right.bearing_deg > 10                                                                         # to G2's right is positive


def test_nothing_is_found_for_the_wrong_colour_a_speck_or_a_blob_above_the_horizon():
    assert of.find_object_array(picture((90, 120, 150, 170, YELLOW)), BASKET) is None
    assert of.find_object_array(picture((100, 150, 104, 154, RED)), BASKET) is None                      # too small
    assert of.find_object_array(picture((90, 10, 150, 40, RED)), BASKET) is None                         # on the wall, above the horizon
    assert of.find_object_array(picture(), BASKET) is None


def test_the_cylinder_needs_two_touching_bands_and_one_band_alone_is_not_it():
    bands = [of.ObjectSpec("red", RED, 1.0, min_area=20), of.ObjectSpec("yellow", YELLOW, 1.0, min_area=20)]
    both = picture((100, 150, 118, 162, RED), (118, 150, 136, 162, YELLOW))
    r = of.find_cylinder_array(both, bands, length_in=3.0)
    assert r is not None and r.name == "cylinder" and r.left <= 101 and r.right >= 135
    assert of.find_cylinder_array(picture((100, 150, 118, 162, RED)), bands, 3.0) is None
    far = picture((20, 150, 38, 162, RED), (200, 150, 218, 162, YELLOW))                                  # the two colours far apart: two things, not one cylinder
    assert of.find_cylinder_array(far, bands, 3.0) is None


def reading(x, y, left, right, top, bottom, bearing=0.0, name="x"):
    return of.ObjectReading(name, x, y, left, right, top, bottom, 100, right - left + 1, 20.0, bearing, False)


def test_the_throw_is_made_missed_or_unknown_from_what_the_finders_saw():
    basket = reading(120, 150, 90, 150, 120, 170, name="basket")
    assert bo.classify_throw(basket, reading(120, 140, 112, 128, 134, 146, name="cylinder"))[0] == bo.MADE
    assert bo.classify_throw(basket, reading(200, 190, 192, 208, 184, 196, bearing=25.0, name="cylinder"))[0] == bo.MISSED
    assert bo.classify_throw(basket, None)[0] == bo.NOT_SEEN                                              # maybe inside, maybe out of view: not a make
    assert bo.classify_throw(None, reading(120, 140, 112, 128, 134, 146))[0] == bo.NO_BASKET             # the look missed the basket: never a make or a miss
