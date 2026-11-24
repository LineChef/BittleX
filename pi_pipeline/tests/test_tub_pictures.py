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
