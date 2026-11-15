"""Gallery matches as bout detections (behavior/gallery_target.py): the named object's box becomes (label, similarity, cx, cy, w, h); unnamed, weak and wrong-name matches do not."""
import io

import numpy as np
from PIL import Image

from pi_pipeline.behavior.gallery_target import GalleryTargets


def jpeg():
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 255, (240, 240, 3), dtype=np.uint8)
    b = io.BytesIO()
    Image.fromarray(arr).save(b, "JPEG")
    return b.getvalue()


class Cand:
    def __init__(self, box):
        self.box = box


class Entry:
    def __init__(self, name):
        self.name = name


class Scorer:
    min_quality = 0.0

    def __init__(self, boxes):
        self.localizer = type("L", (), {"candidates": lambda s, im: [Cand(b) for b in boxes]})()
        self.embedder = type("E", (), {"embed": lambda s, crop: [1.0, 0.0]})()


class Gallery:
    def __init__(self, answers):
        self.answers = list(answers)

    def match(self, emb, named_only=True):
        return self.answers.pop(0)


def test_a_named_match_becomes_a_detection_with_the_boxs_centre_and_size():
    t = GalleryTargets(Scorer([(0.2, 0.3, 0.6, 0.7)]), Gallery([(Entry("toy body"), 0.62)]))
    d = t.detections(jpeg())
    assert len(d) == 1 and d[0][0] == "toy body" and d[0][1] == 0.62
    assert abs(d[0][2] - 0.4) < 1e-9 and abs(d[0][3] - 0.5) < 1e-9 and abs(d[0][4] - 0.4) < 1e-9 and abs(d[0][5] - 0.4) < 1e-9


def test_weak_unnamed_and_wrong_name_matches_are_left_out():
    boxes = [(0.0, 0.0, 0.3, 0.3), (0.4, 0.0, 0.7, 0.3), (0.5, 0.5, 0.9, 0.9)]
    gal = Gallery([(Entry("toy body"), 0.30), (Entry("couch"), 0.8), (Entry("toy body"), 0.50)])
    t = GalleryTargets(Scorer(boxes), gal, min_sim=0.45, target="toy")
    d = t.detections(jpeg())
    assert [x[0] for x in d] == ["toy body"] and d[0][1] == 0.50                      # the 0.30 is too weak, the couch is not the target
    assert GalleryTargets(Scorer([(0.1, 0.1, 0.5, 0.5)]), Gallery([(None, 0.9)])).detections(jpeg()) == []     # an unnamed match has no name to follow


def test_without_a_target_any_named_object_counts_and_a_bad_picture_gives_nothing():
    t = GalleryTargets(Scorer([(0.1, 0.1, 0.5, 0.5)]), Gallery([(Entry("couch"), 0.7)]))
    assert [x[0] for x in t.detections(jpeg())] == ["couch"]
    assert GalleryTargets(Scorer([(0.1, 0.1, 0.5, 0.5)]), Gallery([])).detections(b"not a jpeg") == []
