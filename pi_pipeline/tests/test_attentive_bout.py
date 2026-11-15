"""The supervised attentive bout (behavior/attentive_bout.py): gaze-follow with the claw from the attention pose, slow because the frames are old, never staring, always put back."""
import pytest

from pi_pipeline import focus
from pi_pipeline.behavior import attentive_bout as ab


@pytest.fixture(autouse=True)
def _files(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_FOCUS_FILE", str(tmp_path / "focus.json"))
    monkeypatch.setattr(ab, "STOP_FILE", str(tmp_path / "stop"))


def det(cx, w=0.2, h=0.2, label="thing", score=0.8):
    return (label, score, cx, 0.5, w, h)


class FakeRobot:
    def __init__(self, tilts=None, fell_at=None):
        self.calls, self.sent, self.tilts, self.fell_at = [], [], list(tilts or []), fell_at

    def relax(self):
        self.calls.append("relax")
        return "ok"

    def claw_pose(self, pan, lift):
        self.calls.append(("claw", round(pan, 1), lift))
        return "ok"

    def _fell(self):
        return self.fell_at is not None and len([c for c in self.calls if c != "relax"]) >= self.fell_at

    def _tilt(self, *a, **k):
        return self.tilts.pop(0) if self.tilts else (0.0, 0.0)

    def _tx(self, c):
        self.sent.append(c)

    def stand_up(self):
        self.calls.append("stand_up")
        return "ok"


class Clock:
    t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_a_target_on_his_right_turns_the_camera_right_which_is_a_negative_pan_on_g2():
    cfg = ab.BoutConfig()
    t = ab.GazeTracker(cfg, "left")
    pan = t.update([det(0.9)], 0.0, 0.0)
    assert pan is not None and pan < 0 and abs(pan) <= cfg.pan_max_deg                 # right of the middle: the camera turns right
    assert ab.GazeTracker(cfg, "right").update([det(0.9)], 0.0, 0.0) > 0                # the other sign convention flips it


def test_it_follows_slowly_a_move_at_most_every_cooldown_and_only_part_of_the_way():
    cfg = ab.BoutConfig()
    t = ab.GazeTracker(cfg, "left")
    first = t.update([det(0.9)], 0.0, 0.0)
    assert first is not None
    assert t.update([det(0.9)], first, 0.5) is None                                     # inside the cooldown
    off = (0.9 - 0.5) * 2 * cfg.fov_half_deg
    assert abs(first) == pytest.approx(off * cfg.gain, abs=0.01) and abs(first) < off  # part of the way: the frame is a second old


def test_a_centred_target_and_a_target_too_small_or_unsure_are_left_alone():
    t = ab.GazeTracker(ab.BoutConfig(), "left")
    assert t.update([det(0.52)], 0.0, 0.0) is None
    assert t.update([det(0.9, w=0.01, h=0.01)], 0.0, 1.0) is None
    assert t.update([det(0.9, score=0.1)], 0.0, 2.0) is None


def test_the_largest_detection_wins_and_labels_can_be_limited():
    cfg = ab.BoutConfig()
    assert ab.GazeTracker(cfg).best([det(0.3, 0.1, 0.1, "a"), det(0.7, 0.3, 0.3, "b")])[0] == "b"
    cfg.labels = ("a",)
    assert ab.GazeTracker(cfg).best([det(0.3, 0.1, 0.1, "a"), det(0.7, 0.3, 0.3, "b")])[0] == "a"


def test_he_does_not_stare_after_satiate_s_only_glances_until_the_target_moves_far():
    cfg = ab.BoutConfig()
    t = ab.GazeTracker(cfg, "left")
    moves, pan, now = [], 0.0, 0.0
    while now < 30.0:                                                                    # a target 12 deg off to the side, never centred
        m = t.update([det(0.69)], pan, now)
        if m is not None:
            moves.append(round(now, 1))
            pan = m
        now += 0.5
    early = [x for x in moves if x <= cfg.satiate_s]
    late = [x for x in moves if x > cfg.satiate_s]
    assert len(early) >= 4 and 0 < len(late) <= (30.0 - cfg.satiate_s) / cfg.glance_s + 1   # glances, not a lock-on
    far = t.update([det(0.95)], pan, now + 10.0)                                         # it moved a long way: follow again
    assert far is not None


def test_with_nothing_in_view_he_looks_around_every_scan_every_s():
    cfg = ab.BoutConfig()
    t = ab.GazeTracker(cfg, "left")
    assert t.update([], 0.0, 0.0) is None
    scan = t.update([], 0.0, cfg.scan_every_s + 1)
    assert scan is not None and t.reason == "look around"


def test_a_bout_raises_the_claw_follows_and_puts_everything_back_in_the_standard_order():
    c, r = Clock(), FakeRobot()
    cfg = ab.BoutConfig(minutes=0.5)
    res = ab.run_bout(r, lambda: [det(0.9)], cfg, say=lambda *_: None, sleep=c.sleep, clock=c, stopped=lambda: False)
    assert res["ended"] == "time" and res["moves"] >= 1 and res["pictures"] > 10
    assert r.calls[0] == "relax" and r.calls[1] == ("claw", 0.0, 120.0)                  # attention pose, then the claw up first
    assert r.calls[-2:] == [("claw", 0.0, 0.0), "stand_up"]                              # claw down and centred, then the standard stand-up
    assert ab.LEG_KEEPALIVE_CMD in r.sent                                                # the legs are held
    assert not focus.held()                                                              # the focus lock was held for the bout and released


def test_the_focus_lock_is_held_during_the_bout():
    c = Clock()
    seen = []

    def look():
        seen.append(focus.held())
        return []
    ab.run_bout(FakeRobot(), look, ab.BoutConfig(minutes=0.1), say=lambda *_: None, sleep=c.sleep, clock=c, stopped=lambda: False)
    assert seen and all(seen)


def test_a_sagging_body_a_stop_and_a_fall_end_the_bout_and_a_fall_leaves_him_in_rest():
    c = Clock()
    r = FakeRobot(tilts=[(0.0, 0.0), (0.0, 25.0)])
    res = ab.run_bout(r, lambda: [], ab.BoutConfig(minutes=5), say=lambda *_: None, sleep=c.sleep, clock=c, stopped=lambda: False)
    assert res["ended"] == "sag" and r.calls[-2:] == [("claw", 0.0, 0.0), "stand_up"]
    c = Clock()
    res = ab.run_bout(FakeRobot(), lambda: [], ab.BoutConfig(minutes=5), say=lambda *_: None, sleep=c.sleep, clock=c, stopped=lambda: True)
    assert res["ended"] == "stopped"
    c, r = Clock(), FakeRobot(fell_at=2)
    res = ab.run_bout(r, lambda: [], ab.BoutConfig(minutes=5), say=lambda *_: None, sleep=c.sleep, clock=c, stopped=lambda: False)
    assert res["ended"] == "fell" and "stand_up" not in r.calls                          # after a fall he is laid in rest, never sent a stand


def test_labels_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("G2_ATTENTIVE_LABELS", "Cup, ball")
    assert ab.labels_from_env() == ("cup", "ball")
    monkeypatch.delenv("G2_ATTENTIVE_LABELS")
    assert ab.labels_from_env() is None


def test_a_silent_board_moves_nothing_and_ends_no_board():
    c, r = Clock(), FakeRobot()
    r._tilt = lambda *a, **k: None
    res = ab.run_bout(r, lambda: [], ab.BoutConfig(minutes=1), say=lambda *_: None, sleep=c.sleep, clock=c, stopped=lambda: False)
    assert res["ended"] == "no_board"
    assert "relax" not in r.calls and not any(isinstance(x, tuple) and x[0] == "claw" and x[2] == 120.0 for x in r.calls)       # nothing was moved
