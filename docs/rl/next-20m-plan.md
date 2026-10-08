# The next 20M run: plan and pick-up notes (written 2026-10-08, about noon)

**The new 20M does not start until the user says so** (user, 2026-10-08, 12:00 PM: "don't start the 20m training yet. I'll tell you when I'm ready to start"). Everything below is prepared and parked.

## Why a new run

The 20M that finished at 11:50 AM on 2026-10-08 (`v3_20m`) was launched as a fresh run on the flat stage by mistake: surface steps, snag obstacles and ledges were off for it (decisions log, 2026-10-08), its fault category was inert, and it used the old (world 1) payload. Beyond that, the session found and fixed a floor bug in the staged course, added the passability audit, and settled the standing rule that difficulty never ramps above what a capable policy can pass ([`passability-audit.md`](passability-audit.md)). The user decided to test the finished 20M on G2 and, in parallel, train a new 20M with the same recipe plus all of that.

## What the new run contains (all already in code; `g2_profile.env_for_job` is the single definition)

| Item | Setting | Where |
|---|---|---|
| Recipe | K3 = the `mirror` lever only (the command-drift levers are out, user decision 2026-10-07) | `trained/v3_results.json` -> `v3_k3.levers` |
| New payload ("world 2") | `G2E_PAYLOAD_LAYOUT=spine`: spine-sized block, camera and speaker as tall as the block (front weight share 46.7%) | `g2_profile.WORLD2_CALIBRATION`; the marker `trained/v3_world2` is already on (created 11:59 AM), so every new run gets it |
| Course hazards | the share of training episodes each appears in, set by the user on 2026-10-08 and tuned by sampling the reset: **rubble 50%, box obstacles 30%, slopes of 5 deg or more 20%, rough floor 20%, snag obstacles 20%, ledges 20%**. Each starts from an empty floor and ramps with its level. **The surface step (a hard floor turning into a soft, high-friction carpet-like slab with a 12 mm step) is taken out of the course completely**: no stage, course or recipe switches it on; its generator stays in the environment only because benchmark cells T4.1 and T4.2 test it. Carpet, soft-carpet and rug floors are off too | `g2_profile.FULL_COURSE` (the per-episode chances) and `STAGES` (surface step removed), added to a new fresh final by `env_for_job` |
| Level ceiling | 1.25 (RECIPE) | `G2E_LEVEL_MAX` |
| Hard levels | x1.10 | `FINAL_EXTRA` |
| Top-threshold caps | **Built and tested (2026-10-08).** Provisional start values: side-hill 8 deg, climb 10 deg, descent 10 deg, ledge face 2.0 cm. They were set one step below the first proposal (10/12/12) because the report tool, run on the finished 20M's own log, showed its slope level stuck at 0.70 (side-hill about 10 deg, climb about 17 deg) with probe scores at or below 0.5. The ledge starts small and rises as the policy earns it (ceiling 3.7 cm, the training maximum: the user decides). Adjustable while the run trains and reviewed every 1M steps: "Caps: how they are chosen and monitored" below | `G2E_CAP_*` in `g2_profile.FULL_COURSE` (start values); `trained/<tag>_caps.json` (live values, created at launch); `CapsSync` in `train.py`; `caps_report.py` |
| Episode recording | about 1 episode in 50 is saved so it can be watched exactly: `python watch_training.py <tag>` | `G2E_RECORD_EVERY=50` |
| Real-data calibration | the approved snapshot, if any. Snapshot 0002 (the only candidate) changes nothing: its one value, `G2E_IMU_HOLD_STEPS` 16, equals the profile's, and `G2E_CMD_PATH_EXTRA_MS_MAX` was rejected by the user | `~/g2_data/calibration/` |

### How often each hazard appears (user targets, 2026-10-08; measured by sampling the training reset, 2000 episodes at mature levels)

| Challenge | Share of training episodes | Finished 20M for comparison |
|---|---|---|
| Rubble | 50% | 71% |
| Box obstacles | 30% | 32% |
| Slopes (ground tilted 5 deg or more) | 20% | 22% |
| Rough floor | 20% | 22% |
| Snag obstacles | 20% | 0% |
| Ledges (full-width block, up or down) | 20% | 0% |
| Surface step | 0% (removed) | 0% |

The settings that produce them: `G2E_RUBBLE_PROB` 0.575, `G2E_RANDOM_TERRAIN_PROB` 0.34 (boxes), `G2E_SLOPE_TARGET_PROB` 0.14 with `G2E_SLOPE_MAX_DEG` 10 (slopes), `G2E_ROUGH_TERRAIN_PROB` 0.25, `G2E_SNAG_OBSTACLE_PROB` 0.228, `G2E_LEDGE_PROB` 0.28. They are chances per episode; the measured shares are what the list above reports, after the episode mix (10% hazard-free anchors, focus and combo episodes). To re-check them: sample the reset with `g2_profile.env_for_job` for the new tag (see the hazard-mix method in the decisions log).

The faults lever is not part of K3, so the fault category stays inert in this run too. If the user wants faults trained, that is a separate decision (`NOT_IN_K3` in `phase_v3.py`).

