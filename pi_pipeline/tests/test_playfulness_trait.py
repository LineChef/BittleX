from pi_pipeline.personality.playfulness import Playfulness
from pi_pipeline.personality.personality import Personality
from pi_pipeline.personality.traits import BehaviorParams, REGISTRY


def test_registered():
    assert REGISTRY.get("playfulness") is Playfulness


def test_below_threshold_is_inert():
    assert Playfulness(0.1).prompt_fragment() is None
    p = BehaviorParams()
    Playfulness(0.1).bias(p)
    assert p == BehaviorParams()                      # untouched
    assert Playfulness(0.1).cues("greet") == []


def test_low_level_is_a_light_streak():
    f = Playfulness(0.2).prompt_fragment()
    assert f is not None and "streak" in f.lower()
    # a nudge, not a shove
    p = BehaviorParams()
    Playfulness(0.2).bias(p)
    assert BehaviorParams().vocalize_prob < p.vocalize_prob < 0.30
    assert p.approach_novelty is False                # only flips at >= 0.5


def test_intensity_scales_the_fragment():
    assert len(Playfulness(0.95).prompt_fragment()) > len(Playfulness(0.2).prompt_fragment())
    assert "still answer" in Playfulness(0.95).prompt_fragment().lower()


def test_bias_pulls_against_curiosity_on_dwell_time():
    from pi_pipeline.personality.curiosity import Curiosity
    base = BehaviorParams().investigate_secs
    pc = BehaviorParams(); Curiosity(0.8).bias(pc)
    pp = BehaviorParams(); Playfulness(0.8).bias(pp)
    assert pc.investigate_secs > base > pp.investigate_secs   # curiosity lingers, play flits


def test_bias_touches_expression_and_explore_not_caution():
    p = BehaviorParams()
    Playfulness(0.8).bias(p)
    assert p.vocalize_prob > BehaviorParams().vocalize_prob
    assert p.fidget_prob > BehaviorParams().fidget_prob
    assert p.wander_turn_bias > BehaviorParams().wander_turn_bias
    assert p.idle_secs_before_explore < BehaviorParams().idle_secs_before_explore
    assert p.approach_novelty is True
    assert p.caution == BehaviorParams().caution      # deliberately untouched


def test_cues():
    assert "play_bow" in Playfulness(0.6).cues("greet")
    assert "excited_hop" in Playfulness(0.6).cues("greet")
    assert Playfulness(0.3).cues("greet") == ["play_bow", "chirp_happy"]   # no hop at low
    assert Playfulness(0.6).cues("recognize") == ["excited_hop", "wave"]
    assert Playfulness(0.3).cues("recognize") == ["wave"]
    assert Playfulness(0.3).cues("novelty") == ["sit_shift"]
    assert Playfulness(0.05).cues("greet") == []


def test_composes_and_clamps_with_curiosity():
    from pi_pipeline.personality.curiosity import Curiosity  # noqa: F401
    per = Personality.from_spec("curiosity=0.9, playfulness=0.9")
    prompt = per.system_prompt("BASE.")
    assert "curious" in prompt.lower() and "playful" in prompt.lower()
    p = per.behavior_params()                          # both bias, then clamp()
    assert 0.0 <= p.vocalize_prob <= 1.0
    assert p.investigate_secs >= 0.5                   # _MIN_SECS floor held
    assert p.idle_secs_before_explore >= 5.0
