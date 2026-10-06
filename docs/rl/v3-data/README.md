# v3-data: raw results behind the 2026-10-06 drift investigation

Summarized in [`../real-walk-log.md`](../real-walk-log.md) "Why V2.1 drifts right (investigation, 2026-10-06)" and used by
[`../v3-retrain-plan.md`](../v3-retrain-plan.md). All `drift_probe.py` runs: `Release_CandidateV2.1`, T1.1 environment, 12.5 s
(1000-step) episodes, commanded 0.10 m/s, seed 1234, run from `rl_training/opencat-gym/` with `../../.venv/bin/python`. Heading is in
the sim's convention (+ = left).

| File | Command (env vars + args) | Episodes |
|---|---|---|
| `drift_probe_none.json` | `G2E_PAYLOAD_PROFILE=case drift_probe.py trained/Release_CandidateV2.1_ppo` | 24 |
| `drift_probe_yawflip.json` | same + `--lever yawflip` (policy sees its yaw negated) | 24 |
| `drift_probe_yawzero.json` | same + `--lever yawzero` (policy sees yaw 0) | 24 |
| `drift_probe_sp_base.json` | `G2E_PAYLOAD_PROFILE=case`, no lever | 8 |
| `drift_probe_sp_norate.json` | + `G2E_SERVO_RATE_LIMIT_DEG_S=0` | 8 |
| `drift_probe_sp_ideal.json` | + `G2E_CMD_PATH=` and `G2E_SERVO_RATE_LIMIT_DEG_S=0` | 8 |
| `drift_probe_sp_every1.json` | + `G2E_CMD_SEND_EVERY_N=1` | 8 |
| `drift_probe_sp_est.json` | old 377 g payload (`estimate`, the default) | 8 |
| `drift_probe_sp_short.json` | `case` + `G2E_EPISODE_LENGTH=250` (3.1 s episodes) | 8 |
| `replay_real_obs_2026-10-06.txt` | `replay_real_obs.py` over `real-walk-data/2026-10-06/*.csv` | 6 walks |
