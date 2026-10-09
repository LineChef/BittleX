"""InterestScorer: unknown objects and unfinished named ones are worth a picture; people, finished objects and objects waiting for a name are not."""
import io

import pytest

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from pi_pipeline.vision.embedder import HistogramEmbedder  # noqa: E402
from pi_pipeline.vision.interest import InterestScorer, crop_quality  # noqa: E402
from pi_pipeline.vision.localizer import ForegroundLocalizer  # noqa: E402
from pi_pipeline.vision.object_gallery import ObjectGallery, ObjectGalleryConfig  # noqa: E402


def _picture(color, seed=0):
    rng = np.random.default_rng(seed)
    img = np.empty((240, 240, 3), dtype=float)
    img[:] = (150, 120, 90)
    img += rng.normal(0, 3, img.shape)
    img[100:205, 90:150] = color
    img[100:205, 90:150] += rng.normal(0, 14, (105, 60, 3))        # texture, so the crop has edges and counts as sharp
    buf = io.BytesIO()
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


class Snap:
    def __init__(self, jpeg, detections=()):
        self.jpeg, self.detections = jpeg, list(detections)


def _scorer(gallery=None, veto=("face", "person")):
    return InterestScorer(ForegroundLocalizer(), HistogramEmbedder(), gallery or ObjectGallery(ObjectGalleryConfig()), veto_labels=lambda: veto)


def _embed_of(jpeg):
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    return [float(v) for v in HistogramEmbedder().embed(im.crop((90, 100, 150, 205)))]


def test_an_object_that_matches_nothing_is_unknown_and_a_person_vetoes_the_picture():
    s = _scorer()
    got = s.assess(Snap(_picture((30, 60, 160))))
    assert got.kind == "unknown" and got.box is not None
    assert s.assess(Snap(_picture((30, 60, 160)), [("face", 0.8, 0.5, 0.5, 0.2, 0.2)])).kind == "vetoed"
    assert s.assess(Snap(_picture((30, 60, 160)), [("face", 0.1, 0.5, 0.5, 0.2, 0.2)])).kind == "unknown"      # a weak detection is not a person
    assert _scorer(veto=("sam",)).assess(Snap(_picture((30, 60, 160)), [("sam", 0.9, 0.5, 0.5, 0.2, 0.2)])).kind == "vetoed"   # a roster name too


def test_a_named_unfinished_object_is_reinforced_and_a_locked_one_is_left_alone():
    jpeg = _picture((180, 40, 40))
    g = ObjectGallery(ObjectGalleryConfig())
    g.consider(_embed_of(jpeg), quality=1.0)
    eid = g.last_entry_id
    g.set_name(eid, "red mug")
    got = _scorer(g).assess(Snap(jpeg))
    assert got.kind == "reinforce" and got.name == "red mug"
    g.mark_complete(eid)
    assert _scorer(g).assess(Snap(jpeg)).kind == "none"


def test_an_unnamed_candidate_with_enough_pictures_is_left_until_it_gets_a_name():
    jpeg = _picture((40, 160, 70))
    g = ObjectGallery(ObjectGalleryConfig(near_duplicate_threshold=1.01))
    for _ in range(3):
        g.consider(_embed_of(jpeg), quality=1.0)
    assert g.entries[g.last_entry_id].sample_count == 3
    assert _scorer(g).assess(Snap(jpeg)).kind == "none"


def test_crop_quality_prefers_big_sharp_well_lit_crops():
    rng = np.random.default_rng(1)
    sharp = rng.integers(60, 200, (80, 80, 3), dtype=np.uint8)
    flat = np.full((80, 80, 3), 120, dtype=np.uint8)
    dark = (sharp // 8).astype(np.uint8)
    tiny = sharp[:10, :10]
    assert crop_quality(sharp) > crop_quality(flat) and crop_quality(sharp) > crop_quality(dark) and crop_quality(sharp) > crop_quality(tiny)
