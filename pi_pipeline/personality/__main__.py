"""Show the personality that a `G2_TRAITS` spec resolves to.

    python -m pi_pipeline.personality                      # uses G2_TRAITS from env/.env
    python -m pi_pipeline.personality "curiosity=0.9"      # override
"""
from __future__ import annotations

import sys
from dataclasses import asdict

from ..config import settings
from . import Personality

spec = sys.argv[1] if len(sys.argv) > 1 else getattr(settings, "traits_spec", "")
p = Personality.from_spec(spec)

print(f"spec:   {spec or '(empty)'}")
print(f"traits: {p.describe()}\n")

print("--- system prompt ---")
print(p.system_prompt(settings.system_prompt))

print("\n--- behavior params (biased, clamped) ---")
for k, v in asdict(p.behavior_params()).items():
    if k.startswith("_"):
        continue
    print(f"  {k:26} {v}")

print("\n--- cues ---")
for ev in ("novelty", "explore_start", "greet"):
    print(f"  {ev:14} {p.cues(ev)}")
