"""G2's personality: a set of traits that bias how it talks, behaves, and reacts.

    from pi_pipeline.personality import Personality
    p = Personality.from_spec("curiosity=0.85")
    system = p.system_prompt(base_prompt)
    params = p.behavior_params()
"""
from .personality import Personality, parse_traits
from .traits import REGISTRY, BehaviorParams, Trait

__all__ = ["Personality", "parse_traits", "REGISTRY", "BehaviorParams", "Trait"]
