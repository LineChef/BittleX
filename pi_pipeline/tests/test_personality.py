from pi_pipeline.personality import BehaviorParams, Personality, parse_traits
from pi_pipeline.personality.traits import REGISTRY

BASE = "You are G2."


def test_parse_traits_forms():
    assert parse_traits("") == {}
    assert parse_traits("curiosity=0.8") == {"curiosity": 0.8}
    assert parse_traits(" Curiosity = 0.5 , playfulness=0.2") == {
        "curiosity": 0.5, "playfulness": 0.2}
    assert parse_traits("curiosity") == {"curiosity": 1.0}          # bare name -> full
    assert parse_traits("curiosity=2") == {"curiosity": 1.0}        # clamped
    assert parse_traits("curiosity=oops") == {}                     # bad level dropped


def test_empty_personality_is_neutral():
    p = Personality.from_spec("")
    assert p.traits == []
    assert p.system_prompt(BASE) == BASE
    assert p.behavior_params() == BehaviorParams().clamp()
    assert p.cues("novelty") == []


def test_unknown_trait_skipped_not_fatal():
    p = Personality.from_spec("curiosity=0.5, nonsense=0.9")
    assert [t.name for t in p.traits] == ["curiosity"]


def test_curiosity_registered():
    assert "curiosity" in REGISTRY


def test_curiosity_prompt_scales_with_level():
    low = Personality.from_spec("curiosity=0.05").system_prompt(BASE)
    mid = Personality.from_spec("curiosity=0.4").system_prompt(BASE)
    high = Personality.from_spec("curiosity=0.9").system_prompt(BASE)
    assert low == BASE                              # below threshold -> nothing added
    assert "mildly curious" in mid
    assert "very curious" in high
    assert high.startswith(BASE)


def test_curiosity_biases_behavior_params():
    neutral = Personality.from_spec("").behavior_params()
    curious = Personality.from_spec("curiosity=0.9").behavior_params()
    assert curious.idle_secs_before_explore < neutral.idle_secs_before_explore
    assert curious.novelty_pull > neutral.novelty_pull
    assert curious.investigate_secs > neutral.investigate_secs
    assert curious.approach_novelty is True and neutral.approach_novelty is False


def test_behavior_params_stay_in_range():
    p = Personality.from_spec("curiosity=1.0").behavior_params()
    assert 0.0 <= p.novelty_pull <= 1.0
    assert 0.0 <= p.vocalize_prob <= 1.0
    assert p.idle_secs_before_explore >= 5.0        # floor enforced
    assert p.investigate_secs >= 0.5


def test_cues_deduped_union():
    p = Personality.from_spec("curiosity=0.9")
    assert p.cues("novelty") == ["head_tilt", "chirp_rising", "approach"]
    assert p.cues("explore_start") == ["check_around"]
    assert p.cues("nothing") == []


def test_low_curiosity_no_approach_cue():
    assert "approach" not in Personality.from_spec("curiosity=0.3").cues("novelty")
