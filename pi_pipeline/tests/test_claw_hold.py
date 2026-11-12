"""The survey's stand-up waits for the claw look worker (a slow camera made the look overrun its timed plan)."""
from pi_pipeline.behavior.driver import Effect, EffectKind, _Choreo


def test_due_steps_wait_while_the_claw_worker_runs():
    t = [0.0]
    c = _Choreo(clock=lambda: t[0])
    busy = [True]
    c.hold = lambda: busy[0]
    c.start("survey", [(1.0, Effect(EffectKind.SKILL, "kup", "stand"))])
    t[0] = 2.0
    assert c.pump() == [] and c.busy
    t[0] = 10.0
    assert c.pump() == []
    busy[0] = False
    t[0] = 10.5
    assert [e.payload for e in c.pump(10.5)] == ["kup"] or [e.payload for e in c.pump(11.0)] == ["kup"]


def test_the_hold_gives_up_after_its_cap():
    t = [0.0]
    c = _Choreo(clock=lambda: t[0])
    c.hold, c.hold_max_s = (lambda: True), 5.0
    c.start("survey", [(1.0, Effect(EffectKind.SKILL, "kup", "stand"))])
    out = []
    for now in (1.0, 3.0, 7.0, 7.5):
        t[0] = now
        out += c.pump()
    assert [e.payload for e in out] == ["kup"]
