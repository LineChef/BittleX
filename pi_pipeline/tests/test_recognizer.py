"""vision/embedder.py, localizer.py, recognizer.py: the object recognition pipeline on synthetic pictures (no model file, no camera)."""
import io

import numpy as np
import pytest
from PIL import Image

from pi_pipeline.vision.embedder import HistogramEmbedder, make_embedder, to_image
from pi_pipeline.vision.localizer import GridLocalizer, grid_boxes
from pi_pipeline.vision.object_gallery import GalleryDecision, ObjectGallery, ObjectGalleryConfig
from pi_pipeline.vision.recognizer import Recognizer


def _scene(bg=(120, 110, 100), obj=None, box=(0.1, 0.1, 0.4, 0.4), size=240, seed=0):
    rng = np.random.default_rng(seed)
    a = np.full((size, size, 3), bg, dtype=np.uint8)
    a = np.clip(a.astype(int) + rng.integers(-6, 7, a.shape), 0, 255).astype(np.uint8)
    if obj is not None:
        x0, y0, x1, y1 = (int(v * size) for v in box)
        a[y0:y1, x0:x1] = obj
        a[y0:y1, x0:x0 + 4] = (255, 255, 255)           # an edge that gives the object a texture of its own
    return Image.fromarray(a)


def test_histogram_embedder_is_unit_length_deterministic_and_takes_bytes_arrays_and_images():
    e = HistogramEmbedder()
    im = _scene(obj=(200, 30, 30))
    v = e.embed(im)
    assert v.shape == (e.dim,) and abs(float(np.linalg.norm(v)) - 1.0) < 1e-5
    buf = io.BytesIO(); im.save(buf, "JPEG")
    assert np.allclose(e.embed(im), e.embed(np.asarray(im))) and e.embed(buf.getvalue()).shape == (e.dim,)
    assert to_image(np.asarray(im)).size == (240, 240)


def test_a_similar_picture_is_closer_than_a_different_one():
    e = HistogramEmbedder()
    red_a, red_b = e.embed(_scene(obj=(200, 30, 30), seed=1)), e.embed(_scene(obj=(205, 35, 28), seed=2, box=(0.12, 0.1, 0.42, 0.4)))
    blue = e.embed(_scene(obj=(30, 40, 200), seed=3))
    assert float(red_a @ red_b) > float(red_a @ blue) + 0.03


def test_grid_boxes_cover_the_picture_with_the_asked_overlap():
    boxes = grid_boxes(3, 0.5)
    assert len(boxes) == 9 and boxes[0][:2] == (0.0, 0.0) and abs(boxes[-1][2] - 1.0) < 1e-9 and abs(boxes[-1][3] - 1.0) < 1e-9
    (x0, _, x1, _), (nx0, _, _, _) = boxes[0], boxes[1]
    assert abs((x1 - nx0) / (x1 - x0) - 0.5) < 1e-9                       # neighbours share half a tile
    views = GridLocalizer(3, 0.5).views(_scene())
    assert len(views) == 10 and views[0][0].whole and views[0][1].size == (240, 240) and not views[1][0].whole


def test_the_recognizer_learns_a_named_object_and_finds_it_in_a_busier_scene_by_tile():
    rec = Recognizer(HistogramEmbedder(), ObjectGallery(ObjectGalleryConfig(same_instance_threshold=0.80)))
    mug = _scene(bg=(120, 110, 100), obj=(200, 30, 30), box=(0.05, 0.05, 0.95, 0.95), seed=4)       # the mug fills the picture
    assert rec.learn_named(mug, "mug") in (GalleryDecision.NEW, GalleryDecision.ADD_SAMPLE)
    assert rec.gallery.entries and next(iter(rec.gallery.entries.values())).name == "mug"
    seen = rec.recognize(_scene(obj=(200, 30, 30), box=(0.0, 0.0, 0.45, 0.45), seed=5))              # a mug in one corner of a bigger scene
    assert [r.name for r in seen] == ["mug"] and seen[0].similarity >= rec.threshold
    assert rec.recognize(_scene(obj=(30, 40, 200), box=(0.0, 0.0, 0.45, 0.45), seed=6)) == []                    # a blue object is not the mug

def test_a_look_alike_of_a_differently_named_entry_is_not_renamed():
    rec = Recognizer(HistogramEmbedder(), ObjectGallery(ObjectGalleryConfig(same_instance_threshold=0.70)))
    a = _scene(obj=(200, 30, 30), box=(0.05, 0.05, 0.95, 0.95), seed=7)
    rec.learn_named(a, "mug")
    out = rec.learn_named(_scene(obj=(202, 32, 30), box=(0.05, 0.05, 0.95, 0.95), seed=8), "cup")
    assert out is None and rec.last_conflict[0] == "mug" and {e.name for e in rec.gallery.entries.values()} == {"mug"}


def test_make_embedder_names_and_errors():
    assert isinstance(make_embedder("histogram"), HistogramEmbedder) and isinstance(make_embedder(""), HistogramEmbedder)
    with pytest.raises(ValueError):
        make_embedder("clip")


def test_pool_output_handles_flat_feature_map_and_class_token_outputs():
    from pi_pipeline.vision.embedder import pool_output
    flat = pool_output(np.array([[3.0, 4.0]]))
    assert np.allclose(flat, [0.6, 0.8])
    fmap = np.ones((1, 4, 2, 2), dtype=np.float32) * np.array([1, 2, 3, 4], dtype=np.float32).reshape(1, 4, 1, 1)
    assert pool_output(fmap).shape == (4,)
    tokens = np.zeros((1, 5, 3), dtype=np.float32)
    tokens[0, 0] = [1, 0, 0]; tokens[0, 1:] = [0, 2, 0]
    assert np.allclose(pool_output(tokens, "cls"), [1, 0, 0]) and np.allclose(pool_output(tokens, "mean"), [0, 1, 0])
    both = pool_output(tokens)
    assert both.shape == (6,) and abs(float(np.linalg.norm(both)) - 1.0) < 1e-6
    with pytest.raises(ValueError):
        pool_output(tokens, "max")
