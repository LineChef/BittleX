"""The class cap (owner-approved 2026-11-17): the chase's picture saver and the shared scoring module."""
import io
import json

import numpy as np
from PIL import Image

from pi_pipeline.behavior import ball_chase as bc
from pi_pipeline.vision import picture_score as ps


def jpeg(seed: int, sharp: bool = True) -> bytes:
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 255, (240, 240), dtype=np.uint8) if sharp else np.full((240, 240), 120, dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(np.stack([a, a, a], axis=2)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def ball():
    return bc.BallReading(120.0, 150.0, 100, 12, 12, 12.0, 20.0, 0.0, False, "normal")


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): self.t += 10.0; return self.t


def test_the_saver_stores_the_score_and_skips_poor_and_repeated_pictures(tmp_path):
    s = bc.PictureSaver(str(tmp_path), clock=Clock())
    s.maybe_save(jpeg(1, sharp=False), ball())                              # flat grey: poor
    s.maybe_save(jpeg(2), ball())
    s.maybe_save(jpeg(2), ball())                                           # the same picture again: a near-twin of one just saved
    s.maybe_save(jpeg(3), ball())
    assert s.saved == 2 and s.skipped == {"poor": 1, "same as a recent one": 1}
    side = json.loads(sorted(tmp_path.glob("*.json"))[0].read_text())
    assert 0.0 < side["quality"] <= 1.3


def test_a_session_adds_at_most_forty_pictures(tmp_path):
    s = bc.PictureSaver(str(tmp_path), clock=Clock())
    s.SESSION_MAX_SAVES = 3
    for i in range(10):
        s.maybe_save(jpeg(100 + i), ball())
    assert s.saved == 3 and s.skipped.get("full") == 7


def test_at_the_class_cap_a_better_picture_replaces_the_worst_and_a_worse_one_is_not_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "CLASS_CAP", 3)
    for i, q in enumerate((0.9, 0.8, 0.2)):                                  # three kept pictures with stored scores
        (tmp_path / f"greenball_x_{i}.jpg").write_bytes(b"x")
        (tmp_path / f"greenball_x_{i}.json").write_text(json.dumps({"quality": q}))
    s = bc.PictureSaver(str(tmp_path), clock=Clock())
    s.maybe_save(jpeg(7), ball())                                            # a sharp noisy picture scores far above 0.2
    assert not (tmp_path / "greenball_x_2.jpg").exists() and len(list(tmp_path.glob("greenball_*.jpg"))) == 3
    monkeypatch.setattr(ps, "quality", lambda m, found=True: 0.1)            # now a worse one: not kept, nothing removed
    s.maybe_save(jpeg(8), ball())
    assert len(list(tmp_path.glob("greenball_*.jpg"))) == 3 and s.skipped.get("not better than the worst") == 1


def test_replace_victim_rules():
    assert ps.replace_victim({"a": 0.5}, 0.9, cap=3) is None                  # room left
    assert ps.replace_victim({"a": 0.9, "b": 0.4, "c": None}, 0.5, cap=3) == "c"   # an unscored one is the first to go
    assert ps.replace_victim({"a": 0.9, "b": 0.8, "c": 0.7}, 0.5, cap=3) == ""     # not better than the worst
