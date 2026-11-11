# Curriculum vs the old fixed ramp (2026-10-06, 600k-step smoke runs)

Two fresh runs on the V3 recipe (calibrated profile, case payload, all V3 hazards), identical except the difficulty scheme:
**curriculum** = per-category adaptive levels driven by a deterministic probe every 98k steps (`train.py` Curriculum, quick pace: +0.10 per good probe);
**fixed ramp** = the old scheme (one time ramp to full difficulty by 1M steps, `G2E_ADAPTIVE_LEVEL=0 G2E_CATEGORY_LEVELS=0 G2E_LEVEL_EXTERNAL=0 G2E_SCALE_ALL_HAZARDS=0`).
Checkpoints at 200k / 400k / 600k scored with `benchmark_v4.py` ("core" cells, 20 episodes, full difficulty, seed 1000). Single runs: the per-cell fall rates carry about +-15 points of noise.

- **T1.1 calm**: cur 200k: 0%; cur 400k: 0%; cur 600k: 0%; fix 200k: 0%; fix 400k: 0%; fix 600k: 0%
- **N1 12.5 s calm**: cur 200k: 0%; cur 400k: 0%; cur 600k: 0%; fix 200k: 0%; fix 400k: 5%; fix 600k: 10%
- **N3 stuck FL servo**: cur 200k: 0%; cur 400k: 0%; cur 600k: 0%; fix 200k: 0%; fix 400k: 20%; fix 600k: 10%
- **N5 yaw push**: cur 200k: 0%; cur 400k: 25%; cur 600k: 0%; fix 200k: 0%; fix 400k: 5%; fix 600k: 10%
- **T2.2 uphill 12 deg**: cur 200k: 35%; cur 400k: 40%; cur 600k: 15%; fix 200k: 50%; fix 400k: 95%; fix 600k: 80%
- **T3.2 cross-slope 10 deg**: cur 200k: 35%; cur 400k: 80%; cur 600k: 70%; fix 200k: 15%; fix 400k: 95%; fix 600k: 95%
- **T5.2 ledge 25 mm**: cur 200k: 35%; cur 400k: 25%; cur 600k: 30%; fix 200k: 35%; fix 400k: 40%; fix 600k: 40%
- **T7.2 snag**: cur 200k: 0%; cur 400k: 5%; cur 600k: 0%; fix 200k: 0%; fix 400k: 10%; fix 600k: 5%
- **T8.1 brutal shoves**: cur 200k: 85%; cur 400k: 75%; cur 600k: 85%; fix 200k: 85%; fix 400k: 90%; fix 600k: 75%
- **T9.1 overheat + uphill**: cur 200k: 30%; cur 400k: 55%; cur 600k: 30%; fix 200k: 70%; fix 400k: 100%; fix 600k: 95%
- **T10.2 slick floor**: cur 200k: 0%; cur 400k: 0%; cur 600k: 0%; fix 200k: 0%; fix 400k: 0%; fix 600k: 0%
- **mean of 11**: cur 200k: **20%**; cur 400k: **28%**; cur 600k: **21%**; fix 200k: **23%**; fix 400k: **42%**; fix 600k: **38%**

Calm walk (N1) roll std / L-R asymmetry at 600k: curriculum 3.3 deg / 6.0 deg, fixed ramp 7.0 deg / 9.4 deg. Calm speed: curriculum 0.056-0.059 m/s at 400k-600k vs fixed 0.060-0.071 (up to ~14% slower).
The fixed ramp gets worse as its difficulty reaches full strength; the curriculum holds level. Raw per-cell results: `curriculum_<step>.json`, `fixed_ramp_<step>.json`.
