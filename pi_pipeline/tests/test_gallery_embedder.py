"""The gallery knows which embedder made its fingerprints, and tools/rebuild_gallery.py rebuilds it from the labelled pictures with another one (user, 2026-11-06)."""
import importlib.util
from pathlib import Path

import numpy as np

from pi_pipeline.vision import embedder as emb
from pi_pipeline.vision.object_gallery import ObjectGallery, ObjectGalleryConfig

SPEC = importlib.util.spec_from_file_location("rebuild_gallery", Path(__file__).resolve().parents[2] / "tools" / "rebuild_gallery.py")
RG = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RG)


def test_the_file_records_the_embedder_and_its_thresholds_and_they_apply_on_load(tmp_path):
    g = ObjectGallery(ObjectGalleryConfig(same_instance_threshold=0.58, near_duplicate_threshold=0.77))
    g.embedder = "dinov2_small.onnx#cls"
    g.consider([1.0, 0.0], quality=0.9)
    g.save(tmp_path / "g.json")
    h = ObjectGallery.load(tmp_path / "g.json", ObjectGalleryConfig(lock_by_holdout=True))
    assert h.embedder == "dinov2_small.onnx#cls" and h.cfg.same_instance_threshold == 0.58 and h.cfg.near_duplicate_threshold == 0.77 and h.cfg.lock_by_holdout
    legacy = ObjectGallery()
    legacy.consider([1.0, 0.0], quality=0.9)
    legacy.save(tmp_path / "old.json")
    assert ObjectGallery.load(tmp_path / "old.json").cfg.same_instance_threshold == 0.80                  # no embedder recorded: the config's own thresholds


def test_the_gallery_not_the_environment_picks_the_embedder_once_it_holds_fingerprints(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(emb, "make_embedder", lambda spec="histogram": (made.append(spec), type("E", (), {"key": spec})())[1])
    monkeypatch.setenv("G2_MODELS_DIR", str(tmp_path))
    recorded = ObjectGallery(); recorded.embedder = "dinov2_small.onnx#cls"
    emb.embedder_for(recorded, "histogram")
    assert made[-1] == f"onnx:{tmp_path}/dinov2_small.onnx#cls"                                         # the recorded model, found in the models folder
    legacy = ObjectGallery(); legacy.consider([1.0, 0.0], quality=0.9)
    emb.embedder_for(legacy, "onnx:/other.onnx")
    assert made[-1] == "histogram" and legacy.embedder == "histogram"                                    # an old gallery is histogram, and now says so
    fresh = ObjectGallery()
    emb.embedder_for(fresh, "histogram")
    assert fresh.embedder == "histogram"


def test_thresholds_sit_between_different_objects_and_the_same_object():
    same = np.array([0.80, 0.82, 0.85, 0.90, 0.95])
    diff = np.array([0.10, 0.20, 0.30, 0.40, 0.45])
    t_same, t_near = RG.choose_thresholds(same, diff)
    assert 0.45 < t_same < 0.80 and t_near >= t_same + 0.05


def test_a_rebuild_teaches_each_labelled_picture_to_a_fresh_gallery_under_its_name(tmp_path):
    rng = np.random.default_rng(1)
    centres = {"mug": np.array([1.0, 0, 0, 0]), "lamp": np.array([0, 1.0, 0, 0]), "cat": np.array([0, 0, 1.0, 0])}
    names, vecs, paths = [], [], []
    for n, c in centres.items():
        for i in range(4):
            v = c + rng.normal(0, 0.05, 4)
            names.append(n); vecs.append((v / np.linalg.norm(v)).astype(np.float32)); paths.append(tmp_path / n / f"{n}_{i}.jpg")
    vecs = np.vstack(vecs)
    same, diff = RG.similarity_groups(names, vecs)
    assert RG.leave_one_out(names, vecs) == 1.0 and same.mean() > diff.mean() + 0.5
    t_same, t_near = RG.choose_thresholds(same, diff)
    g = RG.build_gallery(names, vecs, paths, "test.onnx", t_same, t_near)
    assert g.embedder == "test.onnx" and {e.name for e in g.entries.values()} == {"mug", "lamp", "cat"} and all(e.name for e in g.entries.values())
    entry, sim = g.match(list(vecs[0]), named_only=True)
    assert entry.name == "mug" and sim >= t_same
