"""`Personality` -- a set of traits, and the three things the rest of the system
asks of it:

    personality.system_prompt(base)   -> base prompt + each trait's fragment
    personality.behavior_params()     -> neutral BehaviorParams, biased by each trait
    personality.cues(event)           -> the union of the traits' cues for an event

Construct it from the `G2_TRAITS` setting, a comma-separated `name=level` list:

    G2_TRAITS="curiosity=0.85, playfulness=0.4"

Unknown names are warned about and skipped, so a config written for a newer build
degrades gracefully on an older one.
"""
from __future__ import annotations

import logging

from .traits import REGISTRY, BehaviorParams, Trait

log = logging.getLogger("g2.personality")


def parse_traits(spec: str) -> dict[str, float]:
    """`"curiosity=0.8, playfulness=0.4"` -> `{"curiosity": 0.8, "playfulness": 0.4}`.
    Tolerant: blank -> {}, a bare name -> level 1.0, bad level -> skipped."""
    out: dict[str, float] = {}
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        name, _, raw = part.partition("=")
        name = name.strip().lower()
        if not name:
            continue
        if raw.strip() == "":
            out[name] = 1.0
            continue
        try:
            out[name] = max(0.0, min(1.0, float(raw)))
        except ValueError:
            log.warning("personality: bad level %r for trait %r -- skipped", raw, name)
    return out


class Personality:
    def __init__(self, traits: list[Trait]):
        self.traits = traits

    @classmethod
    def from_spec(cls, spec: str) -> "Personality":
        traits: list[Trait] = []
        for name, level in parse_traits(spec).items():
            trait_cls = REGISTRY.get(name)
            if trait_cls is None:
                log.warning("personality: unknown trait %r -- skipped "
                            "(known: %s)", name, ", ".join(sorted(REGISTRY)))
                continue
            traits.append(trait_cls(level))
        return cls(traits)

    @classmethod
    def from_settings(cls, settings, *, runtime_state: bool = True) -> "Personality":
        spec = getattr(settings, "traits_spec", "")
        # opt-in character mode folds in as a trait, unless G2_TRAITS already
        # names it explicitly. Precedence: runtime state file > G2_CHARACTER env.
        char = (getattr(settings, "character_spec", "") or "").strip().lower()
        lvl = getattr(settings, "character_level", 0.4)
        if runtime_state:
            from . import character_state
            rt_name, rt_lvl = character_state.load()
            if rt_name is not None:
                char, lvl = rt_name, (rt_lvl if rt_lvl is not None else lvl)
        if char and char not in parse_traits(spec):
            spec = f"{spec}, {char}={lvl}" if spec.strip() else f"{char}={lvl}"
        return cls.from_spec(spec)

    def with_character(self, name: str, level: float) -> "Personality":
        """A new Personality = these traits with `name` added / replaced at
        `level`. Used to toggle character mode at runtime."""
        name = name.lower()
        cls = REGISTRY.get(name)
        if cls is None:
            return Personality(list(self.traits))
        kept = [t for t in self.traits if t.name != name]
        return Personality(kept + [cls(max(0.0, min(1.0, float(level))))])

    def without_character(self, name: str) -> "Personality":
        name = name.lower()
        return Personality([t for t in self.traits if t.name != name])

    # --- the three asks ---

    def system_prompt(self, base: str) -> str:
        frags = [f for t in self.traits if (f := t.prompt_fragment())]
        if not frags:
            return base
        return base.rstrip() + "\n\n" + " ".join(frags)

    def behavior_params(self) -> BehaviorParams:
        p = BehaviorParams()
        for t in self.traits:
            t.bias(p)
        return p.clamp()

    def cues(self, event: str) -> list[str]:
        seen: list[str] = []
        for t in self.traits:
            for c in t.cues(event):
                if c not in seen:
                    seen.append(c)
        return seen

    # --- introspection ---

    def describe(self) -> str:
        if not self.traits:
            return "neutral (no traits)"
        return ", ".join(f"{t.name} {t.level:.2f}" for t in self.traits)

    def __repr__(self) -> str:  # pragma: no cover
        return f"Personality([{self.describe()}])"
