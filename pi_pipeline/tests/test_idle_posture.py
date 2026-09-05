from pi_pipeline.behavior.idle_posture import (
    IdlePosture, IdlePostureConfig, Posture, PostureAction,
)


class Clk:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


def _mk(**cfg):
    c = Clk()
    return IdlePosture(IdlePostureConfig(sit_after_s=20, rest_after_s=90, **cfg), clock=c), c


def _to_resting(ip, c):
    c.adv(21); ip.update()      # -> SIT
    c.adv(91); ip.update()      # -> RESTING


def test_staged_descent_active_sit_rest():
    ip, c = _mk()
    assert ip.update()[0] is Posture.ACTIVE
    c.adv(21)
    assert ip.update() == (Posture.SIT, PostureAction.GO_SIT)
    c.adv(91)
    assert ip.update() == (Posture.RESTING, PostureAction.GO_REST)


def test_activity_rouses_from_rest():
    ip, c = _mk()
    _to_resting(ip, c)
    assert ip.posture is Posture.RESTING
    ip.on_activity()
    assert ip.posture is Posture.WAKING
    assert ip.update()[1] is PostureAction.NONE      # holds while caller choreographs
    ip.wake_done()
    assert ip.posture is Posture.ACTIVE


def test_wake_timeout_autocompletes():
    ip, c = _mk(wake_timeout_s=4)
    _to_resting(ip, c)
    ip.on_activity()                                  # WAKING
    c.adv(5)
    assert ip.update()[0] is Posture.ACTIVE


def test_stay_command_sits_and_never_rests():
    ip, c = _mk()
    ip.on_stay_command()
    assert ip.posture is Posture.SIT
    c.adv(10_000)
    assert ip.update()[0] is Posture.SIT             # stays sat forever


def test_safe_to_rest_gate_caps_at_sit():
    ip, c = _mk()
    c.adv(21); ip.update()                            # SIT
    c.adv(200)
    assert ip.update(safe_to_rest=False)[0] is Posture.SIT
    assert ip.update(safe_to_rest=True)[0] is Posture.RESTING


def test_person_present_delays_rest():
    ip, c = _mk(person_rest_multiplier=4.0)
    c.adv(21); ip.update()                            # SIT
    c.adv(100)
    assert ip.update(person_present=True)[0] is Posture.SIT   # 90*4 not elapsed
    c.adv(300)
    assert ip.update(person_present=True)[0] is Posture.RESTING


def test_exploring_holds_active():
    ip, c = _mk()
    c.adv(500)
    assert ip.update(exploring=True)[0] is Posture.ACTIVE


def test_conversation_sits_but_never_rests():
    ip, c = _mk()
    c.adv(21)
    assert ip.update(in_conversation=True) == (Posture.SIT, PostureAction.GO_SIT)
    c.adv(500)
    assert ip.update(in_conversation=True)[0] is Posture.SIT


def test_handled_forces_wake():
    ip, c = _mk()
    _to_resting(ip, c)
    assert ip.update(handled=True)[1] is PostureAction.WAKE
    assert ip.posture is Posture.WAKING


def test_life_signs_peek_and_nudge():
    ip, c = _mk(peek_s=120)
    _to_resting(ip, c)
    assert ip.update()[1] is PostureAction.NONE
    assert ip.update(nudge=True)[1] is PostureAction.PEEK       # nearby sound -> look
    c.adv(121)
    assert ip.update()[1] is PostureAction.PEEK                 # periodic peek


def test_breathing_bob_when_enabled():
    ip, c = _mk(breathing=True, breathing_period_s=4, peek_s=999)
    _to_resting(ip, c)
    c.adv(5)
    assert ip.update()[1] is PostureAction.LIFE_SIGN
