"""Environment exports for watch_v3.sh: `python watch_env.py calm|course` prints `export K=V; ...` for the shell to eval.

calm   = the scoring world (a flat, calm floor: what the benchmark cells start from)
course = the scoring world plus the course the 20M trains on: surface steps, snag obstacles and ledges, hard levels x1.10, hazards pinned at difficulty level 1.0
         (the 20M's levels at 19M steps: terrain 1.00, ledge 1.00, slope 0.70, fault 1.00)
"""
import sys

import g2_profile as G

env = dict(G.scoring_env("mirror"))
if (sys.argv[1] if len(sys.argv) > 1 else "course") == "course":
    stage = G.stage_extra("s6_full_strength", ("mirror",))
    env.update({k: v for k, v in stage.items() if k.startswith(("G2E_SURFACE_", "G2E_SNAG_", "G2E_LEDGE_", "G2E_HARD_SCALE"))})
    env.update({"G2E_ADAPTIVE_LEVEL": "1", "G2E_CATEGORY_LEVELS": "1", "G2E_SCALE_ALL_HAZARDS": "1", "G2E_LEVEL_FIXED": "1.0"})
print("; ".join(f"export {k}={v}" for k, v in env.items()))
