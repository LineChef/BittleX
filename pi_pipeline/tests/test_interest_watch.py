"""InterestWatch: picture stops follow what is worth a picture, with a slow fallback; the survey gate; the gallery feeder."""
import io
import json

import pytest

from pi_pipeline.behavior.interest_watch import InterestWatch
from pi_pipeline.behavior.survey import Survey, SurveyConfig
from pi_pipeline.vision.interest import Interest


class Scorer:
    def __init__(self, kinds):
        self.kinds = list(kinds)

    def assess(self, snap):
        k = self.kinds.pop(0)
        return Interest(k, f"test {k}")


class Src:
    def snapshot(self, timeout_s=6.0, settle=None):
        return object()


def test_the_gate_opens_for_something_interesting_once_then_only_for_the_slow_fallback():
    t = [100.0]
    w = InterestWatch(Scorer(["none", "unknown", "vetoed"]), Src(), fresh_s=20.0, fallback_s=300.0, clock=lambda: t[0])
    w.peek_once(100.0)
    assert not w.gate(105.0)                                   # nothing interesting
    w.peek_once(110.0)
    assert w.gate(115.0) and not w.gate(116.0)                 # the unknown object: a stop, once
    w.peek_once(120.0)
    assert not w.gate(125.0) and w.vetoes == 1                 # a person: never
    assert w.gate(115.0 + 301.0)                               # no stop for 300 s: the fallback
    w2 = InterestWatch(Scorer(["reinforce"]), Src(), fresh_s=20.0, clock=lambda: t[0])
    w2.peek_once(200.0)
    assert not w2.gate(230.0)                                  # a sighting older than fresh_s is dropped


def test_the_survey_asks_the_gate_after_its_own_cooldown():
    s = Survey(SurveyConfig(cooldown_s=15.0), clock=lambda: 100.0)
    s.began(100.0)
    calls = []
    s.gate = lambda now: calls.append(now) or True
    assert not s.ready(110.0) and calls == []                 # inside the cooldown the gate is not even asked
    assert s.ready(116.0) and calls == [116.0]                # after it, the gate decides
    s.gate = lambda now: False
    assert not s.ready(130.0)
    no_gate = Survey(SurveyConfig(cooldown_s=15.0), clock=lambda: 100.0)
    assert no_gate.ready(100.0)                               # without a gate the survey behaves as before


def test_the_feeder_gives_each_saved_picture_to_the_gallery_and_skips_people(tmp_path):
    np = pytest.importorskip("numpy")
    PIL = pytest.importorskip("PIL")
    from PIL import Image
    from pi_pipeline.behavior.interest_watch import GalleryFeeder
    from pi_pipeline.vision.embedder import HistogramEmbedder
    from pi_pipeline.vision.interest import InterestScorer
    from pi_pipeline.vision.localizer import ForegroundLocalizer
    from pi_pipeline.vision.object_gallery import ObjectGallery, ObjectGalleryConfig
    rng = np.random.default_rng(0)
    img = np.empty((240, 240, 3), dtype=float)
    img[:] = (150, 120, 90)
    img += rng.normal(0, 3, img.shape)
    img[100:205, 90:150] = (30, 60, 160)
    img[100:205, 90:150] += rng.normal(0, 14, (105, 60, 3))
    f = tmp_path / "after_bow_1.jpg"
    Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).save(f, "JPEG", quality=95)
    g = ObjectGallery(ObjectGalleryConfig())
    feeder = GalleryFeeder(InterestScorer(ForegroundLocalizer(), HistogramEmbedder(), g), g, str(tmp_path / "gal" / "gallery.json"))
    feeder(f)
    assert feeder.added == 1 and len(g.entries) == 1 and (tmp_path / "gal" / "gallery.json").exists()
    f.with_suffix(".json").write_text(json.dumps({"detections": [{"label": "face", "score": 0.9}]}))
    feeder(f)
    assert feeder.skipped == 1 and len(g.entries) == 1         # a picture with a person is not used


def test_other_readers_get_the_same_peek():
    seen = []
    w = InterestWatch(Scorer(["none"]), Src())
    w.on_snap = seen.append
    w.peek_once(1.0)
    assert len(seen) == 1
