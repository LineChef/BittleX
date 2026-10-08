# The next 20M run: plan and pick-up notes (written 2026-10-08, about noon)

**The new 20M does not start until the user says so** (user, 2026-10-08, 12:00 PM: "don't start the 20m training yet. I'll tell you when I'm ready to start"). Everything below is prepared and parked.

## Why a new run

The 20M that finished at 11:50 AM on 2026-10-08 (`v3_20m`) was launched as a fresh run on the flat stage by mistake: surface steps, snag obstacles and ledges were off for it (decisions log, 2026-10-08), its fault category was inert, and it used the old (world 1) payload. Beyond that, the session found and fixed a floor bug in the staged course, added the passability audit, and settled the standing rule that difficulty never ramps above what a capable policy can pass ([`passability-audit.md`](passability-audit.md)). The user decided to test the finished 20M on G2 and, in parallel, train a new 20M with the same recipe plus all of that.

## What the new run contains (all already in code; `g2_profile.env_for_job` is the single definition)

| Item | Setting | Where |
|---|---|---|
| Recipe | K3 = the `mirror` lever only (the command-drift levers are out, user decision 2026-10-07) | `trained/v3_results.json` -> `v3_k3.levers` |
| New payload ("world 2") | `G2E_PAYLOAD_LAYOUT=spine`: spine-sized block, camera and speaker as tall as the block (front weight share 46.7%) | `g2_profile.WORLD2_CALIBRATION`; the marker `trained/v3_world2` is already on (created 11:59 AM), so every new run gets it |
| Course hazards | snag obstacles 20% and ledges 20% on top of terrain and slope; each starts from an empty floor and ramps with its level. **The surface step stays OFF** (user, 2026-10-08: "don't re-enable surface step"; it is the only carpet-like physics: a hard floor that turns into a soft, high-friction slab with a 12 mm step). Carpet, soft-carpet and rug floors are off too. Its floor bug is fixed and its benchmark cells T4.1 and T4.2 still measure it; one line in `FULL_COURSE` turns it on later | `g2_profile.FULL_COURSE`, added to a new fresh final by `env_for_job` |
| Level ceiling | 1.25 (RECIPE) | `G2E_LEVEL_MAX` |
| Hard levels | x1.10 | `FINAL_EXTRA` |
| Top-threshold caps | NOT SET YET: set them from the capability test (below) before launch | `G2E_CAP_SIDEHILL_DEG`, `G2E_CAP_UPHILL_DEG`, `G2E_CAP_DOWNHILL_DEG`, `G2E_CAP_LEDGE_M` in `g2_profile.RECIPE` |
| Episode recording | about 1 episode in 50 is saved so it can be watched exactly: `python watch_training.py <tag>` | `G2E_RECORD_EVERY=50` |
| Real-data calibration | the approved snapshot, if any. Snapshot 0002 (the only candidate) changes nothing: its one value, `G2E_IMU_HOLD_STEPS` 16, equals the profile's, and `G2E_CMD_PATH_EXTRA_MS_MAX` was rejected by the user | `~/g2_data/calibration/` |

The faults lever is not part of K3, so the fault category stays inert in this run too. If the user wants faults trained, that is a separate decision (`NOT_IN_K3` in `phase_v3.py`).

## Before launch (in this order)

