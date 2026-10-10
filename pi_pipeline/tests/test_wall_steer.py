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


def _wall(c, state="near", confirmed=True, turn="left", inches=9.0, age=0.5, groups=0, votes=None, prev=None, prev_age=None):
    return WallReading(c() - age, state, inches, turn, confirmed, groups, (2 if groups >= 3 else 0) if votes is None else votes, prev, prev_age)


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
    for w in (_wall(c, state="far", inches=20.0, confirmed=False, groups=2), _wall(c, age=30.0), _wall(c, state="far", inches=20.0), _wall(c, state="clear", inches=None), None):
        t = d.tick(DriverInputs(frame=[], wall=w))
        assert ChirpMood.AVOID not in payloads(t, EffectKind.CHIRP)
        c.adv(5.0)
    d2, c2 = _explorer(monkeypatch, steer="0")
    t = d2.tick(DriverInputs(frame=[], wall=_wall(c2)))
    assert ChirpMood.AVOID not in payloads(t, EffectKind.CHIRP) and not any(p[0] == "wall.steer" for p in payloads(t, EffectKind.DIAG))


def test_a_blocked_wall_means_he_hit_it_so_he_says_oof_backs_up_and_turns_around_and_only_while_exploring(monkeypatch):
    d, c = _explorer(monkeypatch)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="blocked", confirmed=False, turn="right", inches=0.0)))
    assert ChirpMood.HIT in payloads(t, EffectKind.CHIRP) and any(p[0] == "wall.hit" for p in payloads(t, EffectKind.DIAG))
    c.adv(0.5)
    t = d.tick(DriverInputs(frame=[]))
    assert "kbkF" in payloads(t, EffectKind.SKILL)                              # back up
    c.adv(2.4)
    t = d.tick(DriverInputs(frame=[]))
    assert "kbalance" in payloads(t, EffectKind.SKILL)                           # stop backing up
    c.adv(0.6)
    t = d.tick(DriverInputs(frame=[]))
    big = payloads(t, EffectKind.TURN)
    assert big and big[0] > 2.0 and big[0].__class__.__name__ == "UrgentTurn"    # about 150 degrees toward the open side, replacing any running turn
    idle = BehaviorDriver(BehaviorParams(), clock=(c2 := Clk()), rng=random.Random(0))
    c2.adv(11)
    t = idle.tick(DriverInputs(frame=[], wall=_wall(c2, state="blocked", confirmed=True)))
    assert t.mode is not Mode.EXPLORE and EffectKind.TURN not in kinds(t) and ChirpMood.HIT not in payloads(t, EffectKind.CHIRP)      # a wall look does nothing outside a roam


def test_a_wall_at_six_inches_on_three_groups_is_a_hit_but_a_wall_at_ten_inches_is_only_a_turn_and_the_switch_turns_it_off(monkeypatch):
    d, c = _explorer(monkeypatch)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="near", inches=10.0, groups=4, turn="left")))
    assert ChirpMood.AVOID in payloads(t, EffectKind.CHIRP) and ChirpMood.HIT not in payloads(t, EffectKind.CHIRP)
    c.adv(15.0)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="near", inches=5.0, groups=3, turn="left")))
    assert ChirpMood.HIT in payloads(t, EffectKind.CHIRP)
    c.adv(30.0)
    monkeypatch.setenv("G2_HIT_WALL", "0")
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="blocked", inches=0.0, groups=5)))
    assert ChirpMood.HIT not in payloads(t, EffectKind.CHIRP)


def test_the_hit_sound_is_a_long_falling_oof():
    from pi_pipeline.voice import prompt_tones as pt
    pcm = pt.render_hit()
    assert 0.9 < pcm.size / 48000 < 1.2 and abs(abs(int(pcm.max())) / (pt.DEFAULT_PEAK * 32767) - 2.0) < 0.3


def test_the_turn_away_sound_is_two_soft_falling_notes_and_the_sink_obeys_its_switch(monkeypatch):
    import numpy as np
    from pi_pipeline.app import sinks
    from pi_pipeline.voice import prompt_tones as pt
    pcm = pt.render_turn_away()
    assert 0.3 < pcm.size / 48000 < 0.45 and abs(abs(int(pcm.max())) / (pt.DEFAULT_PEAK * 32767) - 2.0) < 0.15      # 200% of the usual level
    monkeypatch.setenv("G2_WALL_SOUND", "0")
    assert sinks._speaker_avoid_sound() is True                                # off: silent, and True so no buzzer notes either


