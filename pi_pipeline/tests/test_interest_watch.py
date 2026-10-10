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
    w = InterestWatch(Scorer(["none", "unknown", "vetoed"]), Src(), fresh_s=20.0, fallback_s=300.0, clock=lambda: t[0], rng=lambda: 0.5)
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


def test_a_wall_in_view_is_not_judged_an_object_and_the_fallback_interval_is_random():
    scorer = Scorer(["unknown", "unknown"])
    w = InterestWatch(scorer, Src(), clock=lambda: 0.0)
    w.skip_scoring = lambda: True
    assert w.peek_once() is None and w.latest is None and scorer.__dict__.get("calls", 0) == 0          # a wall's base never becomes a picture stop
    w.skip_scoring = lambda: False
    assert w.peek_once() is not None
    lo = InterestWatch(Scorer([]), Src(), fallback_s=300.0, rng=lambda: 0.0)._fallback_due
    hi = InterestWatch(Scorer([]), Src(), fallback_s=300.0, rng=lambda: 1.0)._fallback_due
    assert round(lo) == 180 and round(hi) == 420                # 0.6 to 1.4 times the base, not a clock


def test_the_exploration_session_really_passes_the_fallback_setting_to_the_watch():
    """2026-10-10: the `fallback_s=` argument sat inside a trailing comment, so G2_INTEREST_FALLBACK_S never reached the watch."""
    import inspect
    from pi_pipeline import explore_session
    src = inspect.getsource(explore_session)
    code_lines = [l.split("#")[0] for l in src.splitlines()]
    assert any('fallback_s=float(os.environ.get("G2_INTEREST_FALLBACK_S"' in l for l in code_lines)
