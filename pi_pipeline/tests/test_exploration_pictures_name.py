"""vision/exploration_pictures name_pictures / move_pictures: naming by hand moves a picture and its sidecar into named/<name>/ and can be undone."""
import json

import pytest

from pi_pipeline.vision import exploration_pictures as EP


def _make(root, rel, meta=None):
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"\xff\xd8jpg")
    if meta is not None:
        f.with_suffix(".json").write_text(json.dumps(meta))
    return f


def test_naming_moves_the_picture_and_its_sidecar_and_marks_the_name(tmp_path):
    _make(tmp_path, "survey/20261007/after_bow_1.jpg", {"pose": "after_bow", "time": "2026-10-07 14:00:00"})
    out = EP.name_pictures(str(tmp_path), "Dish Washer!", ["survey/20261007/after_bow_1.jpg"])
    assert out == [{"from": "survey/20261007/after_bow_1.jpg", "to": "named/dish-washer/after_bow_1.jpg"}] or out[0]["to"].startswith("named/dish")
    dst = tmp_path / out[0]["to"]
    assert dst.exists() and not (tmp_path / "survey/20261007/after_bow_1.jpg").exists() and not (tmp_path / "survey/20261007/after_bow_1.json").exists()
    meta = json.loads(dst.with_suffix(".json").read_text())
    assert meta["name"] == "dish washer" and meta["pose"] == "named" and meta["named_by"] == "hand" and meta["time"] == "2026-10-07 14:00:00"
    back = EP.move_pictures(str(tmp_path), [(out[0]["to"], out[0]["from"])])
    assert back and (tmp_path / "survey/20261007/after_bow_1.jpg").exists()


def test_naming_without_a_sidecar_keeps_name_clashes_apart_and_rejects_bad_input(tmp_path):
    _make(tmp_path, "survey/20261007/a.jpg")
    _make(tmp_path, "survey/20261008/a.jpg")
    one = EP.name_pictures(str(tmp_path), "mug", ["survey/20261007/a.jpg"])
    two = EP.name_pictures(str(tmp_path), "mug", ["survey/20261008/a.jpg"])
    assert one[0]["to"] != two[0]["to"] and (tmp_path / one[0]["to"]).exists() and (tmp_path / two[0]["to"]).exists()
    with pytest.raises(ValueError):
        EP.name_pictures(str(tmp_path), "  ", ["survey/20261007/a.jpg"])
    with pytest.raises(ValueError):
        EP.name_pictures(str(tmp_path), "mug", ["../../etc/passwd.jpg"])


def test_a_wrong_detector_label_can_be_dismissed_and_restored(tmp_path):
    _make(tmp_path, "survey/20261007/a.jpg", {"detections": [{"label": "dog", "score": 0.7}, {"label": "person", "score": 0.6}]})
    rel = "survey/20261007/a.jpg"
    assert [p for p in EP.list_pictures(str(tmp_path))][0]["detector"] == ["dog", "person"]
    out = EP.set_label_dismissed(str(tmp_path), rel, "dog")
    assert out["detector"] == ["person"] and out["dismissed"] == ["dog"]
    row = EP.list_pictures(str(tmp_path))[0]
    assert row["detector"] == ["person"] and row["dismissed"] == ["dog"]
    # the detection record itself is kept
    assert json.loads((tmp_path / "survey/20261007/a.json").read_text())["detections"][0]["label"] == "dog"
    back = EP.set_label_dismissed(str(tmp_path), rel, "dog", dismissed=False)
    assert back["detector"] == ["dog", "person"] and back["dismissed"] == []
