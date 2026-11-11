# Phase 1 calibration sweeps (2026-10-06, fast pass)

V2.1 on `benchmark_v4.py` cell N1 (12.5 s calm flat walk, forced 0.10 m/s command), varying the sim's servo / contact settings with `--env G2E_...=` overrides.
`cal1_*`: 20 episodes, `cal2_*`: 30 episodes, seed 1000. Targets: the 14 post-servo-swap real walks (`real-walk-data/2026-10-06b/`): roll std 5.14, pitch std 2.41,
speed ~0.120 m/s, heading +36 +- 25 deg right (negative here), 0 falls.

- **`cal2_r200_mf15` (**chosen**)**: Settings: servo limit 200, motor force 0.15; Falls: 0%; Speed: 0.090; Heading: -3.8; Roll: 4.59; Pitch: 2.57
- **`cal2_r225_mf15`**: Settings: 225, 0.15; Falls: 0%; Speed: 0.088; Heading: -9.9; Roll: 5.32; Pitch: 3.02
- **`cal2_r225_mf18`**: Settings: 225, 0.18; Falls: 0%; Speed: 0.089; Heading: -12.8; Roll: 5.03; Pitch: 3.10
- **`cal2_r200_mf18`**: Settings: 200, 0.18; Falls: 3%; Speed: 0.090; Heading: -7.9; Roll: 4.90; Pitch: 2.97
- **`cal2_r200_mf12`**: Settings: 200, 0.12; Falls: 7%; Speed: 0.082; Heading: -0.2; Roll: 6.23; Pitch: 2.86
- **`cal2_r200_mf15_gf08` / `_gf12`**: Settings: 200, 0.15, ground friction 0.8 / 1.2; Falls: 0%; Speed: 0.089; Heading: -5.3 / -0.7; Roll: 4.60 / 4.58; Pitch: 2.64 / 2.53
- **`cal1_r250_mf15`**: Settings: 250, 0.15; Falls: 0%; Speed: 0.087; Heading: -8.7; Roll: 5.56; Pitch: 3.05
- **`cal1_r200`, `cal1_r300`**: Settings: 200 / 300, default force 0.2; Falls: 5%; Speed: 0.089 / 0.084; Heading: -4.4 / -13.8; Roll: 5.03 / 6.14; Pitch: 2.97 / 4.28
- **`cal1_r250_gf13` / `_gf16` / `_ff15`**: Settings: 250 + ground friction 1.3 / 1.6 / foot friction 1.5; Falls: 10-15%; Speed: ~0.084; Heading: -7 to -16; Roll: 5.7-6.6; Pitch: 3.9-5.3
- **`cal1_r250_mf30`**: Settings: 250, force 0.3; Falls: 15%; Speed: 0.084; Heading: -13.2; Roll: 6.48; Pitch: 4.77
- **`cal1_r250_kp03`**: Settings: 250, servo gain 0.3; Falls: 100%; Speed: 0.095; Heading: -27.9; Roll: 18.5; Pitch: 6.87

Findings: the servo speed limit (137 -> 200) and a lower motor force (0.2 -> 0.15) move roll and pitch onto G2's; friction and gain changes do not help; the sim's speed
stays ~0.09 whatever is changed (G2 ~0.12), so the commanded speed is scaled on the Pi instead.
