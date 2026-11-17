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


def test_the_pi_trash_is_purged_after_fourteen_days_and_the_clock_starts_at_the_first_purge_for_older_trash(tmp_path):
    import json
    import time
    root = tmp_path / "g2_claw_pics"
    make(root, "bout_1/a.jpg")
    make(root, "bout_1/b.jpg")
    cp.trash_pictures(str(root), ["bout_1/a.jpg", "bout_1/b.jpg"])
    tr = tmp_path / "g2_claw_pics_trash"
    idx = json.loads((tr / ".trashed.json").read_text())
    assert set(idx) == {"bout_1/a.jpg", "bout_1/b.jpg"}                                      # the trashed time is kept
    assert cp.purge_trash(str(root), 14) == 0 and (tr / "bout_1/a.jpg").exists()               # fresh: kept
    idx["bout_1/a.jpg"] = time.time() - 15 * 86400
    (tr / ".trashed.json").write_text(json.dumps(idx))
    assert cp.purge_trash(str(root), 14) == 1
    assert not (tr / "bout_1/a.jpg").exists() and not (tr / "bout_1/a.json").exists() and (tr / "bout_1/b.jpg").exists()
    (tr / "bout_1").mkdir(exist_ok=True)
    (tr / "bout_1/old.jpg").write_bytes(b"x")                                                  # trashed before the index existed
    assert cp.purge_trash(str(root), 14) == 0 and "bout_1/old.jpg" in json.loads((tr / ".trashed.json").read_text())      # its 14 days start now


def test_the_explore_trash_is_purged_the_same_way(tmp_path):
    import json
    import time
    from pi_pipeline.vision import exploration_pictures as ep
    root = tmp_path / "explore_pictures"
    (root / "named/greenball").mkdir(parents=True)
    (root / "named/greenball/x.jpg").write_bytes(b"x")
    (root / "named/greenball/x.json").write_text("{}")
    assert ep.trash_pictures(str(root), ["named/greenball/x.jpg"]) == ["named/greenball/x.jpg"]
    tr = ep.trash_root(str(root))
    idx = json.loads((tr / ".trashed.json").read_text())
    idx["named/greenball/x.jpg"] = time.time() - 20 * 86400
    (tr / ".trashed.json").write_text(json.dumps(idx))
    assert ep.purge_trash(str(root), 14) == 1 and not (tr / "named/greenball/x.jpg").exists()


def test_the_groom_queues_the_pi_purge_once_and_the_queue_allows_it(tmp_path, monkeypatch):
    import os
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
    import g2_groom as gm
    import g2_review_queue as rq
    monkeypatch.setenv("G2_REVIEW_DIR", str(tmp_path / "review"))
    assert gm.queue_pi_purge(14) == 2 and gm.queue_pi_purge(14) == 0                         # once per module, not again while waiting
    assert {e["module"] for e in rq.pending()} == set(gm.PI_PURGE_MODULES) and all(e["args"][0] == "purge-trash" for e in rq.pending())
