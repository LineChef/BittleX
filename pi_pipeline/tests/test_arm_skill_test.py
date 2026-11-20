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


def test_a_silent_board_sends_nothing_and_is_not_called_ok():
    """2026-11-15: the BiBoard was off; every read got no answer. The skill test must say so, not report a quiet body as ok."""
    r = FakeRobot()
    r._tilt = lambda *a, **k: None
    res = t.run_skill(r, "launch", watch_s=1.0, say=lambda *_: None, sleep=lambda s: None)
    assert res["verdict"] == "no_board" and r._lk.sent == []


def test_board_answers_needs_a_parseable_imu_frame(monkeypatch):
    from pi_pipeline.link import imu_print

    class L:
        def __init__(self, lines):
            self.lines, self.sent = lines, []

        def send(self, c, **kw):
            self.sent.append(c)

        def poll_imu(self):
            out, self.lines = self.lines, []
            return out
    c = Clock()
    assert imu_print.board_answers(L([]), 1.0, sleep=c.sleep, clock=c) is False
    c = Clock()
    ok = L(["ICM:  0.01  0.02  1.00   10.0   0.0   0.0"])
    assert imu_print.board_answers(ok, 1.0, sleep=c.sleep, clock=c) is True and ok.sent == ["gP"]


def test_trace_summary_gives_onset_peak_and_rate():
    s = t.trace_summary([0.0, 0.1, 0.2, 0.3], [0.0, 1.0, 5.0, 3.0], [0.0, 0.0, 2.0, 1.0], (0.0, 0.0))
    assert s["frames"] == 4 and s["frame_hz"] == 10.0 and s["onset_s"] == 0.2 and s["peak_s"] == 0.2
    assert s["imu_trace"][2] == [0.2, 5.0, 2.0]
    quiet = t.trace_summary([0.0, 0.1], [0.5, 0.6], [0.0, 0.1], (0.0, 0.0))
    assert quiet["onset_s"] is None
    assert t.trace_summary([], [], [], (0.0, 0.0))["peak_s"] is None


def test_run_skill_logs_the_trace_the_send_time_and_the_pictures():
    c = Clock()
    r = FakeRobot(rolls=[-1.0, 3.0, 8.0], pitches=[-2.0, 0.0, 10.0])
    res = t.run_skill(r, "launch", watch_s=1.0, say=lambda *_: None, sleep=c.sleep, clock=c, wall=lambda: 1000.25, capture=lambda: [{"n": 1, "file": None, "detections": []}])
    assert res["sent_at"] == 1000.25 and res["sent_iso"].endswith(".250")
    assert res["frames"] == 3 and len(res["imu_trace"]) == 3 and res["peak_s"] is not None
    assert res["pictures"] == [{"n": 1, "file": None, "detections": []}]


def test_the_landing_record_and_update_log(tmp_path):
    answers = iter(["36", "left", "y", "bounced"])
    assert t.ask_landing(ask=lambda _p: next(answers)) == {"landed_in": 36.0, "direction": "left", "left_claw": True, "note": "bounced"}
    skip = t.ask_landing(ask=lambda _p: "")
    assert skip["landed_in"] is None and skip["left_claw"] is None
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"skill": "launch"}))
    assert t.update_log(str(f), {"landing": {"landed_in": 5.0}}) and json.loads(f.read_text())["landing"]["landed_in"] == 5.0
    assert not t.update_log(str(tmp_path / "missing.json"), {})


def test_the_pick_skills_are_allowed_and_not_in_the_throw_order():
    assert t.PICKS == ("pickF", "pickD") and not set(t.PICKS) & set(t.ORDER + t.EXTRA)