def test_at_the_start_of_a_roam_he_walks_straight_before_any_exploring_turn(monkeypatch):
    from pi_pipeline.behavior.explore import ExploreAction, ExploreDecision
    d, c = _explorer(monkeypatch)
    d.explorer.decide = lambda frame, now: ExploreDecision(ExploreAction.TURN, turn=0.8, reason="new heading")
    t = d.tick(DriverInputs(frame=[]))
    assert EffectKind.TURN not in kinds(t) and EffectKind.WALK in kinds(t)       # inside the first 8 s: straight ahead
    c.adv(9.0)
    t = d.tick(DriverInputs(frame=[]))
    assert EffectKind.TURN in kinds(t)                                            # then the explorer may turn
    c.adv(1.0)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="near", confirmed=False, turn="left", inches=10.0, groups=4)))
    assert any(isinstance(p, float) and p < 0 for p in payloads(t, EffectKind.TURN))      # a wall turn is never held back


def test_a_wall_turn_cancels_a_turn_that_is_already_running():
    from pi_pipeline.app.sinks import WalkerSink
    from pi_pipeline.behavior.driver import UrgentTurn

    class Link:
        last_motion_command = ""
        def __init__(self): self.sent = []
        def send(self, c, **k): self.sent.append(c)
    t = [100.0]
    link = Link()
    w = WalkerSink(link, clock=lambda: t[0])
    w.turn(0.9)                                                                 # the explorer's own turn: runs a few seconds
    n = len(link.sent)
    w.turn(-0.9)                                                                # a normal turn is ignored while it runs
    assert len(link.sent) == n
    w.turn(UrgentTurn(-0.9), urgent=True)                                       # a wall turn replaces it at once
    assert len(link.sent) == n + 1


def test_a_wall_ahead_is_acted_on_at_24_inches_when_three_groups_agree_and_at_12_inches_from_a_single_look(monkeypatch):
    d, c = _explorer(monkeypatch)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=20.0, confirmed=False, groups=3, turn="right")))
    assert [p for p in payloads(t, EffectKind.TURN) if p > 0] and ChirpMood.AVOID in payloads(t, EffectKind.CHIRP)        # three groups at 24 in or closer
    c.adv(6.0)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="near", inches=10.0, confirmed=False, groups=1, turn="left")))
    assert [p for p in payloads(t, EffectKind.TURN) if p < 0]                                                         # one look at 12 in or closer is enough
    c.adv(6.0)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=20.0, confirmed=False, groups=2)))
    assert ChirpMood.AVOID not in payloads(t, EffectKind.CHIRP)                                                       # two groups at 24 in is not yet a wall ahead


def test_a_one_off_glare_look_at_24_inches_is_not_a_wall_ahead_but_two_of_three_looks_are(monkeypatch):
    d, c = _explorer(monkeypatch)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=20.0, confirmed=False, groups=4, votes=1, turn="right")))
    assert ChirpMood.AVOID not in payloads(t, EffectKind.CHIRP)                       # one vote only
    c.adv(4.0)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=20.0, confirmed=False, groups=4, votes=2, turn="right")))
    assert ChirpMood.AVOID in payloads(t, EffectKind.CHIRP)


def test_stuck_at_the_same_close_wall_for_two_looks_without_turning_counts_as_a_hit_and_a_turn_in_between_does_not(monkeypatch):
    d, c = _explorer(monkeypatch)
    # first reaction: a turn away at 14 in (a wall ahead), so a following look at the same wall is NOT "stuck" (he has turned since)
    d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=14.0, confirmed=False, groups=4, votes=2, turn="left", prev=14.0, prev_age=3.0)))
    c.adv(12.0)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=14.5, confirmed=False, groups=4, votes=1, prev=14.0, prev_age=3.0)))
    assert ChirpMood.HIT not in payloads(t, EffectKind.CHIRP)                          # the previous look came after his turn only if no reaction lay between
    c.adv(30.0)
    # two looks 3 s apart at 14 in with no reaction in between: pinned against it
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=14.2, confirmed=False, groups=4, votes=1, prev=14.0, prev_age=3.0)))
    assert ChirpMood.HIT in payloads(t, EffectKind.CHIRP) and any("stuck" in p[1] for p in payloads(t, EffectKind.DIAG))


