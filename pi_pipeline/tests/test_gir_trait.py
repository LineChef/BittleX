from pi_pipeline.personality.gir import Gir
from pi_pipeline.personality.personality import Personality
from pi_pipeline.personality.traits import BehaviorParams, REGISTRY


def test_registered():
    assert REGISTRY.get("gir") is Gir


def test_below_threshold_is_silent():
    assert Gir(0.1).prompt_fragment() is None
    Gir(0.1).bias(BehaviorParams())          # no-op, no raise


def test_intensity_scales_the_fragment():
    low = Gir(0.3).prompt_fragment()
    mid = Gir(0.6).prompt_fragment()
    high = Gir(0.95).prompt_fragment()
    assert "subtle" in low.lower()
    assert len(high) > len(low)
    # every level keeps the task guard
    for f in (low, mid, high):
        assert "still" in f.lower() and ("help" in f.lower() or "task" in f.lower())
    # manner-only guardrail present in the fuller blocks
    assert "never quote" in mid.lower()


def test_bias_only_touches_expression_knobs():
    p = BehaviorParams()
    base_explore = p.idle_secs_before_explore
    Gir(0.8).bias(p)
    assert p.vocalize_prob > BehaviorParams().vocalize_prob
    assert p.fidget_prob > BehaviorParams().fidget_prob
    assert p.idle_secs_before_explore == base_explore   # not a curiosity-style trait


def test_composes_in_a_personality_system_prompt():
    per = Personality.from_spec("gir=0.6")
    out = per.system_prompt("BASE.")
    assert out.startswith("BASE.")
    assert "sidekick" in out.lower()


def test_cues():
    assert "chirp_happy" in Gir(0.6).cues("greet")
    assert "excited_hop" in Gir(0.6).cues("greet")
    assert Gir(0.6).cues("greet").count("excited_hop") == 1
    assert Gir(0.3).cues("greet") == ["chirp_happy"]      # no hop at low level
    assert Gir(0.05).cues("greet") == []
