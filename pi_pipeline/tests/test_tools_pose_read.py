"""tools/g2_pose_read.py: the left/right comparison and the refusals (no serial port is opened)."""
import importlib.util
import os
import subprocess
import sys

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
_spec = importlib.util.spec_from_file_location("g2_pose_read_under_test", os.path.join(_TOOLS, "g2_pose_read.py"))
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)

STAND = [1, -1, 0, -1, 0, 0, 0, 0, 14, 14, 19, 19, 55, 55, 49, 49]


def test_a_matching_stand_is_symmetric_and_a_leg_off_by_more_than_the_tolerance_is_named():
    assert pr.symmetry(STAND)["state"] == "ok"
    bad = list(STAND)
    bad[13] = 40                                                       # the front-right knee
    s = pr.symmetry(bad)
    assert s["state"] == "off" and s["off"] == ["front knee"]


def test_all_zeros_and_no_reading_are_not_taken_for_a_pose():
    assert pr.symmetry([0] * 16)["state"] == "blank" and pr.symmetry(None)["state"] == "unread"
    assert "no pose yet" in " ".join(pr.describe("x", [0] * 16))


def test_two_identical_reads_are_flagged():
    assert "may not have changed" in " ".join(pr.describe("kcalib", STAND, previous=list(STAND)))
    assert "may not have changed" not in " ".join(pr.describe("kcalib", STAND, previous=[0] * 16))


def test_it_refuses_without_being_told_where_he_is():
    r = subprocess.run([sys.executable, os.path.join(_TOOLS, "g2_pose_read.py")], capture_output=True, text=True)
    assert r.returncode != 0 and "--suspended or --at-rest" in r.stderr
