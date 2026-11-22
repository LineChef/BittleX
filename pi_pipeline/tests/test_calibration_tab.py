"""The Calibration tab of the review page (tools/g2_review.py): which picture sets it lists, what it serves, that the groom refuses a recognition set, and that a changed picture in one is caught."""
import importlib.util
import json
import os
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name + "_t", TOOLS / (name + ".py"))
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(TOOLS.parent))
    spec.loader.exec_module(m)
    return m


def jpg(p):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\xff\xd8\xff\xd9")


def test_the_tab_lists_the_recognition_wall_and_claw_sets_and_leaves_look_pictures_and_people_out(tmp_path):
    rv = load("g2_review")
    jpg(tmp_path / "recognition_sets" / "cylinder_basket" / "shot_001.jpg")
    (tmp_path / "recognition_sets" / "cylinder_basket" / "labels.json").write_text(json.dumps({"shot_001": {"label": "cylinder_A", "distance_in": 6, "exposure": {"mean": 115.6}}}))
    jpg(tmp_path / "wall" / "shot_002.jpg")
    jpg(tmp_path / "wall" / "shot_003.jpg")
    (tmp_path / "wall" / "labels.json").write_text(json.dumps({"shot_002": {"label": "wall_straight", "distance_in": 16}, "shot_003": {"label": "chair", "set": "looks"}}))
    jpg(tmp_path / "claw" / "20261101_150353" / "a.jpg")
    jpg(tmp_path / "people" / "p.jpg")
    jpg(tmp_path / "explore" / "e.jpg")
    sets = rv.calibration_sets(tmp_path)
    keys = {s["key"]: s for s in sets}
    assert set(keys) == {"recognition_sets/cylinder_basket", "wall/None", "claw/20261101_150353"}                          # no look pictures, no people, no exploration pictures
    rec = keys["recognition_sets/cylinder_basket"]
    assert rec["items"][0]["label"] == "cylinder_A" and rec["items"][0]["distance_in"] == 6 and rec["items"][0]["exposure"] == 115.6 and rec["protected"] is True
    assert [i["label"] for i in keys["wall/None"]["items"]] == ["wall_straight"]


def test_a_recognition_set_in_the_wall_cache_is_not_listed_twice_once_it_is_a_hash_checked_set(tmp_path):
    rv = load("g2_review")
    jpg(tmp_path / "wall" / "shot_051.jpg")
    (tmp_path / "wall" / "labels.json").write_text(json.dumps({"shot_051": {"label": "cylinder_A", "set": "recog"}}))
    assert [s["key"] for s in rv.calibration_sets(tmp_path)] == ["wall/recog"]
    jpg(tmp_path / "recognition_sets" / "cylinder_basket" / "shot_051.jpg")
    assert [s["key"] for s in rv.calibration_sets(tmp_path)] == ["recognition_sets/cylinder_basket"]


def test_only_pictures_inside_the_calibration_folders_are_served(tmp_path):
    rv = load("g2_review")
    jpg(tmp_path / "recognition_sets" / "s" / "a.jpg")
    jpg(tmp_path / "people" / "p.jpg")
    jpg(tmp_path / "explore" / "e.jpg")
    assert rv.cal_image_ok("recognition_sets/s/a.jpg", tmp_path) is not None
    for bad in ("people/p.jpg", "explore/e.jpg", "recognition_sets/../people/p.jpg", "recognition_sets/s/a.png", "../x.jpg", ""):
        assert rv.cal_image_ok(bad, tmp_path) is None, bad


def test_the_groom_refuses_a_recognition_set_and_the_verifier_catches_a_changed_picture(tmp_path):
    groom, cv = load("g2_groom"), load("g2_cal_verify")
    p = tmp_path / "recognition_sets" / "cylinder_basket" / "shot_051.jpg"
    jpg(p)
    assert groom.is_calibration(str(p), str(tmp_path)) is True
    from pi_pipeline.vision import wall_calibration_set as wcs
    wcs.write_manifest(p.parent)
    root = tmp_path / "recognition_sets"
    assert dict(cv.check(root))["cylinder_basket"]["ok"] is True                                                           # pinned and matching
    os.chmod(p, 0o644)
    p.write_bytes(b"\xff\xd8\x00\xff\xd9")
    res = dict(cv.check(root))["cylinder_basket"]
    assert res["ok"] is False and res["changed"] == ["shot_051.jpg"]                                                       # a changed picture shows
