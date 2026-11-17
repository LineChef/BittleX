"""tools/g2_groom.py: only the allowlisted folders are touched, calibration pictures never, hand-named never, and nothing is deleted at once."""
import importlib.util
import io
import json
import os

import numpy as np
from PIL import Image

spec = importlib.util.spec_from_file_location("g2_groom", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "g2_groom.py"))
gm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gm)


def pic(path, seed, named_by=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 255, (240, 240), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(np.stack([a, a, a], axis=2)).save(buf, "JPEG", quality=95)
    open(path, "wb").write(buf.getvalue())
    if named_by:
        json.dump({"named_by": named_by}, open(os.path.splitext(path)[0] + ".json", "w"))


def build(tmp):
    root = str(tmp / "g2_pictures")
    for i in range(6):
        pic(f"{root}/explore/named/greenball/auto_{i}.jpg", 100 + i, "ball_chase")          # auto-saved: groomed
    pic(f"{root}/explore/named/greenball/mine.jpg", 7, "hand")                              # hand-named: never
    for i in range(4):
        pic(f"{root}/wall/shot_{i:03d}.jpg", 200 + i)                                        # calibration: never
        pic(f"{root}/liftcal/liftcal_1/pic_{i}.jpg", 300 + i)
        pic(f"{root}/stepcal/stepcal_1/miss_{i}.jpg", 400 + i)
    pic(f"{root}/bout/bout_1/a.jpg", 9)
    pic(f"{root}/bout/bout_1/a_twin.jpg", 9)                                                 # an exact twin: an extra
    pic(f"{root}/explore/named/greenball-labelled/x.jpg", 55, "ball_chase")
    json.dump({"x": {"label": "wall_straight"}}, open(f"{root}/explore/named/greenball-labelled/labels.json", "w"))
    return root


def test_only_allowlisted_folders_are_groomed_and_calibration_is_never_an_extra(tmp_path):
    root = build(tmp_path)
    res = gm.plan(root, cap=3)
    extras = [p for t in res.values() for p in t["extras"]]
    assert res["explore/named/greenball"]["kept"] == 3 and len(res["explore/named/greenball"]["extras"]) == 4           # 6 auto + 1 hand over a cap of 3: the hand one is kept, 2 auto kept, 4 extras
    assert all("/wall/" not in p and "liftcal" not in p and "stepcal" not in p for p in extras)
    assert not any(p.endswith("mine.jpg") for p in extras)                                                               # hand-named: never
    assert not any("greenball-labelled" in p for p in extras)                                                            # a labels file beside it: refused
    assert any(p.endswith("a_twin.jpg") or p.endswith("a.jpg") for p in res["bout"]["extras"]) and len(res["bout"]["extras"]) == 1
    assert "wall" not in res and "liftcal" not in res and "stepcal" not in res                                           # not even looked at


def test_the_calibration_check_refuses_by_folder_name_and_by_a_labels_file(tmp_path):
    root = build(tmp_path)
    for p in ("wall/shot_001.jpg", "wall/ring/x.jpg", "liftcal/liftcal_1/pic_0.jpg", "stepcal/stepcal_1/miss_0.jpg", "claw/20261101/straight.jpg", "explore/named/greenball-labelled/x.jpg"):
        os.makedirs(os.path.dirname(os.path.join(root, p)), exist_ok=True)
        assert gm.is_calibration(os.path.join(root, p), root), p
    assert not gm.is_calibration(os.path.join(root, "bout/bout_1/a.jpg"), root)


def test_apply_moves_the_extras_aside_and_never_a_calibration_picture(tmp_path, monkeypatch):
    root = build(tmp_path)
    monkeypatch.setattr(gm, "PRUNED", str(tmp_path / "pruned"))
    res = gm.plan(root, cap=3)
    n = gm.apply(res, root, queue=False)
    assert n["moved"] == 5 and n["report_only"] == 0 and len(list((tmp_path / "pruned").rglob("*.jpg"))) == 5
    assert len(list((tmp_path / "g2_pictures" / "wall").glob("*.jpg"))) == 4 and len(list((tmp_path / "g2_pictures" / "liftcal").rglob("*.jpg"))) == 4
    res["bad"] = {"kept": 0, "extras": [os.path.join(root, "wall", "shot_000.jpg")]}
    try:
        gm.apply(res, root)
        assert False, "a calibration picture must be refused"
    except AssertionError as e:
        assert "shot_000" in str(e) or e.args


def test_the_weekly_run_waits_seven_days_and_purges_only_old_groomed_folders(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(gm, "PRUNED", str(tmp_path / "pruned"))
    old = tmp_path / "pruned" / "groom_20260101"
    new = tmp_path / "pruned" / "groom_20261110"
    keep = tmp_path / "pruned" / "greenball_backup"
    for d in (old, new, keep):
        d.mkdir(parents=True)
    os.utime(old, (time.time() - 30 * 86400,) * 2)
    os.utime(keep, (time.time() - 30 * 86400,) * 2)
    assert gm.purge(14) == 1 and not old.exists() and new.exists() and keep.exists()              # only an old groom_ folder is purged


def test_apply_queues_the_same_removal_for_the_pi_and_leaves_the_other_folders_report_only(tmp_path, monkeypatch):
    root = build(tmp_path)
    monkeypatch.setattr(gm, "PRUNED", str(tmp_path / "pruned"))
    monkeypatch.setenv("G2_REVIEW_DIR", str(tmp_path / "review"))
    monkeypatch.delenv("G2_PI", raising=False)
    res = gm.plan(root, cap=3)
    out = gm.apply(res, root)
    assert out["moved"] == 5 and out["queued"] == 5 and out["report_only"] == 0                   # the 4 green ball extras and the one bout twin: every folder has a Pi removal path now
    import g2_review_queue as rq
    q = {e["module"]: e for e in rq.pending()}
    ex, claw = q["pi_pipeline.vision.exploration_pictures"], q["pi_pipeline.vision.claw_pictures"]
    assert ex["args"][0] == "trash" and all(a.startswith("named/greenball/") for a in ex["args"][1:])      # paths under the Pi's explore_pictures folder
    assert claw["args"][0] == "trash" and all(a.startswith("bout_1/") for a in claw["args"][1:])            # Mac bout/bout_1/x.jpg -> Pi ~/g2_claw_pics/bout_1/x.jpg
