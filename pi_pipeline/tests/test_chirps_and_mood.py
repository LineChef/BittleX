import random

from pi_pipeline.behavior import BehaviorDriver, DriverInputs, EffectKind
from pi_pipeline.behavior.chirps import (
    CHIRP, ChirpMood, Chirper, chirp_for, cue_chirp,
)
from pi_pipeline.personality.mood import Mood, MoodConfig, MoodModel
from pi_pipeline.personality.traits import BehaviorParams


# ---------------------------------------------------------------- chirps (B5)
def test_every_mood_has_a_playable_sequence():
    for m in ChirpMood:
        s = chirp_for(m)
        assert s.startswith("b") and len(CHIRP[m]) >= 1
        # opencat.beep format: "b<tone> <ms> <tone> <ms> ..."
        nums = s[1:].split()
        assert len(nums) == 2 * len(CHIRP[m])


def test_cue_chirp_maps_stages():
    assert cue_chirp("listening") == chirp_for(ChirpMood.ALERT)
    assert cue_chirp("thinking") == chirp_for(ChirpMood.QUESTION)
    assert cue_chirp("speaking") is None
    assert cue_chirp("idle") is None
    assert cue_chirp("bogus") is None


def test_chirper_rate_limits():
    t = [0.0]
    ch = Chirper(min_gap_s=2.0, clock=lambda: t[0])
    assert ch.maybe(ChirpMood.HAPPY) is not None
    t[0] = 1.0
    assert ch.maybe(ChirpMood.ALERT) is None          # too soon
    t[0] = 2.5
    assert ch.maybe(ChirpMood.ALERT) is not None


# ------------------------------------------------------------- mood (B6)
def _mood(**cfg):
    t = [0.0]
    return MoodModel(MoodConfig(**cfg), clock=lambda: t[0]), t


def test_long_silence_is_lonely():
    m, t = _mood(lonely_after_s=2700)
    assert m.update(last_interaction_s=3000) is Mood.LONELY
    assert "wistful" in m.phrasing_hint()
    b = m.idle_bias()
    assert b.seek_attention and b.sit_mult < 1.0      # rouses / descends sooner


def test_recent_chatter_is_content_or_playful():
    m, _ = _mood(content_within_s=1200, playful_exchanges=6)
    assert m.update(last_interaction_s=60, exchanges_recent=2) is Mood.CONTENT
    assert m.update(last_interaction_s=60, exchanges_recent=8) is Mood.PLAYFUL


def test_rebuff_makes_it_subdued_then_wears_off():
    m, t = _mood(subdued_s=480)
    m.note_rebuff(now=0.0)
    assert m.update(now=100.0, last_interaction_s=10) is Mood.SUBDUED
    assert m.idle_bias().rest_mult > 1.0              # holds still longer
    assert m.update(now=600.0, last_interaction_s=10) is Mood.CONTENT   # 8 min later


def test_neutral_when_quiet_but_not_long():
    m, _ = _mood(lonely_after_s=2700, content_within_s=1200)
    assert m.update(last_interaction_s=1800) is Mood.NEUTRAL
    assert m.phrasing_hint() == ""


# --------------------------------------------------- "say hi" driver hook
class Clk:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def adv(self, dt): self.t += dt


def test_say_hi_emits_a_greeting_skill():
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=c, rng=random.Random(0))
    c.adv(0.5)
    tick = d.tick(DriverInputs(say_hi=True))
    skills = [e.payload for e in tick.effects if e.kind is EffectKind.SKILL]
    assert skills and any(e.reason == "say hi" for e in tick.effects)


def test_say_hi_is_suppressed_during_enrollment(tmp_path):
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=c, rng=random.Random(0), capture_root=str(tmp_path))
    c.adv(0.5)
    d.tick(DriverInputs(meet_name="Sam"))            # enrollment owns the robot
    c.adv(0.5)
    tick = d.tick(DriverInputs(say_hi=True))
    assert not any(e.reason == "say hi" for e in tick.effects)
