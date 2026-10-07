"""tools/curate_exploration.py on synthetic pictures: quality rejects, people set aside, near-duplicates, named pictures flagged not rejected,
the manifest and contact sheets, and the input folder left untouched. No hardware, no network."""
import importlib.util
import json
import os
import sys

import pytest

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "curate_exploration.py")


@pytest.fixture(scope="module")
def ce():
    spec = importlib.util.spec_from_file_location("curate_exploration_under_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod                     # dataclasses look the module up by name
    spec.loader.exec_module(mod)
    return mod


def textured(seed, mean=110.0, std=40.0):
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(mean, std, (240, 240)), 0, 255).astype("uint8")


def blocky(seed, mean=110.0):
    """Large soft blocks plus fine noise: a stable average hash (pure noise averages out to a near-uniform 16 x 16 and flips bits on rounding)."""
    rng = np.random.default_rng(seed)
    base = np.kron(rng.normal(mean, 45.0, (8, 8)), np.ones((30, 30)))
    return np.clip(base + rng.normal(0, 12.0, (240, 240)), 0, 255).astype("uint8")


def save(folder, fname, arr, **meta):
    os.makedirs(folder, exist_ok=True)
    Image.fromarray(arr).convert("RGB").save(os.path.join(folder, fname + ".jpg"), quality=95)
    base = {"file": fname + ".jpg", "pose": meta.pop("pose", "after_bow"), "name": meta.pop("name", None), "time": meta.pop("time", "2026-10-07 10:00:00"), "detections": meta.pop("detections", [])}
    json.dump(base, open(os.path.join(folder, fname + ".json"), "w"))


def build(root):
    sv = os.path.join(root, "survey", "20261007")
    save(sv, "after_bow_100000", textured(1), time="2026-10-07 10:00:00")                                   # good
    save(sv, "after_bow_100100", textured(1) // 1, time="2026-10-07 10:01:00")                            # exact repeat -> duplicate
    save(sv, "after_bow_100200", textured(2), time="2026-10-07 10:02:00")                                   # good, different view
    save(sv, "after_bow_100300", np.full((240, 240), 6, "uint8"), time="2026-10-07 10:03:00")              # too dark
    save(sv, "after_bow_100400", np.full((240, 240), 252, "uint8"), time="2026-10-07 10:04:00")            # blown out
    save(sv, "after_bow_100500", np.tile(np.linspace(80, 140, 240).astype("uint8"), (240, 1)), time="2026-10-07 10:05:00")   # smooth gradient: blurry
    save(sv, "after_bow_100600", textured(3), time="2026-10-07 10:06:00",
         detections=[{"label": "face", "score": 0.9, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2}])         # a person
    save(sv, "after_bow_100700", textured(4), time="2026-10-07 10:07:00",
         detections=[{"label": "dog", "score": 0.9, "cx": 0.5, "cy": 0.5, "w": 0.3, "h": 0.3}])          # a dog is not a person
    nm = os.path.join(root, "named", "mug")
    save(nm, "mug_110000_000", textured(10), pose="named", name="Mug", time="2026-10-07 11:00:00")
    save(nm, "mug_110100_000", textured(11), pose="named", name="Mug", time="2026-10-07 11:01:00")
    save(nm, "mug_110200_000", np.full((240, 240), 8, "uint8"), pose="named", name="Mug", time="2026-10-07 11:02:00")    # dark but named: weak, kept
    with open(os.path.join(sv, "broken_1.jpg"), "wb") as f:
        f.write(b"not a jpeg")


def status_of(m, name):
    return next(r for r in m["pictures"] if r["file"].endswith(name + ".jpg"))


def test_pipeline_fates_and_outputs(ce, tmp_path):
    src, out = tmp_path / "in", tmp_path / "out"
    build(str(src))
    before = sorted(os.listdir(src / "survey" / "20261007"))
    m = ce.curate(str(src), str(out))
    fate = lambda n: status_of(m, n)["status"]
    assert fate("after_bow_100000") == "kept" and fate("after_bow_100200") == "kept" and fate("after_bow_100700") == "kept"
    assert fate("after_bow_100100") == "duplicate" and status_of(m, "after_bow_100100")["duplicate_of"].endswith("after_bow_100000.jpg")
    assert status_of(m, "after_bow_100300")["reason"] == "too_dark"
    assert status_of(m, "after_bow_100400")["reason"] == "blown_out"
    assert status_of(m, "after_bow_100500")["reason"] == "blurry"
    assert fate("after_bow_100600") == "people" and fate("broken_1") == "rejected" and status_of(m, "broken_1")["reason"] == "unreadable"
    assert fate("mug_110000_000") == "kept" and fate("mug_110200_000") == "weak" and status_of(m, "mug_110200_000")["reason"] == "too_dark"
    assert sorted(os.listdir(src / "survey" / "20261007")) == before                          # input untouched
    keep = out / "keep"
    assert (keep / "survey" / "20261007" / "after_bow_100000.jpg").exists() and (keep / "survey" / "20261007" / "after_bow_100000.json").exists()
    assert (keep / "named" / "mug" / "mug_110200_000.jpg").exists()                           # weak named pictures are still kept
    assert (out / "rejects" / "too_dark").exists() and (out / "rejects" / "blown_out").exists() and (out / "rejects" / "duplicate").exists()
    assert not any("100600" in f for _r, _d, fs in os.walk(out) for f in fs)                     # the person picture is never copied
    assert (out / "contact" / "survey__20261007.jpg").exists() and (out / "contact" / "named__mug.jpg").exists()
    assert json.load(open(out / "manifest.json"))["summary"]["by_status"]["people"] == 1
    assert "Named objects" in (out / "summary.txt").read_text()


def test_best_of_a_duplicate_cluster_is_kept_and_hints_are_given(ce, tmp_path):
    src = tmp_path / "in"
    nm = str(src / "named" / "ball")
    img = blocky(5)
    save(nm, "ball_1", np.clip(img.astype(int) * 0.6, 0, 255).astype("uint8"), pose="named", name="Ball", time="2026-10-07 11:00:00")    # dim copy
    save(nm, "ball_2", img, pose="named", name="Ball", time="2026-10-07 11:01:00")                                                          # the better one
    m = ce.curate(str(src), str(tmp_path / "out"))
    assert status_of(m, "ball_2")["status"] == "kept" and status_of(m, "ball_1")["status"] == "duplicate"
    assert any("'Ball'" in h and "only 1 usable" in h for h in m["summary"]["hints"])


def test_a_pose_with_mostly_rejects_gets_a_hint(ce, tmp_path):
    src = tmp_path / "in"
    d = str(src / "survey" / "20261007")
    for i in range(5):
        save(d, f"look_up_{i}", np.full((240, 240), 5 + i, "uint8"), pose="look_up", time=f"2026-10-07 10:0{i}:00")
    m = ce.curate(str(src), str(tmp_path / "out"), write=False)
    assert not (tmp_path / "out").exists()                                                      # write=False copies nothing
    assert any("'look_up'" in h and "rejected" in h for h in m["summary"]["hints"])
