"""The one-skill arm test (behavior/arm_skill_test.py): what it sends, what it calls a lean, a tip and a fall, and what it never accepts."""
import json

from pi_pipeline.behavior import arm_skill_test as t


class Clock:
    now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.now += s


class Link:
    def __init__(self):
        self.sent = []

    def send(self, c, **kw):
        self.sent.append(c)


class FakeRobot:
    def __init__(self, rolls=(), pitches=(), fell_after=None, base=(1.0, -2.0)):
        self._lk, self._roll, self._pitch = Link(), [], []
        self._rolls, self._pitches, self.fell_after, self.base, self.polls, self.tx = list(rolls), list(pitches), fell_after, base, 0, []

    def stand_up(self):
        return "ok"

    def _tilt(self, *a, **k):
        return self.base

    def _tx(self, c):
        self.tx.append(c)

    def _fell(self):
        self.polls += 1
        if self._rolls:
            self._roll.append(self._rolls.pop(0))
        if self._pitches:
            self._pitch.append(self._pitches.pop(0))
        return self.fell_after is not None and self.polls >= self.fell_after


def test_the_verdict_thresholds():
    assert t.verdict(5, False) == "ok" and t.verdict(t.LEAN_DEG, False) == "lean" and t.verdict(t.TIPPED_DEG, False) == "tipped" and t.verdict(0, True) == "fell"


def test_it_sends_the_skill_then_gb_and_calls_a_small_swing_ok():
    c = Clock()
    r = FakeRobot(rolls=[-1.0, 3.0, 8.0], pitches=[-2.0, 0.0, 10.0])
    res = t.run_skill(r, "launch", watch_s=1.0, say=lambda *_: None, sleep=c.sleep, clock=c)
    assert r._lk.sent == ["klaunch"] and r.tx == ["gP", "gb"]                              # the skill, then gyro balance off, never gb beside a firmware gait
    assert res["verdict"] == "ok" and res["max_roll_dev"] == 10.0 and res["max_pitch_dev"] == 9.0


def test_a_big_lean_a_tip_and_a_fall_are_told_apart():
    c = Clock()
    assert t.run_skill(FakeRobot(rolls=[40.0]), "tossF", watch_s=1.0, say=lambda *_: None, sleep=c.sleep, clock=c)["verdict"] == "lean"
    c = Clock()
    assert t.run_skill(FakeRobot(pitches=[70.0]), "tossF", watch_s=1.0, say=lambda *_: None, sleep=c.sleep, clock=c)["verdict"] == "tipped"
    c = Clock()
    res = t.run_skill(FakeRobot(fell_after=2), "tossF", watch_s=5.0, say=lambda *_: None, sleep=c.sleep, clock=c)
    assert res["verdict"] == "fell" and res["fell"]


def test_the_order_is_mildest_first_and_clap_needs_its_own_flag():
    assert t.ORDER[0] == "launch" and t.ORDER.index("toss") < t.ORDER.index("tossF")
    assert "clap" not in t.ORDER and "clap" in t.EXTRA
    assert all(("k" + s) not in __import__("pi_pipeline.link.opencat", fromlist=["x"]).DISABLED_SKILLS for s in t.ORDER + t.EXTRA)


def test_the_log_is_one_json_file_per_run(tmp_path, monkeypatch):
    monkeypatch.setattr(t, "LOG_DIR", str(tmp_path))
    p = t.write_log({"skill": "launch", "verdict": "ok"}, {"pack_pct": 80})
    d = json.load(open(p))
    assert d["skill"] == "launch" and d["pack_pct"] == 80 and p.endswith("_launch.json")
