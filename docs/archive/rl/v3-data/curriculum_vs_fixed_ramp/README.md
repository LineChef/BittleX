# Curriculum vs the old fixed ramp (2026-10-06, 600k-step smoke runs)

Two fresh runs on the V3 recipe (calibrated profile, case payload, all V3 hazards), identical except the difficulty scheme:
**curriculum** = per-category adaptive levels driven by a deterministic probe every 98k steps (`train.py` Curriculum, quick pace: +0.10 per good probe);
**fixed ramp** = the old scheme (one time ramp to full difficulty by 1M steps, `G2E_ADAPTIVE_LEVEL=0 G2E_CATEGORY_LEVELS=0 G2E_LEVEL_EXTERNAL=0 G2E_SCALE_ALL_HAZARDS=0`).
Checkpoints at 200k / 400k / 600k scored with `benchmark_v4.py` ("core" cells, 20 episodes, full difficulty, seed 1000). Single runs: the per-cell fall rates carry about +-15 points of noise.

| Fall rate | cur 200k | cur 400k | cur 600k | fix 200k | fix 400k | fix 600k |
|---|---|---|---|---|---|---|
| T1.1 calm | 0% | 0% | 0% | 0% | 0% | 0% |
| N1 12.5 s calm | 0% | 0% | 0% | 0% | 5% | 10% |
| N3 stuck FL servo | 0% | 0% | 0% | 0% | 20% | 10% |
| N5 yaw push | 0% | 25% | 0% | 0% | 5% | 10% |
| T2.2 uphill 12 deg | 35% | 40% | 15% | 50% | 95% | 80% |
| T3.2 cross-slope 10 deg | 35% | 80% | 70% | 15% | 95% | 95% |
| T5.2 ledge 25 mm | 35% | 25% | 30% | 35% | 40% | 40% |
| T7.2 snag | 0% | 5% | 0% | 0% | 10% | 5% |
| T8.1 brutal shoves | 85% | 75% | 85% | 85% | 90% | 75% |
| T9.1 overheat + uphill | 30% | 55% | 30% | 70% | 100% | 95% |
| T10.2 slick floor | 0% | 0% | 0% | 0% | 0% | 0% |
| **mean of 11** | **20%** | **28%** | **21%** | **23%** | **42%** | **38%** |

Calm walk (N1) roll std / L-R asymmetry at 600k: curriculum 3.3 deg / 6.0 deg, fixed ramp 7.0 deg / 9.4 deg. Calm speed: curriculum 0.056-0.059 m/s at 400k-600k vs fixed 0.060-0.071 (up to ~14% slower).
The fixed ramp gets worse as its difficulty reaches full strength; the curriculum holds level. Raw per-cell results: `curriculum_<step>.json`, `fixed_ramp_<step>.json`.
