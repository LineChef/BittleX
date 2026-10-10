"""The teaching tool (gait/teach.py) and the step builder (reference_gait/build_taught_step.py)."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from pi_pipeline.gait import standup, teach

ROOT = Path(__file__).resolve().parents[2]


class FakeLink:
    def __init__(self, feedback=None):
        self.sent, self.feedback = [], feedback or {}

    def send(self, cmd, read_reply=True, **kw):
        self.sent.append(cmd)
        return self.feedback.get(cmd, "") if read_reply else ""

    def drain(self, s=0.3):
        return ""


def teacher(tmp_path, link=None):
    out = []
    t = teach.Teacher(link or FakeLink(), tmp_path / "s.json", say=out.append, sleep=lambda s: None)
    return t, out


def test_jog_relative_absolute_and_limits():
    cur = [30.0] * 8
    assert teach.parse_jog("fl knee +5", cur)[1] == 35
    assert teach.parse_jog("fr shoulder 40", cur)[2] == 40
    assert teach.parse_jog("bl hip -3", cur)[6] == 27
    assert teach.parse_jog("br k +10", cur)[5] == 40
    for bad in ("fl knee +50", "fl knee 90", "xx knee 1", "fl elbow 1", "fl knee", "fl knee abc"):
        with pytest.raises(ValueError):
            teach.parse_jog(bad, cur)


def test_feedback_parsing_maps_servo_order_to_urdf():
    servo_legs = [10, 11, 12, 13, 20, 21, 22, 23]       # FLs FRs BRs BLs FLk FRk BRk BLk
    got = teach.parse_angles("f " + " ".join(["0"] * 8 + [str(x) for x in servo_legs]))
    assert got == [10, 20, 11, 21, 12, 22, 13, 23]
    assert teach.parse_angles(" ".join(str(x) for x in servo_legs)) == got
    assert teach.parse_angles("") is None and teach.parse_angles("1 2 3") is None


def test_jog_sends_eased_moves_and_save_undo_roundtrip(tmp_path):
    link = FakeLink()
    t, _ = teacher(tmp_path, link)
    t.stand("balance")
    assert link.sent[0] == "kbalance" and t.current == standup.BALANCE_URDF_DEG
    n = len(link.sent)
    t.jog("fl knee +10")
    moves = link.sent[n:]
    assert len(moves) >= 5 and all(m.startswith("i") for m in moves) and moves[-1] == standup.move_cmd(t.current)
    t.save("lift")
    t.jog("fl shoulder +8")
    t.save()
    assert [s["name"] for s in t.steps] == ["lift", "step2"]
    t.undo()
    t2, _ = teacher(tmp_path)                           # reloads from the file
    assert [s["name"] for s in t2.steps] == ["lift"] and t2.steps[0]["deg"][1] == 40


def test_jog_needs_a_pose_and_grab_needs_limp_servos(tmp_path):
    link = FakeLink({"f": " ".join(["0"] * 8 + ["50"] * 8)})
    t, _ = teacher(tmp_path, link)
    with pytest.raises(ValueError):
        t.jog("fl knee +5")
    with pytest.raises(ValueError):
        t.grab()                                         # servos not relaxed: refuse
    t.hand()
    assert link.sent[-1] == "d"
    t.grab()
    assert t.current == [50.0] * 8
    t.hold()
    assert link.sent[-1] == standup.move_cmd([50.0] * 8)
    t.jog("fr knee -5")                                  # grab then jog works together
    assert t.current[3] == 45


def test_grab_falls_back_to_j_and_reports_no_reading(tmp_path):
    t, _ = teacher(tmp_path, FakeLink({"j": " ".join(["0"] * 8 + ["7"] * 8)}))
    t.hand(); t.grab()
    assert t.current == [7.0] * 8
    t2, _ = teacher(tmp_path / "x", FakeLink())
    t2.hand()
    with pytest.raises(ValueError):
        t2.grab()


def test_check_flags_a_mismatch(tmp_path):
    fb = " ".join(["0"] * 8 + [str(30)] * 8)
    t, out = teacher(tmp_path, FakeLink({"f": fb}))
    t.check()
    assert any("looks right" in o for o in out)
    t, out = teacher(tmp_path / "y", FakeLink({"f": " ".join(["0"] * 8 + ["90"] * 8)}))
    t.check()
    assert any("MISMATCH" in o for o in out)


def _builder():
    spec = importlib.util.spec_from_file_location("bts", ROOT / "rl_training/opencat-gym/reference_gait/build_taught_step.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_builder_closes_the_loop_and_phases_the_legs():
    b = _builder()
    wkf = np.rad2deg(np.load(ROOT / "rl_training/opencat-gym/reference_gait/wkf_ref.npy"))
    lift = [[40, 0] + [0] * 6, [60, 20] + [0] * 6, [70, 30] + [0] * 6, [45, 5] + [0] * 6]
    out = b.build(lift, "fl", wkf)
    assert out.shape == (100, 8)
    assert np.allclose(out[0, :2], [40, 0], atol=1e-6) and np.allclose(out[25, :2], [60, 20], atol=1e-6)
    assert np.abs(out[0, :2] - out[-1, :2]).max() < 25                       # continuous across the wrap
    fr_expected = np.roll(out[:, :2], -50, axis=0)                           # FR is 50 frames ahead of FL
    assert np.allclose(out[:, 2:4], fr_expected, atol=1e-6)
    rep = b.build(lift, "fl", wkf, rear="replace")
    assert np.allclose(rep[:, 4:6], np.roll(rep[:, :2], -88, axis=0))
    d = b.build(lift, "fl", wkf, rear="delta")
    assert np.allclose(d[:, 4:6].mean(0), wkf[:, 4:6].mean(0), atol=1e-6)    # delta keeps wkF's rear mean
    with pytest.raises(ValueError):
        b.build(lift[:2], "fl", wkf)