## Caps: how they are chosen and monitored (built 2026-10-08)

**What the data says (capability test, Part B, 2026-10-08; policies: V2.1, K3 and the finished 20M; 20 episodes per cell; "success" = stayed up and covered half the commanded distance in 3 s, which is strict on slopes because every policy slows down there; the fall rate is the better sign of "impossible"):**

| Hazard | Best policy (the finished 20M) | Reading |
|---|---|---|
| Side-hill roll 4 / 6 / 8 / 10 / 12 / 15 deg | falls 15 / 5 / 25 / 40 / 65 / 70% | passable to about 8-10 deg; the course reaches 15 deg (19 deg at level 1.25) |
| Climb 8 / 12 / 16 / 20 / 24 deg | falls 5 / 15 / 15 / 50 / 70% (progress shrinks from 12 deg) | usable to about 12 deg; the course reaches 24 deg (30 at 1.25) |
| Descent 8 / 12 / 16 / 20 deg | falls 10 / 30 / 60 / 65% | usable to about 12 deg |
| Step-down (starts on the block, drops off) 1.5 / 2.5 / 3.5 cm | V2.1 and K3 pass 92-100% / about 50% / about 0%; the 20M passes 88% / 0% / 0% | none of them survives a drop of 3.5 cm or more; the course goes to 3.7 cm |
| Step-up (climbs onto the block) 1.5-6 cm | few falls, but nobody gets onto the block within 3 s (0-8% pass) | untested ability: none of these policies ever trained on ledges |

The ledge numbers measure policies that never trained on ledges, so they are a starting point, not a limit. The slope numbers are for policies that did train on slopes up to 24 deg and still fail above about 10 deg, which is much stronger evidence of a real limit.

**Review procedure (built; follow it while a run trains):**
1. *Caps live in a file the training reads while it runs:* `trained/<tag>_caps.json` (side-hill deg, climb deg, descent deg, ledge face m). A callback in `train.py` (`CapsSync`, like `RampSync`) checks the file at every rollout and pushes changes to every env (and the probe env) through `set_caps` / `apply_caps`; it creates the file with the starting values at launch and logs a `[caps]` line on each change. The viewer (`watch_trained.py`) follows the file too. Test: `test_caps_runtime.py` (lowering and removing a cap changes the very next episodes without a restart).
2. *The report tool* (`cd rl_training/opencat-gym && ../../.venv/bin/python caps_report.py <tag>`) reads the run's console log (`[level]` and `[probe]` lines: per-category level and probe score every 98k steps) and prints, per hazard: the current cap, the level, how long the level has sat at the cap, the recent probe scores, and a verdict: **cap too low** (the level reached the cap, probe score stays at or above 0.80 for several probes: raise the cap one step) or **cap too high** (the level keeps being demoted, probe score at or below 0.50 for several probes while the cap is above the level the policy reached: lower the cap, or hold it) or **on track**.
3. *Cadence:* `caps_report.py <tag> --watch` (arm it with the Monitor tool when the run starts) prints a "CAPS REVIEW DUE" line each time the run passes another 1M steps (about 25 minutes at 43k steps a minute); Claude reads the report, changes the caps file when a verdict is clear, notes it in the decisions log with the step count, and tells the user. The user can also change a cap at any time.
4. *Do not change a cap more than one step per review* (side-hill/climb/descent 2 deg, ledge 0.5 cm) so the effect is visible; a cap only ever moves inside the measured-impossible limits (never above 15 deg side-hill, 24 deg climb, 3.7 cm ledge, which is the course's own design range).
5. After the run: record the final caps and where each ended, as the starting point for the next run.

**Open question for the user:** the ledge ceiling (3.7 cm = the training maximum, or lower), and whether to confirm the provisional start values above. Real-data check of the tool: on the finished 20M's log it reports the side-hill and climb caps of 10/12 deg as "too high" (the level sat at 0.70 with probe scores at or below 0.5), the descent and ledge caps as on track; the new run starts one step lower.

## Before launch (in this order)

1. **Capability test (Part B) finishes.** It was started at 12:00 PM: `rl_training/opencat-gym/trained/passability_capability.log` and `trained/passability_capability.json` (log shows the table when done). It scores V2.1, K3 and the finished 20M on side-hills, climbs, descents and ledges at rising magnitudes (20 episodes per cell; success = stayed up and covered at least half the commanded distance). Re-run if needed: `cd rl_training/opencat-gym && ../../.venv/bin/python passability_audit.py capability --episodes 20 --jobs 8` (Mac idle).
2. **Confirm the caps.** The start values are already in `g2_profile.FULL_COURSE` (provisional, above); change them if the user wants other numbers (the largest magnitude the best policy passes at least half the time): side-hill roll, climb, descent in degrees; the ledge face (block height plus the ground falling away on a descent) in metres. Run `test_difficulty_caps.py`, `test_watch_sync.py`, `test_surface_transition_junction.py`, `test_episode_replay.py` (RL venv, from `rl_training/opencat-gym`). Re-run the geometry audit (`passability_audit.py geometry`) to confirm no episode exceeds a cap. Note the numbers in [`passability-audit.md`](passability-audit.md).
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
