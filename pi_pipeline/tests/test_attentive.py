import random

from pi_pipeline.behavior import (
    AttentiveConfig, AttentiveLook, BehaviorDriver, DriverInputs, EffectKind,
    Mode, Posture,
)
from pi_pipeline.behavior.novelty import Novelty
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.vision.feed import Detection


def det(label, cx=0.5, side=0.3, conf=0.9):
    return Detection(label, conf, cx - side / 2, 0.5 - side / 2, side, side)


class Clk:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


# ----------------------------------------------------------- the layer itself
def _look(**cfg):
    c = Clk()
    a = AttentiveLook(Novelty(), AttentiveConfig(**cfg), clock=c)
    return a, c


def test_gaze_follows_the_nearest_person():
    a, c = _look(follow_deadband_rad=0.05)
    c.adv(1)
    fx = a.decide([det("face", cx=0.8)], resting=False, now=c())
    assert fx and fx[0].kind is EffectKind.HEAD and fx[0].payload > 0   # look right


def test_gaze_follow_ignores_tiny_bearing():
    a, c = _look(follow_deadband_rad=0.3)
    c.adv(1)
    fx = a.decide([det("face", cx=0.52)], resting=False, now=c())      # nearly centered
    assert not any(e.reason == "follow person" for e in fx)


def test_novelty_reaction_peers_and_chirps_when_not_resting():
    a, c = _look(react_cooldown_s=1.0)
    c.adv(2)
    fx = a.decide([det("mug", cx=0.3)], resting=False, now=c())
    kinds = [e.kind for e in fx]
    assert EffectKind.HEAD in kinds and EffectKind.SKILL in kinds and EffectKind.CHIRP in kinds
    # a second look right after is on cooldown (and the object is no longer novel)
    c.adv(0.2)
    assert not a.decide([det("mug", cx=0.3)], resting=False, now=c())


def test_resting_reaction_is_head_only_no_body_skill():
    a, c = _look(react_cooldown_s=1.0)
    c.adv(2)
    fx = a.decide([det("mug", cx=0.3)], resting=True, now=c())
    assert not any(e.kind is EffectKind.SKILL for e in fx)             # no peer bow while lying
    assert any(e.kind is EffectKind.HEAD for e in fx)


def test_periodic_scan_fires_on_its_interval_with_no_camera():
    c = Clk()
    a = AttentiveLook(Novelty(), AttentiveConfig(scan_every_s=30.0), clock=c,
                      vision_available=False)
    assert a.decide([], resting=False, now=c()) == []                 # not due yet
    c.adv(31)
    fx = a.decide([], resting=False, now=c())
    assert fx and fx[0].payload == "pan_sweep"


# --------------------------------------------- wired into the driver's IDLE
class DClk:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


def test_driver_runs_attentive_while_sitting_idle():
    c = DClk()
    d = BehaviorDriver(BehaviorParams(idle_sit_secs=3, idle_rest_secs=999),
                       clock=c, rng=random.Random(0),
                       attentive_cfg=AttentiveConfig(follow_deadband_rad=0.05))
    c.adv(5)
    d.tick(DriverInputs())                         # -> SIT
    c.adv(1)
    t = d.tick(DriverInputs(frame=[det("face", cx=0.85)], person_present=True))
    assert t.posture is Posture.SIT and t.mode is Mode.IDLE
    assert any(e.kind is EffectKind.HEAD and e.reason == "follow person"
               for e in t.effects)


def test_attentive_does_not_walk():
    c = DClk()
    d = BehaviorDriver(BehaviorParams(idle_sit_secs=3, idle_rest_secs=999),
                       clock=c, rng=random.Random(0))
    c.adv(5); d.tick(DriverInputs())
    for _ in range(20):
        c.adv(2)
        t = d.tick(DriverInputs(frame=[det("mug", cx=0.2), det("face", cx=0.9)],
                                person_present=True))
        assert EffectKind.WALK not in [e.kind for e in t.effects]
        assert EffectKind.TURN not in [e.kind for e in t.effects]
