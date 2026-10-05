import io
import os
import time

from PIL import Image

from pi_pipeline.util.tidy import tidy_old, tidy_startup
from pi_pipeline.vision.pictures import ahash, hamming, prune_duplicates


def jpeg(pattern: str) -> bytes:
    """A 64x64 test picture: 'bright-left', 'bright-top', 'dark' ... all clearly different layouts."""
    im = Image.new("L", (64, 64), 40)
    for x in range(64):
        for y in range(64):
            if (pattern == "left" and x < 32) or (pattern == "top" and y < 32) or (pattern == "diag" and x + y < 64):
                im.putpixel((x, y), 220)
    buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG"); return buf.getvalue()


def test_hash_is_stable_for_the_same_picture_and_differs_for_different_layouts():
    assert hamming(ahash(jpeg("left")), ahash(jpeg("left"))) == 0
    assert hamming(ahash(jpeg("left")), ahash(jpeg("top"))) > 40


def test_prune_keeps_the_earliest_of_near_duplicates_and_leaves_other_files_alone(tmp_path):
    (tmp_path / "look_20261004_100000_000.jpg").write_bytes(jpeg("left"))
    (tmp_path / "look_20261004_100100_000.jpg").write_bytes(jpeg("left"))          # a duplicate of the first
    (tmp_path / "look_20261004_100200_000.jpg").write_bytes(jpeg("top"))           # different: kept
    (tmp_path / "look_20261004_100300_000.jpg").write_bytes(jpeg("left"))          # another duplicate
    (tmp_path / "notes.txt").write_text("keep me")
    (tmp_path / "other.jpg").write_bytes(jpeg("left"))                              # not a look_ picture: never touched
    removed = prune_duplicates(tmp_path)
    assert removed == ["look_20261004_100100_000.jpg", "look_20261004_100300_000.jpg"]
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["look_20261004_100000_000.jpg", "look_20261004_100200_000.jpg", "notes.txt", "other.jpg"]


def test_prune_on_a_missing_folder_or_an_unreadable_file_does_not_raise(tmp_path):
    assert prune_duplicates(tmp_path / "nope") == []
    (tmp_path / "look_bad.jpg").write_bytes(b"not a jpeg")
    assert prune_duplicates(tmp_path) == [] and (tmp_path / "look_bad.jpg").exists()


def test_saving_a_picture_prunes_duplicates_in_the_save_folder(tmp_path):
    from pi_pipeline.tests.test_vision_describe import FakeSerial, make_cam
    import base64, json
    line = json.dumps({"type": 1, "name": "INVOKE", "code": 0, "data": {"resolution": [240, 240], "boxes": [],
                                                                       "image": base64.b64encode(jpeg("left")).decode()}})
    cam = make_cam(FakeSerial([line, line]), save_dir=str(tmp_path))
    assert cam.snapshot() is not None
    cam._ser._lines.append(line)
    time.sleep(0.01)
    assert cam.snapshot() is not None
    assert len(list(tmp_path.glob("look_*.jpg"))) == 1                              # the second, identical picture was pruned


def age(path, days):
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def test_tidy_removes_old_files_and_folders_and_keeps_recent_ones(tmp_path):
    old_dir = tmp_path / "20260901T000000_aaaa"; old_dir.mkdir(); (old_dir / "events.jsonl").write_text("x"); age(old_dir, 40)
    new_dir = tmp_path / "20261004T000000_bbbb"; new_dir.mkdir(); age(new_dir, 2)
    old_file = tmp_path / "walk_old.csv"; old_file.write_text("x"); age(old_file, 31)
    new_file = tmp_path / "walk_new.csv"; new_file.write_text("x")
    removed = tidy_old(tmp_path, 30)
    assert sorted(removed) == ["20260901T000000_aaaa", "walk_old.csv"]
    assert new_dir.exists() and new_file.exists() and not old_dir.exists() and not old_file.exists()


def test_tidy_never_touches_dotfiles_symlinks_or_anything_outside_the_folder(tmp_path):
    folder = tmp_path / "logs"; folder.mkdir()
    outside = tmp_path / "precious.db"; outside.write_text("memory"); age(outside, 400)
    (folder / ".keep").write_text("x"); age(folder / ".keep", 400)
    link = folder / "link_to_precious"; link.symlink_to(outside)
    tidy_old(folder, 30)
    assert outside.exists() and (folder / ".keep").exists() and link.is_symlink()


def test_tidy_is_off_at_zero_days_and_safe_on_a_missing_folder(tmp_path):
    f = tmp_path / "old.csv"; f.write_text("x"); age(f, 400)
    assert tidy_old(tmp_path, 0) == [] and f.exists()
    assert tidy_old(tmp_path / "missing", 30) == []
    assert tidy_startup([tmp_path, tmp_path / "missing"], 30) == {str(tmp_path): 1, str(tmp_path / "missing"): 0}
