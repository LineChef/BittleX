import random

from pi_pipeline.behavior import (
    BehaviorDriver, BehaviorRuntime, DriverInputs, EffectKind, EmergencyStop,
)
from pi_pipeline.behavior.bindings import MockBindings
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.voice.commands import match_local_command


class Clk:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


def _kinds(tick):
    return [e.kind for e in tick.effects]


# --------------------------------------------------------- the latch itself
def test_latch_and_entry_burst():
    es = EmergencyStop(freeze_token="kbalance")
    assert not es.halted
    assert es.halt() is True and es.halted
    assert es.halt() is False                       # idempotent
    burst = es.effects()
    kinds = [e.kind for e in burst]
    assert EffectKind.STOP in kinds and EffectKind.CHIRP in kinds
    assert any(e.kind is EffectKind.SKILL and e.payload == "kbalance" for e in burst)
    later = es.effects()                            # subsequent ticks: just STOP
    assert [e.kind for e in later] == [EffectKind.STOP]
    assert es.release() is True and not es.halted


# ------------------------------------------------------------ in the driver
def _driver():
    c = Clk()
    return BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                          clock=c, rng=random.Random(0)), c


def test_driver_halts_and_holds_until_released():
    d, c = _driver()
    t = d.tick(DriverInputs(halt=True))
    assert t.halted
    assert any(e.kind is EffectKind.SKILL and e.payload == "kbalance" for e in t.effects)
    assert EffectKind.CHIRP in _kinds(t)

    c.adv(1.0)
    t = d.tick(DriverInputs())                      # still halted, no new input
    assert t.halted and _kinds(t) == [EffectKind.STOP]

    c.adv(1.0)
    t = d.tick(DriverInputs(release=True))
    assert not t.halted


def test_halt_outranks_everything(tmp_path):
    d, c = _driver()
    d._vision = True
    # a meeting request + sleep command + a running choreography all lose to halt
    d.tick(DriverInputs(meet_name="Sam"))
    c.adv(0.3)
    t = d.tick(DriverInputs(halt=True, meet_name="Sam", told_sleep=True,
                            loud_sound=True, picked_up=True))
    assert t.halted
    # nothing but the emergency burst -- no enrollment SPEAK, no sleep kzz
    assert not any(e.kind is EffectKind.SPEAK for e in t.effects)
    assert not any(e.kind is EffectKind.SKILL and e.payload == "kzz" for e in t.effects)


def test_freeze_token_is_configurable():
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=c, rng=random.Random(0), estop_freeze_token="ksit")
    t = d.tick(DriverInputs(halt=True))
    assert any(e.kind is EffectKind.SKILL and e.payload == "ksit" for e in t.effects)


# ----------------------------------------------------------- in the runtime
def test_runtime_halt_dispatches_even_when_paused():
    c = Clk()
    d, _ = _driver()
    mb = MockBindings()
    rt = BehaviorRuntime(d, mb, hz=0, clock=c)
    rt.pause()
    assert rt.tick() is None                        # paused: normal ticks are no-ops
    rt.halt()
    perf = [a[0] for n, a, _k in mb.calls if n == "actuator.perform"]
    assert "kbalance" in perf                       # the freeze went out despite pause
    # and a subsequent tick still re-asserts the stop while paused+halted
    n_before = len(mb.calls)
    rt.tick()
    assert any(n == "actuator.stop" for n, _a, _k in mb.calls[n_before:])
    rt.release()
    rt.resume()


def test_runtime_accepts_posted_halt_release():
    c = Clk()
    d, _ = _driver()
    rt = BehaviorRuntime(d, MockBindings(), hz=0, clock=c)
    rt.post(halt=True)
    assert rt.tick().halted
    rt.post(release=True)
    assert not rt.tick().halted


# --------------------------------------------------------- the voice phrases
def test_voice_phrases_map_to_halt_and_resume():
    for p in ("emergency stop", "freeze", "G2 halt", "stop moving", "abort"):
        assert match_local_command(p) == "halt", p
    for p in ("resume", "you can move", "as you were", "carry on"):
        assert match_local_command(p) == "resume", p
    # an ordinary request is not a halt
    assert match_local_command("can you stop the kitchen timer") != "halt"
