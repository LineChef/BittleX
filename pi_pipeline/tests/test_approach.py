import random

from pi_pipeline.behavior import (
    ApproachConfig, ApproachTarget, BehaviorDriver, DriverInputs, EffectKind, Mode,
)
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.vision.feed import Detection


def person(cx=0.5, side=0.2, conf=0.9):
    return Detection("person", conf, cx - side / 2, 0.5 - side / 2, side, side)


class Clk:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


# ------------------------------------------------------------- the helper
def test_walks_toward_then_stops_close():
    c = Clk()
    a = ApproachTarget(ApproachConfig(close_area=0.20), clock=c)
    a.start(c())
    fx = a.decide([person(cx=0.8, side=0.15)], c())         # far, off to the right
    assert fx[0].kind is EffectKind.WALK and fx[0].payload > 0 and a.active

    c.adv(1)
    fx = a.decide([person(cx=0.52, side=0.55)], c())        # now big/close
    assert any(e.kind is EffectKind.STOP for e in fx)
    assert any(e.kind is EffectKind.CHIRP for e in fx)
    assert not a.active                                     # one-shot: disarmed on arrival


def test_gives_up_if_it_loses_sight():
    c = Clk()
    a = ApproachTarget(ApproachConfig(give_up_s=2.0), clock=c)
    a.start(c())
    a.decide([person()], c())
    c.adv(0.5)
    fx = a.decide([], c())                                  # lost -> scan, still active
    assert a.active and any(e.payload == "pan_sweep" for e in fx)
    c.adv(3.0)
    fx = a.decide([], c())
    assert not a.active and any(e.kind is EffectKind.STOP for e in fx)


def test_cancel_stops_it():
    c = Clk()
    a = ApproachTarget(clock=c)
    a.start(c())
    a.cancel()
    assert not a.active and a.decide([person()], c()) == []


# --------------------------------------------------- wired into the driver
def _drv(**kw):
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=c, rng=random.Random(0), **kw)
    return d, c


def test_come_here_enters_approach_and_walks():
    d, c = _drv(approach_cfg=ApproachConfig(close_area=0.9))
    t = d.tick(DriverInputs(come_here=True, frame=[person(cx=0.75)]))
    assert t.mode is Mode.APPROACH
    assert EffectKind.WALK in [e.kind for e in t.effects]


def test_come_here_is_cancelled_by_told_stop():
    d, c = _drv(approach_cfg=ApproachConfig(close_area=0.9))
    d.tick(DriverInputs(come_here=True, frame=[person(cx=0.7)]))
    c.adv(0.5)
    t = d.tick(DriverInputs(told_stop=True, frame=[person(cx=0.7)]))
    assert t.mode is not Mode.APPROACH
    assert not d.approach.active


def test_come_here_needs_vision():
    d, c = _drv(vision_available=False)
    t = d.tick(DriverInputs(come_here=True, frame=[person()]))
    assert t.mode is not Mode.APPROACH and not d.approach.active