def test_a_wall_ahead_cuts_the_current_leg_to_what_is_left_before_it(monkeypatch):
    d, c = _explorer(monkeypatch)
    d.tick(DriverInputs(frame=[]))
    d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=33.0, confirmed=False, groups=0, votes=0, turn=None)))
    assert d.explorer._leg_cap is not None and abs(d.explorer._leg_cap - (33.0 - 12.0) / 3.5) < 0.01       # 21 in left at 3.5 in/s = 6 s
    d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=14.0, confirmed=False, groups=0, votes=0, turn=None, age=0.1)))
    assert d.explorer._leg_cap >= 1.5 and d.explorer._leg_cap <= 6.0                                        # never shorter than 1.5 s, never longer than before


def test_a_new_leg_after_a_wall_look_turns_toward_the_open_side_and_without_one_the_explorer_is_unchanged(monkeypatch):
    from pi_pipeline.behavior.explore import ExploreAction, ExploreDecision
    d, c = _explorer(monkeypatch)
    c.adv(12.0)
    d.explorer.decide = lambda frame, now: ExploreDecision(ExploreAction.TURN, turn=-0.2, reason="new leg")            # a random heading to the left
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=40.0, confirmed=False, groups=0, votes=0, turn="right")))
    assert [p for p in payloads(t, EffectKind.TURN) if p > 0.5]                                                          # sent right, at least 0.6 rad
    c.adv(3.0)
    t = d.tick(DriverInputs(frame=[]))                                                                                    # no wall look: his own heading stands
    assert [p for p in payloads(t, EffectKind.TURN) if abs(p + 0.2) < 1e-9]
    monkeypatch.setenv("G2_LEG_TURN_OPEN", "0")
    c.adv(3.0)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="far", inches=40.0, confirmed=False, groups=0, votes=0, turn="right")))
    assert [p for p in payloads(t, EffectKind.TURN) if abs(p + 0.2) < 1e-9]                                               # switched off


def test_an_imu_contact_signal_starts_the_hit_sequence_even_when_vision_sees_no_wall_and_is_used_once(monkeypatch):
    """2026-10-10: two walk legs showed the stall signature while the wall estimator said clear; the IMU contact signal is a second way to know he hit something."""
    d, c = _explorer(monkeypatch)
    t = d.tick(DriverInputs(frame=[], wall=_wall(c, state="clear", inches=None, confirmed=False)))
    assert ChirpMood.HIT not in payloads(t, EffectKind.CHIRP)
    d.note_contact({"mean_jitter_deg": 7.0})
    c.adv(0.2)
    t = d.tick(DriverInputs(frame=[], wall=None))                               # no wall look at all
    assert ChirpMood.HIT in payloads(t, EffectKind.CHIRP) and any(p[0] == "wall.hit" for p in payloads(t, EffectKind.DIAG))
    assert ("contact", "hit") in payloads(t, EffectKind.CAPTURE)                # and the instant diagnosis frames
    c.adv(0.5)
    assert "kbkF" in payloads(d.tick(DriverInputs(frame=[], wall=None)), EffectKind.SKILL)
    c.adv(15.0)
    t = d.tick(DriverInputs(frame=[], wall=None))                               # the same signal is not acted on twice
    assert ChirpMood.HIT not in payloads(t, EffectKind.CHIRP)


def test_the_imu_contact_signal_is_ignored_when_switched_off_or_old_or_outside_exploring(monkeypatch):
    d, c = _explorer(monkeypatch)
    monkeypatch.setenv("G2_IMU_CONTACT", "0")
    d.note_contact({})
    assert ChirpMood.HIT not in payloads(d.tick(DriverInputs(frame=[], wall=None)), EffectKind.CHIRP)
    monkeypatch.delenv("G2_IMU_CONTACT")
    d._contact_t -= 10.0                                                        # the walk has long ended: too old
    assert ChirpMood.HIT not in payloads(d.tick(DriverInputs(frame=[], wall=None)), EffectKind.CHIRP)
