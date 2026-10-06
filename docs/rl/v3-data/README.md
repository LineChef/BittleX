# v3-data: raw results behind the 2026-10-06 drift investigation

Summarized in [`../real-walk-log.md`](../real-walk-log.md) "Why V2.1 drifts right (investigation, 2026-10-06)" and used by
[`../v3-retrain-plan.md`](../v3-retrain-plan.md). All runs: `Release_CandidateV2.1`, the 422 g `case` payload, run from `rl_training/opencat-gym/`
with `../../.venv/bin/python`. Heading is in the sim's convention (+ = left, so a real right-hand drift is negative here).

## Fixed-command results (use these)
`benchmark_v4.py` forces the commanded speed (0.10 m/s) for the whole episode, like the real walks. N1 = the 12.5 s calm flat walk (20 episodes,
seed 1000) on the pre-calibration profile (`g2_profile.py`), varying one setting:

| File | Command | Result (fell / speed / heading / roll std) |
|---|---|---|
| `n1_sweep_base.json` | `benchmark_v4.py --policy trained/Release_CandidateV2.1_ppo --cells N1 --episodes 20` | 0% / 0.089 / +9.3 / 2.64 |
| `n1_sweep_rate90.json` | + `--env G2E_SERVO_RATE_LIMIT_DEG_S=90` | 0% / 0.067 / +7.3 / 2.26 |
| `n1_sweep_rate180.json` | `...=180` | 0% / 0.091 / +1.8 / 3.83 |
| `n1_sweep_rate250.json` | `...=250` (the firmware's own easing) | 10% / 0.086 / **-10.8** / **5.92** |
| `n1_sweep_rate400.json` | `...=400` | 10% / 0.081 / -15.8 / 6.68 |
| `n1_sweep_norate.json` | `...=0` (no limit) | 5% / 0.081 / -23.3 / 6.51 |
| `n1_sweep_ideal.json` | `...=0` and `--env G2E_CMD_PATH=` (no firmware model) | 35% / 0.083 / -27.9 / 8.30 |
| `n1_sweep_every1.json` | `--env G2E_CMD_SEND_EVERY_N=1` | 0% / 0.089 / +10.9 / 2.65 |
| `n1_sweep_oldpayload.json` | `--env G2E_PAYLOAD_PROFILE=estimate` (377 g) | 0% / 0.090 / +8.8 / 2.60 |
| `benchmark_v4_V2.1_precalibration.json` | `benchmark_v4.py --policy trained/Release_CandidateV2.1_ppo --jobs 8` (all 28 cells, 40 episodes, N2 12) | the V2.1 reference on the v4 ladder: mirror gap 0.172, N1 L-R asymmetry 7.1 deg (hip BR-BL), turn command tracking +7% / -2% |

Real G2 (six walks, 2026-10-06): roll std 5.7-6.2, pitch std 1.9-2.7, heading change about -142 (right), speed about 0.118 m/s (10-01, taped).
The servo-speed ceiling is the setting that moves the sim toward G2 (roll swing and the turn to the right).

## Superseded: `drift_probe_*.json` (random-command confound)
These were taken with `drift_probe.py` before 2026-10-06 (afternoon), which set the command once after reset instead of forcing it. The env then
redrew the command (including stand and backward) about 9 times per 1000 steps, so the **speeds are too low** (0.05 instead of 0.09 m/s) and the
"V2.1 slows down on long walks" reading is wrong (with a fixed command the slow-down over 12.5 s is about 0). Heading and the yaw-sign results
are unaffected (the commanded yaw is always 0). `drift_probe.py` now forces the command.

| File | Setting | Episodes |
|---|---|---|
| `drift_probe_none.json`, `drift_probe_yawflip.json`, `drift_probe_yawzero.json` | yaw seen normal / negated / zero (`--lever yawflip|yawzero`) | 24 each |
| `drift_probe_sp_base.json` ... `drift_probe_sp_short.json` | servo limit off / ideal path / send every tick / old payload / 250-step episodes | 8 each |
| `replay_real_obs_2026-10-06.txt` | `replay_real_obs.py` over `real-walk-data/2026-10-06/*.csv` | 6 walks |
