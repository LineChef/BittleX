import random

from pi_pipeline.behavior import BehaviorDriver, DriverInputs, EffectKind, Mode
from pi_pipeline.behavior.explore_request import ExploreRequester, answer_kind
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.tests.test_driver import Clk, payloads


def test_answers_are_read_from_short_replies_only():
    for t in ("Yes", "yeah.", "Gee two, go ahead", "ok", "Sure thing!"):
        assert answer_kind(t) == "yes", t
    for t in ("No", "not now", "Gee Two, later", "stay here"):
        assert answer_kind(t) == "no", t
    for t in ("yes but first tell me the weather", "what time is it", "", None):
        assert answer_kind(t) is None, t


def make(idle=None, ok=None):
    idle, ok = idle or [0.0], ok or [True]
    t = [0.0]
    asked = []
    r = ExploreRequester(idle_s=lambda: idle[0], eligible=lambda: ok[0], ask=lambda: asked.append(t[0]), ask_after_s=100.0, window_s=30.0, clock=lambda: t[0])
    return r, t, asked, idle, ok


def test_he_asks_once_after_the_idle_time_and_only_when_he_may():
    r, t, asked, idle, ok = make([0.0], [False])
    t[0], idle[0] = 150.0, 150.0
    assert not r.tick() and asked == []                       # not eligible (busy, asleep, battery)
    ok[0] = True
    assert r.tick() and len(asked) == 1 and r.is_open()
    assert not r.tick() and len(asked) == 1                   # one question at a time


def test_a_yes_closes_the_question_and_resets_the_wait_a_no_or_silence_doubles_it():
    r, t, asked, idle, ok = make()
    t[0], idle[0] = 150.0, 150.0
    r.tick()
    assert r.answer("what is that") is None and r.is_open()   # not an answer: still open
    assert r.answer("yes") == "yes" and not r.is_open()
    assert r.answer("yes") is None                            # nothing open: a yes is ignored
    t[0], idle[0] = 260.0, 260.0
    assert r.tick()                                           # waited the base 100 s since the last question
    assert r.answer("no") == "no"
    t[0], idle[0] = 400.0, 400.0
    assert not r.tick()                                       # now 200 s
    t[0], idle[0] = 470.0, 470.0
    assert r.tick() and len(asked) == 3
    t[0] = 520.0                                              # 50 s: the 30 s window passed unanswered
    assert not r.tick() and not r.is_open()


def test_the_driver_reports_look_when_idle_and_move_when_roaming(monkeypatch):
    c = Clk()
    d = BehaviorDriver(BehaviorParams(), clock=c, rng=random.Random(0), chirps=True)
    assert d.phase == "look"
    c.adv(11)
    t = d.tick(DriverInputs(arm_explore=True, frame=[]))
    assert t.mode is Mode.EXPLORE and d.phase in ("move", "pause")
    assert any(p[0] == "phase" for p in payloads(t, EffectKind.DIAG))
