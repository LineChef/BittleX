"""Wall calibration sets (vision/wall_calibration_set.py, tools/g2_cal_verify.py): the pictures the calibration is built from live in their own folder, hashed, read-only, never deleted by the picture tools."""
import importlib.util
import json
import os
import stat
from pathlib import Path

import pytest

from pi_pipeline.vision import wall_calibration_set as wcs
from pi_pipeline.vision import wall_pictures as wp

ROOT = Path(__file__).resolve().parents[2]


def _set(tmp_path, name="claw-walk-test"):
    d = tmp_path / "g2_wall_calibration" / name
    d.mkdir(parents=True)
    (d / "shot_001.jpg").write_bytes(b"jpeg one")
    (d / "shot_002.jpg").write_bytes(b"jpeg two")
    (d / "labels.json").write_text(json.dumps({"shot_001": {"label": "wall_straight", "distance_in": 8}}))
    return d


def test_the_manifest_hashes_every_file_and_verify_reports_what_changed(tmp_path):
    d = _set(tmp_path)
    man = wcs.write_manifest(d)
    assert set(man["files"]) == {"shot_001.jpg", "shot_002.jpg", "labels.json"} and wcs.verify(d)["ok"]
    (d / "shot_001.jpg").write_bytes(b"altered")
    (d / "shot_002.jpg").unlink()
    (d / "shot_003.jpg").write_bytes(b"new")
    res = wcs.verify(d)
    assert not res["ok"] and res["changed"] == ["shot_001.jpg"] and res["missing"] == ["shot_002.jpg"] and res["added"] == ["shot_003.jpg"]


def test_lock_makes_the_files_read_only_but_the_folder_stays_writable(tmp_path):
    d = _set(tmp_path)
    wcs.write_manifest(d)
    assert wcs.lock(d) == 4
    for f in ("shot_001.jpg", "labels.json", "MANIFEST.json"):
        assert not os.stat(d / f).st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    (d / "shot_003.jpg").write_bytes(b"a later picture can still be added")
    wcs.unlock_file(d / "labels.json")
    assert os.stat(d / "labels.json").st_mode & stat.S_IWUSR


def test_the_picture_tools_refuse_a_calibration_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(wcs, "CAL_ROOT", str(tmp_path / "g2_wall_calibration"))
    d = _set(tmp_path)
    for call in (lambda: wp.delete(d, [1]), lambda: wp.trash(d, ["shot_001"]), lambda: wp.restore(d, ["shot_001"]), lambda: wp.empty_trash(d)):
        with pytest.raises(SystemExit, match="calibration set"):
            call()
    assert (d / "shot_001.jpg").exists()
    ordinary = tmp_path / "g2_wall_pics"
    ordinary.mkdir()
    assert wp.delete(ordinary, [1]) == []                                              # an ordinary shot folder still works as before


def test_a_set_name_is_plain_and_the_mac_mirror_counts_as_a_calibration_folder():
    assert wcs.set_dir("claw-walk-2026-11-19").name == "claw-walk-2026-11-19"
    with pytest.raises(ValueError):
        wcs.set_dir("../escape")
    assert wcs.is_calibration_dir("/Users/x/Desktop/G2Memory/g2_pictures/wall_calibration/claw-walk")
    assert not wcs.is_calibration_dir("/Users/x/Desktop/G2Memory/g2_pictures/wall/ring")


def _verify_tool():
    spec = importlib.util.spec_from_file_location("g2_cal_verify_t", ROOT / "tools" / "g2_cal_verify.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_mac_check_pins_a_set_the_first_time_and_flags_any_later_change(tmp_path):
    tool = _verify_tool()
    root = tmp_path / "wall_calibration"
    d = root / "claw-walk"
    d.mkdir(parents=True)
    (d / "shot_001.jpg").write_bytes(b"jpeg one")
    (d / "labels.json").write_text("{}")
    first = tool.check(root)
    assert first[0][0] == "claw-walk" and first[0][1]["ok"] and (root / "_pinned" / "claw-walk.json").exists()
    assert not os.stat(d / "shot_001.jpg").st_mode & stat.S_IWUSR                     # locked read-only by the check
    os.chmod(d / "shot_001.jpg", 0o644)
    (d / "shot_001.jpg").write_bytes(b"someone edited it")
    (d / "shot_002.jpg").write_bytes(b"a new one")
    res = tool.check(root)[0][1]
    assert not res["ok"] and res["changed"] == ["shot_001.jpg"] and res["added"] == ["shot_002.jpg"]
    assert tool.main(["--root", str(root), "--quiet"]) == 1                           # the exit code says so
    tool.check(root, accept="claw-walk")                                              # after looking, the new state is accepted
    assert tool.check(root)[0][1]["ok"]
