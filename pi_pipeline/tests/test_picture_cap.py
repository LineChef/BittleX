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


def test_the_balls_colour_is_remembered_between_sessions_only_when_switched_on(tmp_path, monkeypatch):
    from pi_pipeline.behavior import ball_color_store as store
    monkeypatch.setattr(store, "PATH", str(tmp_path / "ball_color.json"))
    monkeypatch.setattr(store, "ENABLED", False)
    monkeypatch.setattr(store, "_samples", [])
    store.note((120, 160, 120))
    assert store.load() is None and not (tmp_path / "ball_color.json").exists()          # off: nothing is written (tests and tools)
    store.enable()
    for c in ((120, 160, 120), (124, 168, 124), (126, 166, 122)):
        store.note(c)
    assert store.load() == (120, 160, 120)                                             # saved by the first sample; the later medians are within 6 of it, so not saved again
    before = (tmp_path / "ball_color.json").read_text()
    store.note((125, 165, 123))                                                        # a small move: not saved again
    assert (tmp_path / "ball_color.json").read_text() == before
    monkeypatch.setattr(store, "_samples", [])
    for _ in range(9):
        store.note((100, 140, 100))                                                    # a lasting change: saved
    assert store.load() == (100, 140, 100)


def test_a_chase_starts_with_the_remembered_colour_and_the_sample_is_noted(tmp_path, monkeypatch):
    from pi_pipeline.behavior import ball_chase as bc
    from pi_pipeline.behavior import ball_color_store as store
    monkeypatch.setattr(store, "PATH", str(tmp_path / "ball_color.json"))
    monkeypatch.setattr(store, "_samples", [])
    store.enable()
    monkeypatch.setattr(store, "ENABLED", True)
    store.note((110, 150, 112))
    planner = bc.ChasePlanner()
    planner.decide(bc.BallReading(120.0, 150.0, 900, 30, 30, 30.0, 8.0, 0.0, False, "normal", color=(111, 151, 113)))
    assert planner.ball_color == (111, 151, 113) and store.load() == (110, 150, 112)   # a close reading sets the colour at once; the saved median only moves past a 6 difference
    import inspect
    assert "ball_color_store.load()" in inspect.getsource(bc._chase_loop)
