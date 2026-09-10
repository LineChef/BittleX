import random

from pi_pipeline.behavior import (
    BehaviorDriver, DriverInputs, EffectKind, Posture,
    SleepModeConfig, SleepState,
)
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


# ---------------------------------------------- mood: unknown recency = NEUTRAL
def test_no_recency_data_stays_neutral():
    m, _ = _mood(lonely_after_s=2700)
    assert m.update(last_interaction_s=None) is Mood.NEUTRAL   # not LONELY
    assert m.phrasing_hint() == ""
    assert m.idle_bias().sit_mult == 1.0


# --------------------------------------------- driver: mood scales idle timing
def test_lonely_mood_makes_the_driver_settle_sooner():
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9,
                                      idle_sit_secs=10, idle_rest_secs=200),
                       clock=c, rng=random.Random(0),
                       mood_cfg=MoodConfig(lonely_after_s=1800))
    # LONELY -> sit_mult 0.6 -> sit_after ~6s instead of 10
    c.adv(7.0)
    tick = d.tick(DriverInputs(last_interaction_s=3600))
    assert tick.posture is Posture.SIT
    assert tick.mood is Mood.LONELY and tick.seek_attention


def test_neutral_mood_keeps_base_idle_timing():
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9,
                                      idle_sit_secs=10, idle_rest_secs=200),
                       clock=c, rng=random.Random(0))
    c.adv(7.0)
    tick = d.tick(DriverInputs(last_interaction_s=None))
    assert tick.posture is Posture.ACTIVE and tick.mood is Mood.NEUTRAL


# --------------------------------------------------- driver: emotive chirps
def test_say_hi_also_chirps_a_greeting():
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=c, rng=random.Random(0))
    c.adv(0.5)
    tick = d.tick(DriverInputs(say_hi=True))
    chirps = [e.payload for e in tick.effects if e.kind is EffectKind.CHIRP]
    assert ChirpMood.GREETING in chirps


def test_pickup_chirps_alert_once_rate_limited():
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=c, rng=random.Random(0))
    c.adv(0.5)
    t1 = d.tick(DriverInputs(picked_up=True, held=True))
    assert any(e.kind is EffectKind.CHIRP and e.payload is ChirpMood.ALERT
               for e in t1.effects)
    c.adv(0.3)                                   # inside the chirp cooldown
    t2 = d.tick(DriverInputs(loud_sound=True))
    assert not any(e.kind is EffectKind.CHIRP for e in t2.effects)


def test_chirps_can_be_disabled():
    c = Clk()
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9),
                       clock=c, rng=random.Random(0), chirps=False)
    c.adv(0.5)
    tick = d.tick(DriverInputs(say_hi=True))
    assert not any(e.kind is EffectKind.CHIRP for e in tick.effects)


# --------------------------------------------------- driver: deep-idle sleep
def _run(d, c, secs, dt=2.0, **inputs):
    """Tick the driver for `secs`, returning every effect it emitted."""
    seen = []
    for _ in range(int(secs / dt)):
        c.adv(dt)
        seen += d.tick(DriverInputs(**inputs)).effects
    return seen


def _sleepy_driver(**sleep_kw):
    c = Clk()
    cfg = dict(sleep_after_resting_s=30.0, settle_timeout_s=2.0)
    cfg.update(sleep_kw)
    d = BehaviorDriver(BehaviorParams(idle_secs_before_explore=1e9,
                                      idle_sit_secs=5, idle_rest_secs=10),
                       clock=c, rng=random.Random(0),
                       sleep_cfg=SleepModeConfig(**cfg))
    return d, c


def test_driver_enters_sleep_after_long_rest():
    d, c = _sleepy_driver()
    seen = _run(d, c, 90.0)                     # quiet: descend, rest, then sleep
    payloads = {(e.kind, e.payload) for e in seen}
    assert (EffectKind.SKILL, "kzz") in payloads
    assert (EffectKind.POWER, "headless") in payloads
    assert (EffectKind.CAPTURE, ("off", None)) in payloads
    assert any(e.kind is EffectKind.CHIRP and e.payload is ChirpMood.SLEEPY
               for e in seen)
    assert d.tick(DriverInputs()).sleep_state in (SleepState.DOZING, SleepState.ASLEEP)


def test_driver_wakes_on_wake_word_and_runs_the_rouse():
    d, c = _sleepy_driver(min_sleep_s=1.0)
    _run(d, c, 90.0)                            # -> ASLEEP
    assert d.tick(DriverInputs()).sleep_state is SleepState.ASLEEP
    c.adv(5.0)
    tick = d.tick(DriverInputs(wake_word=True))
    payloads = {(e.kind, e.payload) for e in tick.effects}
    assert (EffectKind.POWER, "interactive") in payloads
    assert (EffectKind.CAPTURE, ("on", None)) in payloads
    # and the rouse choreography starts this same tick
    assert any(e.kind is EffectKind.HEAD for e in tick.effects)


def test_told_sleep_overrides_person_present():
    d, c = _sleepy_driver(sleep_after_resting_s=1e9)  # never auto-sleeps
    _run(d, c, 60.0)                                  # just lie down
    c.adv(2.0)
    tick = d.tick(DriverInputs(told_sleep=True, person_present=True))
    assert any(e.kind is EffectKind.SKILL and e.payload == "kzz" for e in tick.effects)