1. **Capability test (Part B) finishes.** It was started at 12:00 PM: `rl_training/opencat-gym/trained/passability_capability.log` and `trained/passability_capability.json` (log shows the table when done). It scores V2.1, K3 and the finished 20M on side-hills, climbs, descents and ledges at rising magnitudes (20 episodes per cell; success = stayed up and covered at least half the commanded distance). Re-run if needed: `cd rl_training/opencat-gym && ../../.venv/bin/python passability_audit.py capability --episodes 20 --jobs 8` (Mac idle).
2. **Set the caps** in `g2_profile.RECIPE` from `largest_passable` in that JSON (the largest magnitude the best policy passes at least half the time): side-hill roll, climb, descent in degrees; the ledge face (block height plus the ground falling away on a descent) in metres. Run `test_difficulty_caps.py`, `test_watch_sync.py`, `test_surface_transition_junction.py`, `test_episode_replay.py` (RL venv, from `rl_training/opencat-gym`). Re-run the geometry audit (`passability_audit.py geometry`) to confirm no episode exceeds a cap. Note the numbers in [`passability-audit.md`](passability-audit.md).
3. **Smoke test of the new environment (a dry run, not the 20M):** about 100k steps with the final environment to confirm it trains, the levels log, the recorder writes episodes and nothing crashes (`run_pipeline.launch` with a throwaway tag and `steps="1e5"`, then delete the tag's files). The user asked for a "quick smoke test of the impact of the new training data" (the calibration snapshot): checked 2026-10-08, the environment is identical with or without snapshot 0002, so it has no impact. The real gate is the run's own 3M checkpoint (below).
4. **Add the job** to `rl_training/opencat-gym/trained/v3_queue.json` (copy the `v3_20m` job: `kind: final`, `stage: s6_full_strength`, `levers: K3`, `fresh: true`; new tag, e.g. `v3_20m_full`; do NOT add the tag to `HISTORICAL_FLAT_FINALS`) followed by a `report` job with `report_of` = the new tag. The queue runner exited at 11:59 AM ("QUEUE COMPLETE"); it and its watchdog (`tools/v3_watchdog.sh`) must be started again. Rules that stay: never `pkill -f`, never put `train.py --tag` text in a command line, restart the runner only by exact pid.
5. **Ask the user for the go**, give a timing estimate with a projected completion clock time (12-hour Eastern): the last 20M took about 8.5 hours (3:17 AM to 11:50 AM at roughly 43k steps a minute) plus about 30 minutes of scoring. Start only on the go; open TensorBoard; arm a watcher (Monitor) on the log.

## While it runs

- The run's own gait checks at 3M, 5M and 10M against the K3 envelope (`trained/v3_score_v3_k3_envelope.json`) are the smoke test of the new course and payload: flat-ground falls must stay 0 and the run must be learning (levels rising). If the 3M check fails, find the term spoiling it before continuing (user rule, 2026-10-07).
- Watch it as it trains: `./watch_v3.sh <tag>` (the run's own environment and current levels, actions sampled like training) or `python watch_training.py <tag>` (the recorded episodes, exact).
- The calibration builder's harm check for snapshot 0002 waits for an idle Mac; `g2bg` (the Mac background loop) will start it as soon as nothing trains, so it will run before the launch if the Mac is idle. It changes nothing; it can be skipped.

## After it finishes

Report (V2.1, the first 20M, K3 and the new run, with the difficulty ladder), the parity bar (flat falls 0, speed at least 80% of V2.1's about 0.090 m/s, decision-cell falls no worse than V2.1 + 0.10), then `tools/g2_promote_policy.sh <tag>_ppo <Name>` and a G2 test with the hold on, tape-measured, after asking which floor G2 is on.

## The finished 20M on G2 (in progress at 12:02 PM)

`tools/g2_promote_policy.sh v3_20m_ppo Release_CandidateV3` was started: it exports the ONNX with its sidecar, points `DEFAULT_POLICY` at `Release_CandidateV3_ppo.onnx`, runs the test suite, commits and pushes, then waits in the background (up to 24 h) for the Pi and deploys when it is online (log `~/g2_logs/promote_deploy.out`; the deploy restarts `g2-voice` for about 30 s). Check `git log` for the "Promote Release_CandidateV3" commit. Rollback: set `DEFAULT_POLICY` back to `Release_CandidateV2.1_ppo.onnx` and run `tools/g2_deploy_when_online.sh --once`.
Its results against V2.1 (benchmark v5, 40 episodes per cell): flat falls 0; calm walk speed 0.084-0.086 vs 0.088-0.089; mirror gap 0.040 vs 0.174; fewer falls in nearly every decision cell (uphill 12 deg 0.00 vs 0.93, cross-slope 10 deg 0.10 vs 0.65, constant yaw push 0.00 vs 0.45, 40 s run 0.31 vs 0.56); not better on the 25 mm ledge (0.25, same as V2.1), the 60 s endurance run (0.62 vs 0.75) and the brutal gauntlet (0.97 vs 0.88). Its ledge, step and snag cells test generalization (it never trained on them). Report page: `rl_training/opencat-gym/trained/v3_report_v3_20m/post20m_report.html` (not yet published as an Artifact page).
Test it on G2 per [`../STATUS.md`](../STATUS.md): the front-foot hold stays on, controlled runs only, ask which floor G2 is on and set it (`g2floor tile` or by voice: "the floor is tile" / "this is a tile floor"; the voice command needs the next deploy to the Pi).

## Other state to remember

- The Pi was powered off for a recharge at about 9:50 AM; the voice-service fixes made after that (the floor voice command) are not on it yet.
- Open exploration problems and the voice-service fixes are in [`../plan-detail/handoff-2026-10-08.md`](../plan-detail/handoff-2026-10-08.md).
- All of 2026-10-08 is `unknown` in `~/g2_data/floor_overrides.json` (the morning walks were not all on tile) until the user says which time ranges were which floor.
- The Mac background loop (`g2bg`) re-curates the exploration pictures and runs the calibration step every 30 minutes; it ends at a Mac restart (`g2bg start`).
- Standing rules: [`passability-audit.md`](passability-audit.md) (difficulty never above capability), what you watch is what trains (`env_for_job`), ask the floor before runs, never deploy while the user is testing, wait for the user's go before any 20M.
