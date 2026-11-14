"""gait/body_guards.py: the guard, the sag recovery and the responses to a fall and to a deaf board, built ONE way for every mode (owner, 2026-11-13)."""
import threading
import types

from pi_pipeline.gait import body_guards as BG
from pi_pipeline.gait.stand_guard import StandGuard


def imu_line(roll, pitch):
    return f"ICM: 0.00 0.00 1.00 0.0 {pitch:.1f} {roll:.1f}"


class Link:
    def __init__(self, last="kbalance"):
        self.sent, self.queue, self.last_motion_command = [], [], last

    def send(self, c, **kw):
        self.sent.append(c)
        return ""

    def poll_imu(self):
        q, self.queue = self.queue, []
        return q


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


def _installed(monkeypatch, link, clock, **kw):
    """`install()` with the guard's clock injected and its thread not started: the test drives `tick()`."""
    class Driven(StandGuard):
        def __init__(self, *a, **k):
            super().__init__(*a, clock=clock, sleep=lambda s: None, **k)

        def start(self):
            return self
    monkeypatch.setattr(BG, "StandGuard", Driven)
    settings = types.SimpleNamespace(stand_guard=True, balance_off_idle=True, stand_reassert_s=60.0)
    got = {"fall": [], "silent": [], "hold": 0, "release": 0}
    g = BG.install(link, settings=settings, new_consumer=lambda: link, release_consumer=lambda c: None, is_busy=lambda: False, on_fall=lambda: got["fall"].append(1),
                   on_silent=lambda s: got["silent"].append(round(s)), hold=lambda: got.__setitem__("hold", got["hold"] + 1), release=lambda: got.__setitem__("release", got["release"] + 1), **kw)
    return g, got


def test_the_installed_guard_ends_the_mode_on_a_fall_and_on_a_deaf_board_the_same_way(monkeypatch):
    link, clock = Link(), Clock()
    g, got = _installed(monkeypatch, link, clock)
    for roll in (5.0, 70.0, 75.0, 80.0, 80.0, 80.0):                     # tipped past 60 degrees for 0.3 s: the body's fall
        clock.t += 0.2
        link.queue = [imu_line(roll, 3.0)]
        g.tick()
    assert got["fall"] == [1] and "d" in link.sent                         # the mode's handler once, and he was laid down
    quiet = Link()
    g2, got2 = _installed(monkeypatch, quiet, Clock())
    clock2 = g2._clock
    for _ in range(int(25 / 0.5)):                                         # 25 s of no motion data: the body's 20 s
        clock2.t += 0.5
        g2.tick()
    assert len(got2["silent"]) == 1 and got2["silent"][0] >= 20


def test_a_sag_runs_the_recovery_between_the_modes_hold_and_release(monkeypatch):
    link, clock = Link(), Clock()
    g, got = _installed(monkeypatch, link, clock)
    calls = []
    import pi_pipeline.behavior.ball_chase as bc
    monkeypatch.setattr(bc.SerialRobot, "recover_sag", lambda self, tilt=None: calls.append(tilt) or "ok")
    sag = BG.make_sag_recover(new_consumer=lambda: link, release_consumer=lambda c: calls.append("released"), hold=lambda: calls.append("hold"), release=lambda: calls.append("release"))
    sag(roll=-15.0, pitch=2.0)
    assert calls == ["hold", (2.0, -15.0), "release", "released"]
    assert g._is_walking is not None and g._is_walking() is False
    link.last_motion_command = "kwkF"
    assert g._is_walking() is True                                         # walking sag is watched in every mode


def test_the_fall_words_follow_the_horn_and_never_raise():
    order = []
    th = BG.announce_fall(lambda t: order.append(t), horn=lambda: order.append("horn"))
    th.join(2.0)
    assert order == ["horn", BG.FALL_WORDS]
    th = BG.announce_fall(lambda t: 1 / 0, horn=lambda: 1 / 0)
    th.join(2.0)
    assert not th.is_alive()


def test_a_deaf_board_is_halted_laid_down_without_waiting_and_explained():
    link, order, said = Link(), [], []
    th = BG.lay_down_deaf_board(link, said.append, halt=lambda: order.append(list(link.sent)))
    th.join(2.0)
    assert order == [[]] and link.sent == ["gb", "krest"] and said == [BG.DEAF_WORDS]       # halted FIRST, then gb and rest, then the words


def test_both_modes_build_their_guard_and_responses_through_the_shared_module():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for rel in ("voice/__main__.py", "explore_session.py"):
        text = (root / rel).read_text()
        assert "body_guards.install(" in text and "body_guards.lay_down_deaf_board(" in text, rel
        assert "StandGuard(" not in text, rel
    assert "body_guards.announce_fall(" in (root / "voice/__main__.py").read_text() and "body_guards.announce_fall(" in (root / "explore_session.py").read_text()
    assert threading.current_thread() is not None
