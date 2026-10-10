"""A near wall steers an exploring G2 away from it (behavior/driver.py `_wall_reflex`); prototype, `G2_WALL_STEER=0` turns it off."""
import random

from pi_pipeline.behavior import BehaviorDriver, DriverInputs, EffectKind, Mode
from pi_pipeline.behavior.chirps import ChirpMood
from pi_pipeline.personality.traits import BehaviorParams
from pi_pipeline.tests.test_driver import Clk, kinds, payloads
from pi_pipeline.vision.wall_distance import WallReading


def _explorer(monkeypatch, steer="1"):
    monkeypatch.setenv("G2_WALL_STEER", steer)
    c = Clk()
    d = BehaviorDriver(BehaviorParams(), clock=c, rng=random.Random(0), chirps=True)
    c.adv(11)
    assert d.tick(DriverInputs(arm_explore=True, frame=[])).mode is Mode.EXPLORE
    return d, c


def _wall(c, state="near", confirmed=True, turn="left", inches=9.0, age=0.5):
    return WallReading(c() - age, state, inches, turn, confirmed)


def test_a_confirmed_near_wall_turns_him_toward_the_open_side_with_a_soft_sound_once_per_look(monkeypatch):
    d, c = _explorer(monkeypatch)
    w = _wall(c, turn="left")
    t = d.tick(DriverInputs(frame=[], wall=w))
    turns = payloads(t, EffectKind.TURN)
    assert len(turns) == 1 and turns[0] < 0                                   # left is negative
    assert ChirpMood.AVOID in payloads(t, EffectKind.CHIRP)
    assert any(p[0] == "wall.steer" for p in payloads(t, EffectKind.DIAG))
    c.adv(5.0)                                                                # the turn is done; the SAME look is not acted on again
    t2 = d.tick(DriverInputs(frame=[], wall=w))
    assert ChirpMood.AVOID not in payloads(t2, EffectKind.CHIRP)
    c.adv(1.0)
    t3 = d.tick(DriverInputs(frame=[], wall=_wall(c, turn="right", age=0.2)))  # a new near look: turn right
    assert [x for x in payloads(t3, EffectKind.TURN) if x > 0]


def test_one_unconfirmed_look_a_stale_look_a_far_wall_or_the_switch_off_never_steer(monkeypatch):
    d, c = _explorer(monkeypatch)
    for w in (_wall(c, confirmed=False), _wall(c, age=30.0), _wall(c, state="far", inches=20.0), _wall(c, state="clear", inches=None), None):
        t = d.tick(DriverInputs(frame=[], wall=w))
        assert ChirpMood.AVOID not in payloads(t, EffectKind.CHIRP)
        c.adv(5.0)
    d2, c2 = _explorer(monkeypatch, steer="0")
    t = d2.tick(DriverInputs(frame=[], wall=_wall(c2)))
    assert ChirpMood.AVOID not in payloads(t, EffectKind.CHIRP) and not any(p[0] == "wall.steer" for p in payloads(t, EffectKind.DIAG))


def test_a_blocked_wall_needs_no_second_look_and_turns_harder_and_only_while_exploring(monkeypatch):
    d, c = _explorer(monkeypatch)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="blocked", confirmed=False, turn="right", inches=0.0)))
    big = payloads(t, EffectKind.TURN)
    assert big and big[0] > 1.0                                               # about 80 degrees
    idle = BehaviorDriver(BehaviorParams(), clock=(c2 := Clk()), rng=random.Random(0))
    c2.adv(11)
    t = idle.tick(DriverInputs(frame=[], wall=_wall(c2, state="blocked", confirmed=True)))
    assert t.mode is not Mode.EXPLORE and EffectKind.TURN not in kinds(t)      # a wall look does nothing outside a roam


def test_the_turn_away_sound_is_two_soft_falling_notes_and_the_sink_obeys_its_switch(monkeypatch):
    import numpy as np
    from pi_pipeline.app import sinks
    from pi_pipeline.voice import prompt_tones as pt
    pcm = pt.render_turn_away()
    assert 0.3 < pcm.size / 48000 < 0.45 and 0 < abs(int(pcm.max())) < 0.8 * pt.DEFAULT_PEAK * 32767 + 1
    monkeypatch.setenv("G2_WALL_SOUND", "0")
    assert sinks._speaker_avoid_sound() is True                                # off: silent, and True so no buzzer notes either
