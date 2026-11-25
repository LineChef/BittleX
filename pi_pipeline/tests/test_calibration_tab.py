"""The Calibration tab of the review page (tools/g2_review.py): objects and sets it lists, what it serves, that the groom refuses calibration pictures, and that a changed picture in a hash-checked set is caught."""
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


def tree(tmp_path):
    rec = tmp_path / "recognition_sets" / "cylinder_basket"
    labels = {}
    for i, label in enumerate(("cylinder_A", "cylinder_A", "cylinder_B", "cylinder_side_A", "cylinder_A_left3", "basket", "basket", "basket_left6", "held_good_stand_lift0", "bad_grab_stand_lift0", "cylinder_basket_setup_lift0")):
        jpg(rec / f"shot_{i:03d}.jpg")
        labels[f"shot_{i:03d}"] = {"label": label, "distance_in": 6, "exposure": {"mean": 115.6}}
    (rec / "labels.json").write_text(json.dumps(labels))
    jpg(tmp_path / "wall" / "shot_100.jpg")
    jpg(tmp_path / "wall" / "shot_101.jpg")
    jpg(tmp_path / "wall" / "shot_102.jpg")
    (tmp_path / "wall" / "labels.json").write_text(json.dumps({"shot_100": {"label": "wall_straight", "distance_in": 16, "set": "new1"}, "shot_101": {"label": "wall_far", "set": "prototype1"},
                                                              "shot_102": {"label": "look", "set": "looks"}}))
    jpg(tmp_path / "claw" / "20261101_150353" / "a.jpg")
    ball = tmp_path / "explore" / "named" / "greenball"
    jpg(ball / "session_1_greenball_r01_6in_c_0.jpg")
    jpg(ball / "session_1_greenball_r02_12in_l_0.jpg")
    jpg(ball / "session_2_greenball_t1_12in_r_0.jpg")
    jpg(ball / "greenball_chase_20261108_083818.jpg")
    jpg(tmp_path / "explore" / "named" / "greenball-noball" / "session_1_greenball_r01_6in_c_0.jpg")
    jpg(tmp_path / "explore" / "named" / "chair" / "session_1_chair_a.jpg")
    jpg(tmp_path / "people" / "p.jpg")


def test_the_tab_separates_the_objects_and_splits_the_cylinder_and_basket_pictures(tmp_path):
    rv = load("g2_review")
    tree(tmp_path)
    sets = rv.calibration_sets(tmp_path)
    by = {}
    for s in sets:
        by.setdefault(s["object"], {})[s["title"]] = len(s["items"])
    assert set(by) == {"Cylinder", "Basket", "Wall", "Ball", "Claw"}                                                          # no look pictures, no people, no auto-saved or other-class pictures
    assert by["Cylinder"] == {"Flat on the floor, face A (distance series)": 2, "Other faces (B, C, D at 18 in)": 1, "On its side": 1, "Bearing check (3 in left and right)": 1,
                              "Throw setup (cylinder and basket)": 1, "Held in the claw, good grip": 1, "Held in the claw, bad grip": 1}
    assert by["Basket"] == {"Distance series (centre, 12 to 36 in)": 2, "Bearing check (6 in left and right)": 1}
    assert by["Wall"] == {"Wall shots, set new1": 1, "Wall shots, set prototype1": 1}
    assert by["Ball"] == {"Ball calibration session 1": 2, "Ball calibration session 2": 1, "No ball (negative examples), session 1": 1}                 # only the hand-taken session pictures
    ball = [s for s in sets if s["object"] == "Ball"][0]
    assert ball["items"][0]["label"] == "ball at 6 in, centred" and ball["items"][0]["distance_in"] == 6.0 and all(s["protected"] for s in sets)


