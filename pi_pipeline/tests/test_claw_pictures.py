"""vision/claw_pictures.py: the Pi-side trash for the grooming: behaviour pictures only, calibration refused, restorable."""
import pytest

from pi_pipeline.vision import claw_pictures as cp


def make(root, rel, data=b"x"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    p.with_suffix(".json").write_text("{}")


def test_a_behaviour_picture_is_trashed_and_restored_with_its_notes(tmp_path):
    root = tmp_path / "g2_claw_pics"
    make(root, "watch_20261115_190038/pic_03.jpg")
    assert cp.trash_pictures(str(root), ["watch_20261115_190038/pic_03.jpg"]) == ["watch_20261115_190038/pic_03.jpg"]
    assert not (root / "watch_20261115_190038/pic_03.jpg").exists() and (tmp_path / "g2_claw_pics_trash/watch_20261115_190038/pic_03.jpg").exists()
    assert (tmp_path / "g2_claw_pics_trash/watch_20261115_190038/pic_03.json").exists()
    assert cp.restore_pictures(str(root), ["watch_20261115_190038/pic_03.jpg"]) == ["watch_20261115_190038/pic_03.jpg"] and (root / "watch_20261115_190038/pic_03.jpg").exists()


@pytest.mark.parametrize("rel", ["liftcal_20261115_182843/pic_08.jpg", "stepcal_20261116_162404/miss_03.jpg", "wall_x/a.jpg", "20261101_150537/straight.jpg", "../outside.jpg", "bout_1/labels.json", "notallowed_1/a.jpg"])
def test_calibration_and_other_pictures_are_refused(tmp_path, rel):
    root = tmp_path / "g2_claw_pics"
    make(root, "liftcal_20261115_182843/pic_08.jpg")
    with pytest.raises(ValueError):
        cp.trash_pictures(str(root), [rel])
    assert (root / "liftcal_20261115_182843/pic_08.jpg").exists()


def test_the_queue_allows_this_module_and_only_trash_and_restore():
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
    import g2_review_queue as rq
    rq.check("pi_pipeline.vision.claw_pictures", ["trash", "bout_1/a.jpg"])
    with pytest.raises(ValueError):
        rq.check("pi_pipeline.vision.claw_pictures", ["empty-trash"])
