# Phase 1 calibration sweeps (2026-10-06, fast pass)

V2.1 on `benchmark_v4.py` cell N1 (12.5 s calm flat walk, forced 0.10 m/s command), varying the sim's servo / contact settings with `--env G2E_...=` overrides.
`cal1_*`: 20 episodes, `cal2_*`: 30 episodes, seed 1000. Targets: the 14 post-servo-swap real walks (`real-walk-data/2026-10-06b/`): roll std 5.14, pitch std 2.41,
speed ~0.120 m/s, heading +36 +- 25 deg right (negative here), 0 falls.

| File | Settings | Falls | Speed | Heading | Roll | Pitch |
|---|---|---|---|---|---|---|
| `cal2_r200_mf15` (**chosen**) | servo limit 200, motor force 0.15 | 0% | 0.090 | -3.8 | 4.59 | 2.57 |
| `cal2_r225_mf15` | 225, 0.15 | 0% | 0.088 | -9.9 | 5.32 | 3.02 |
| `cal2_r225_mf18` | 225, 0.18 | 0% | 0.089 | -12.8 | 5.03 | 3.10 |
| `cal2_r200_mf18` | 200, 0.18 | 3% | 0.090 | -7.9 | 4.90 | 2.97 |
| `cal2_r200_mf12` | 200, 0.12 | 7% | 0.082 | -0.2 | 6.23 | 2.86 |
| `cal2_r200_mf15_gf08` / `_gf12` | 200, 0.15, ground friction 0.8 / 1.2 | 0% | 0.089 | -5.3 / -0.7 | 4.60 / 4.58 | 2.64 / 2.53 |
| `cal1_r250_mf15` | 250, 0.15 | 0% | 0.087 | -8.7 | 5.56 | 3.05 |
| `cal1_r200`, `cal1_r300` | 200 / 300, default force 0.2 | 5% | 0.089 / 0.084 | -4.4 / -13.8 | 5.03 / 6.14 | 2.97 / 4.28 |
| `cal1_r250_gf13` / `_gf16` / `_ff15` | 250 + ground friction 1.3 / 1.6 / foot friction 1.5 | 10-15% | ~0.084 | -7 to -16 | 5.7-6.6 | 3.9-5.3 |
| `cal1_r250_mf30` | 250, force 0.3 | 15% | 0.084 | -13.2 | 6.48 | 4.77 |
| `cal1_r250_kp03` | 250, servo gain 0.3 | 100% | 0.095 | -27.9 | 18.5 | 6.87 |

Findings: the servo speed limit (137 -> 200) and a lower motor force (0.2 -> 0.15) move roll and pitch onto G2's; friction and gain changes do not help; the sim's speed
stays ~0.09 whatever is changed (G2 ~0.12), so the commanded speed is scaled on the Pi instead.
