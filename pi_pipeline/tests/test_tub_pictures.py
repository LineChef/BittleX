"""The tub finders on the pictures that calibrated them (the `tub` recognition set, Mac only: skipped where it is absent). A regression guard on the 2026-11-24 pictures, NOT a validation: the thresholds were set from these very pictures, and the make check needs held-out pictures and a live trial."""
import json
import os
from pathlib import Path

import numpy as np
import pytest

from pi_pipeline.vision import basket_finder as bf
from pi_pipeline.vision import puck_finder as pf

import pwd

SET = Path(pwd.getpwuid(os.getuid()).pw_dir) / "Desktop/G2Memory/g2_pictures/recognition_sets/tub"          # the real home: the test sandbox moves $HOME (this test only reads)
if not (SET / "labels.json").exists():
    pytest.skip("the tub recognition set is only on the owner's Mac", allow_module_level=True)


def load():
    from PIL import Image
    labels = json.loads((SET / "labels.json").read_text())
    out = []
    for k, v in sorted(labels.items()):
        f = SET / f"{k}.jpg"
        if f.exists():
            out.append((v["label"], v.get("distance_in"), np.asarray(Image.open(f).convert("RGB")).astype(np.int16)))
    return out


def test_the_tape_is_found_in_every_picture_within_two_inches_where_the_distance_is_known():
    pics = load()
    assert len(pics) >= 30
    for label, dist, im in pics:
        r = bf.find_basket_array(im)
        assert r is not None, label
        if dist is not None and "left" not in label and "right" not in label and "offset" not in label:          # the shifted pictures read the tape's far end short
            assert abs(r.claw_in - float(dist)) <= 2.1, (label, dist, r.claw_in)


def test_at_eight_inches_a_puck_inside_is_read_inside_and_every_other_case_is_not():
    n = 0
    for label, _d, im in load():
        if not label.startswith("tub_8in_"):
            continue
        n += 1
        r = bf.find_basket_array(im)
        inside = pf.find_puck_in_tub_array(im, r)
        assert (inside is not None) == ("inside" in label), label
        floor = pf.find_puck_array(im, r)
        if "inside" in label or label in ("tub_8in_empty", "tub_8in_past"):
            assert floor is None, label                                                                   # nothing on the floor
        else:
            assert floor is not None, label                                                               # a puck outside the tub is found on the floor
    assert n >= 13


def test_tape_that_comes_as_two_thin_pieces_on_the_same_rows_is_one_strip_and_a_puck_is_never_joined_to_it():
    """2026-11-25: at about 24 inches the tape came as two pieces (15 and 17 pixels, a gap of 8), each too short to seed: the look said no basket with the tub in front of him."""
    import numpy as np
    from pi_pipeline.vision import basket_finder as bf

    def pic(pieces):
        a = np.full((240, 240, 3), 90, dtype=np.uint8)
        for (x0, x1, y0, y1) in pieces:
            a[y0:y1, x0:x1] = (200, 60, 50)
        return a
    r = bf.find_basket_array(pic([(96, 111, 88, 90), (119, 136, 88, 91)]))
    assert r is not None and 38 <= r.width_px <= 44 and abs(r.bearing_deg) < 5 and 22.0 < r.claw_in < 26.0
    assert bf.find_basket_array(pic([(96, 111, 88, 90)])) is None                                    # one short piece alone is still not a tub
    assert bf.find_basket_array(pic([(96, 111, 88, 90), (160, 176, 88, 91)])) is None               # a gap of 49 columns is two things, not one strip
    r2 = bf.find_basket_array(pic([(96, 111, 88, 90), (119, 136, 88, 91), (114, 122, 92, 104)]))     # a puck-shaped red blob below the tape (8 by 12) is not joined to it
    assert r2 is not None and 38 <= r2.width_px <= 44


def test_the_dim_light_tape_is_found_by_the_second_try_and_the_strict_readings_are_unchanged():
    """2026-11-25: the tape read (169, 103, 87) at 22 inches in the morning light, red minus green 66 under the seed test's 70; a second, looser seed finds it, and only when the strict one found nothing."""
    import numpy as np
    from pi_pipeline.vision import basket_finder as bf

    def pic(color, x0=96, x1=140, y0=88, y1=91):
        a = np.full((240, 240, 3), 90, dtype=np.uint8)
        a[y0:y1, x0:x1] = color
        return a
    dim = bf.find_basket_array(pic((169, 103, 87)))
    assert dim is not None and 40 <= dim.width_px <= 48 and 20.0 < dim.claw_in < 26.0                  # found only by the dim test
    assert bf._find_basket(pic((169, 103, 87)), bf.TAPE_STRICT) is None
    strict_pic = pic((240, 115, 105))
    a, b = bf.find_basket_array(strict_pic), bf._find_basket(strict_pic, bf.TAPE_STRICT)
    assert a is not None and a == b                                                                      # the calibrated colour: the same reading as before
    assert bf.find_basket_array(pic((140, 120, 110))) is None                                            # a brownish strip (floor, wood) is still not tape
    assert bf.find_basket_array(pic((169, 103, 87), x0=96, x1=108)) is None                              # and a short one is not a tub