def test_a_recognition_set_in_the_wall_cache_is_not_listed_twice_once_it_is_a_hash_checked_set(tmp_path):
    rv = load("g2_review")
    jpg(tmp_path / "wall" / "shot_051.jpg")
    (tmp_path / "wall" / "labels.json").write_text(json.dumps({"shot_051": {"label": "cylinder_A", "set": "recog"}}))
    assert [s["key"] for s in rv.calibration_sets(tmp_path)] == ["wall/recog#Flat on the floor, face A (distance series)"]
    jpg(tmp_path / "recognition_sets" / "cylinder_basket" / "shot_051.jpg")
    (tmp_path / "recognition_sets" / "cylinder_basket" / "labels.json").write_text(json.dumps({"shot_051": {"label": "cylinder_A"}}))
    assert [s["key"] for s in rv.calibration_sets(tmp_path)] == ["recognition_sets/cylinder_basket#Flat on the floor, face A (distance series)"]


def test_only_calibration_pictures_are_served(tmp_path):
    rv = load("g2_review")
    tree(tmp_path)
    ok = ("wall/shot_100.jpg", "claw/20261101_150353/a.jpg", "recognition_sets/cylinder_basket/shot_001.jpg", "explore/named/greenball/session_1_greenball_r01_6in_c_0.jpg",
          "explore/named/greenball-noball/session_1_greenball_r01_6in_c_0.jpg")
    for good in ok:
        assert rv.cal_image_ok(good, tmp_path) is not None, good
    for bad in ("people/p.jpg", "explore/named/greenball/greenball_chase_20261108_083818.jpg", "explore/named/chair/session_1_chair_a.jpg", "recognition_sets/../people/p.jpg",
                "explore/named/greenball/../chair/session_1_chair_a.jpg", "recognition_sets/cylinder_basket/shot_001.png", "../x.jpg", ""):
        assert rv.cal_image_ok(bad, tmp_path) is None, bad


def test_the_groom_refuses_a_recognition_set_and_the_ball_sessions_and_the_verifier_catches_a_changed_picture(tmp_path):
    groom, cv = load("g2_groom"), load("g2_cal_verify")
    tree(tmp_path)
    assert groom.is_calibration(str(tmp_path / "recognition_sets" / "cylinder_basket" / "shot_001.jpg"), str(tmp_path)) is True
    assert groom.is_calibration(str(tmp_path / "explore" / "named" / "greenball" / "session_1_greenball_r01_6in_c_0.jpg"), str(tmp_path)) is True
    from pi_pipeline.vision import wall_calibration_set as wcs
    p = tmp_path / "recognition_sets" / "cylinder_basket" / "shot_001.jpg"
    wcs.write_manifest(p.parent)
    root = tmp_path / "recognition_sets"
    assert dict(cv.check(root))["cylinder_basket"]["ok"] is True                                                           # pinned and matching
    os.chmod(p, 0o644)
    p.write_bytes(b"\xff\xd8\x00\xff\xd9")
    res = dict(cv.check(root))["cylinder_basket"]
    assert res["ok"] is False and res["changed"] == ["shot_001.jpg"]                                                       # a changed picture shows


def test_the_tub_set_has_its_own_object_and_sections_never_lumped_under_the_cylinder(tmp_path):
    rv = load("g2_review")
    tub = tmp_path / "recognition_sets" / "tub"
    labels = {}
    for i, label in enumerate(("tub_empty", "tub_empty_left", "puck_inside_middle", "puck_beside_left", "puck_outside_touching_left", "tub_8in_empty", "tub_8in_inside_far", "tub_8in_inside_middle_offset_left", "tub_8in_front_3in", "something_new")):
        jpg(tub / f"shot_{i:03d}.jpg")
        labels[f"shot_{i:03d}"] = {"label": label, "distance_in": 16}
    (tub / "labels.json").write_text(json.dumps(labels))
    sets = rv.calibration_sets(tmp_path)
    assert {s["object"] for s in sets} == {"Tub"}
    assert {s["title"]: len(s["items"]) for s in sets} == {"16 in series: empty tub (12 to 22 in, and 16 in left and right)": 2, "16 in: puck inside the tub": 1, "16 in: puck outside the tub or out of view": 2,
                                                          "8 in: empty tub": 1, "8 in: puck inside the tub": 2, "8 in: puck outside the tub": 1, "Other pictures": 1}
    assert all(s["protected"] and "clear tub" in s["note"] for s in sets)
    assert rv.cal_image_ok("recognition_sets/tub/shot_000.jpg", tmp_path) is not None
