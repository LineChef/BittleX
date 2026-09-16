from pi_pipeline.personality import gir as gir_module
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


class _FakeSettings:
    def __init__(self, traits="curiosity=0.8", character="", level=0.4):
        self.traits_spec = traits
        self.character_spec = character
        self.character_level = level


def test_character_mode_is_off_by_default():
    per = Personality.from_settings(_FakeSettings())
    assert not any(t.name == "gir" for t in per.traits)


def test_g2_character_turns_gir_on_at_default_level():
    per = Personality.from_settings(_FakeSettings(character="gir"))
    g = [t for t in per.traits if t.name == "gir"]
    assert g and abs(g[0].level - 0.4) < 1e-9
    # and curiosity is still there -- character composes, doesn't replace
    assert any(t.name == "curiosity" for t in per.traits)


def test_character_level_is_configurable():
    per = Personality.from_settings(_FakeSettings(character="gir", level=0.75))
    g = [t for t in per.traits if t.name == "gir"][0]
    assert abs(g.level - 0.75) < 1e-9


def test_explicit_g2_traits_entry_wins_over_g2_character():
    per = Personality.from_settings(
        _FakeSettings(traits="gir=0.95", character="gir", level=0.4))
    g = [t for t in per.traits if t.name == "gir"][0]
    assert abs(g.level - 0.95) < 1e-9


def test_cues():
    assert "chirp_happy" in Gir(0.6).cues("greet")
    assert "excited_hop" in Gir(0.6).cues("greet")
    assert Gir(0.6).cues("greet").count("excited_hop") == 1
    assert Gir(0.3).cues("greet") == ["chirp_happy"]      # no hop at low level
    assert Gir(0.05).cues("greet") == []


# --------------------------------------------------- voice-facing 1-5 levels
def test_levels_is_five_not_ten():
    assert gir_module.LEVELS == 5


def test_level_to_intensity_spans_the_on_range():
    assert gir_module.level_to_intensity(1) == gir_module._LEVEL_LO
    assert gir_module.level_to_intensity(5) == gir_module._LEVEL_HI
    # every level is meaningfully "on" -- none dip below the off threshold
    for n in range(1, 6):
        assert Gir(gir_module.level_to_intensity(n)).prompt_fragment() is not None


def test_nearest_level_round_trips():
    for n in range(1, 6):
        assert gir_module.nearest_level(gir_module.level_to_intensity(n)) == n


def test_describe_level_matches_the_real_tiers():
    # levels 1-2 -> light quirk, 3-4 -> core character, 5 -> full chaos
    assert "light quirk" in gir_module.describe_level(1)
    assert "light quirk" in gir_module.describe_level(2)
    assert "clearly a character" in gir_module.describe_level(3)
    assert "clearly a character" in gir_module.describe_level(4)
    assert "full chaos" in gir_module.describe_level(5)
