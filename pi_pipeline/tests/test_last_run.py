"""`g2lastrun` (diag/last_run.py): what the newest run did, and whether the board took a script."""
import json
import os

from pi_pipeline.diag import last_run as lr


def write(root, sub, name, data, mtime):
    d = os.path.join(root, sub)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, name)
    json.dump(data, open(p, "w"))
    os.utime(p, (mtime, mtime))
    return p


BASE = {"verdict": "ok", "max_pitch_dev": 26.8, "max_roll_dev": 2.1, "fell": False, "pack_pct": 75, "script": "lob_soft", "amount": 1.0, "picked_first": True, "pick_gap_s": 0.5, "gyro_off": True}


def test_the_newest_logs_come_first_across_the_three_folders(tmp_path):
    a = write(str(tmp_path), "scripts", "a.json", BASE, 1000)
    b = write(str(tmp_path), "arm_skills", "b.json", BASE, 3000)
    c = write(str(tmp_path), "catapult", "c.json", BASE, 2000)
    assert lr.newest(3, str(tmp_path)) == [b, c, a] and lr.newest(1, str(tmp_path)) == [b]


def test_a_script_the_board_took_says_so_and_one_it_did_not_take_is_not_called_fine(tmp_path):
    took = write(str(tmp_path), "scripts", "t.json", {**BASE, "board_after_send": ["g", "K", "K"]}, 1)
    not_taken = write(str(tmp_path), "scripts", "n.json", {**BASE, "board_after_send": ["g"]}, 2)
    old = write(str(tmp_path), "scripts", "o.json", dict(BASE), 3)
    assert any("the board took the script" in x for x in lr.describe(took))
    bad = lr.describe(not_taken)
    assert any("NO K from the board" in x and "probably NOT taken" in x for x in bad) and any("verdict ok" in x for x in bad)
    assert any("not recorded" in x for x in lr.describe(old))                                   # an older log: the verdict alone proves nothing


def test_an_arm_skill_log_shows_the_claw_and_an_unreadable_log_says_so(tmp_path):
    arm = write(str(tmp_path), "arm_skills", "p.json", {"verdict": "ok", "max_pitch_dev": 17.1, "max_roll_dev": 2.6, "fell": False, "pack_pct": 81, "pack_pct_after": 69, "claw_joint_before": 0, "claw_joint_after": 0}, 1)
    lines = lr.describe(arm)
    assert any("pack 81% before, 69% after" in x for x in lines) and any("claw reading before 0 and after 0" in x for x in lines)
    bad = tmp_path / "x.json"
    bad.write_text("{not json")
    assert "could not read" in lr.describe(str(bad))[0]
