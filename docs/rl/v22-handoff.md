# v2.2 hand-off: fixing G2's drift to the right (written 2026-10-06, 12:07 PM ET)

For a new session picking this up. Read this, then [`v22-log.md`](v22-log.md) (working log, round table, resume commands) and [`../STATUS.md`](../STATUS.md). Snapshot copies of the run's JSON and log
are in [`v22-data/`](v22-data/) (the live files are in `rl_training/opencat-gym/trained/`, which git ignores).

## 1. The goal and why
Make G2 walk straight with the learned gait on the real robot, and train a better gait on the real (heavier) robot. Real hard-floor V2.1 walks with the case mounted (six, 2026-10-06,
[`real-walk-log.md`](real-walk-log.md)): no falls, roll std 5.7-6.2 deg, pitch std 1.9-2.7, but a steady turn to the **right** of about +142 deg in 12.7 s (8-14 deg/s), same every run. G2 now weighs about
422 g (sim had ~377 g). The user's plan: fresh measurements, fix the sim to match, then a new 20M run ("v2.2"), promoted to the default gait if it passes.

## 2. State at 12:07 PM (all on the Mac, `rl_training/opencat-gym/`)
- `phase_v22.py` (the round runner) and the round-3 training (`v22_r3_control`, a 3M control run) are running. Round 3 was at 2.0M of 3M steps; expected done about 12:30 PM, scored about 12:40 PM.
- Rounds so far (`trained/v22_results.json`, copy in `v22-data/`): R1 `v22_r1_drift` and R2 `v22_r2_len` finished and are scored; the queue (`trained/v22_queue.json`) holds R1, R2, R3.
- Claude-session notifications came from a Monitor armed in the previous session; a new session must read `trained/phase_v22.log` or arm its own.
- Nothing is deployed from this campaign. The Pi runs V2.1 as the default gait (movement unlocked, voice service up). Pi/G2 state and defaults: STATUS.md and the memory note `project_g2_defaults_2026_10_06`.

## 3. Established facts
**Hardware / real robot**
- Weights: whole G2 422 g (measured); base about 301 g (assumed, 269 g URDF x 1.12); camera 15 g (front), speaker 20 g (very back), spine block 86 g (derived), mic on the lid (negligible). [`../hardware/specs.md`](../hardware/specs.md).
- **Front-left shoulder servo (servo 8) is faulty**: reproducibly sticks near 42 deg and will not go above it even when commanded 65; the stand angle (50) is therefore 8 deg low and its swing is clipped ([`real-walk-log.md`](real-walk-log.md), "Servo feedback tests"). The user will swap it at the hardware check-in (if they have a spare). Whether it causes the drift is NOT established (see below).
- The firmware step gait (`kvtF`) on the same leg walks straight (about 1 inch of drift left over 6 s); the user says most gaits look fine and only a few outliers show symptoms.
- Real V2.1 commanded joint means (six walks, deg): FL shoulder 47.2, FR shoulder 49.2, BR hip 52.9, BL hip 60.1 (rear hips differ by 7 deg), FL shoulder range 11..74 (the servo cannot follow the top of it).
- Voltage under load: a full pack (8.5 V rest) sags 0.3-0.45 V walking. G2 browned out walking at a resting 7.58 V (battery alarms were changed, see STATUS).
**Sim vs real**
- The policy observes heading (the orientation quaternion, yaw zeroed at the start of each walk; `IMU_RATE_ZERO` so no yaw rate) and the reward penalizes heading error (`FAC_HEADING` 5.0), but training episodes are only 250 steps (3.1 s) and nothing pushes it off course, so it was never trained to steer back.
- In the sim, V2.1 (T1.1-style calm environment, 422 g payload, 12.5 s, 24 episodes): 0 falls, heading error 9.7 deg, speed 0.051 m/s, roll std 3.3 (real 5.9). Under a constant yaw torque (up to 0.5, `G2E_DRIFT_TORQUE`): heading error 26.9 deg, 1/24 falls. **The sim does not reproduce the real 140-deg drift.**
- The heavier payload alone raises sim roll swing (3.1 -> ~5.5 with the harsher random hazards) and helps several decathlon cells when trained on (R1 cells: uphill, snag, rug 0% falls vs 20-25% for V2.1).

## 4. What has been tried (sim, V2.1 frozen unless noted; `drift_probe.py --lever`)
| Lever (one at a time, 12 episodes, harsher hazards on) | Result |
|---|---|
| servo zero offset FL shoulder -8 / -14 deg | heading abs 8 / 19 deg; falls 2 / 5 of 12 |
| shortened swing FL shoulder (scale 0.5 / 0.2) | heading mean -15 / -11 deg; falls 4 / 3 |
| motor force cut FL shoulder (0.4 / 0.15), FL knee 0.2 | abs 14 / 13 deg; knee cut: 10 of 12 fall |
| one foot at 30% friction (4 feet) | abs 12-17 deg |
| constant yaw torque (applied once per env step) 0.003-0.4 | little effect up to 0.4 (heading mean -10); 1.0 gives -43 deg, falls 2/12 |
| constant yaw torque on every physics substep, uniform +-T: 0.45 / 0.7 / 0.85 | abs 22 / 71 / 80 deg; falls 9 / 13 / 16 of 24 (first, too harsh probe) |
| FL shoulder capped at 42 / 46 / 38 deg (the real stuck servo) | heading mean -14 / -6 / +1 deg, abs 18 / 15 / 10, falls 6 / 5 / 5 of 12: **does not reproduce 140 deg** |
Rounds (fresh 3M-step runs, 422 g payload `G2E_PAYLOAD_PROFILE=case`):
| Round | Change | Result (corrected probe) |
|---|---|---|
| R1 `v22_r1_drift` | yaw torque up to 0.5 on 70% of episodes | calm 0/24 falls, heading 9.3 deg, **speed 0.018** (slow); under disturbance 2/24 falls, heading 34.5 deg. Cells: T2.2 0.0, T3.2 0.8, T5.2 0.2, T7.2 0.0, T8.1 0.8, T10.1 0.0, T10.2 0.05 |
| R2 `v22_r2_len` | training episodes 1000 steps (12.5 s) only | calm 1/24, heading 24.8, speed 0.044; under disturbance 8/24 falls, heading 62 deg. Cells: 0.05, 0.45, 0.25, 0.05, 1.0, 0.0, 0.0 |
| V2.1 (context, ~30M steps) | frozen | calm 0/24, 9.7 deg, 0.051; disturbance 1/24, 26.9 deg. Cells: 0.2, 0.3, 0.2, 0.2, 1.0, 0.2, 0.25 |
| R3 `v22_r3_control` | the 3M reference: payload only | **running; the reference for R1/R2** |
Lessons: (1) my first probe left random slopes/rubble on, so its "calm" falls were meaningless; fixed by using the decathlon `_apply({})` environment. (2) A 3M scratch policy is not comparable with V2.1; judge rounds against the 3M control.

## 5. Agreed rules (user instructions)
- Up to **six** 3M rounds (single levers first, round 6 = best drift fix + best yaw fix together); iterate between rounds; take as long as needed in the sweeping stage; change one lever at a time.
- **Hardware check-in:** after the best 3M round testing PAUSES before the 20M run and the user is notified; the user walks the best 3M policy on G2 (after swapping servo 8). Do not start the 20M run without their go.
- Final run: 20M, fresh (not a fine-tune), `G2E_HARD_SCALE=1.10` (the hardest training levels +10%: shoves, slope range, overheat cutback, obstacle/rubble heights; nominal walk unchanged), gates at 3M and 5M (stop on a regression).
- Benchmark report: score V2.1 and the new policy on the original ladder AND a ladder with the hardest rung of each category +10% (T2.2 12->13.2 deg, T3.2 10->11, T5.3 40->44 mm, T8.1 shoves 1.00->1.10, T9.1 cutback 0.60->0.66, T11.2); label harder-level results as not comparable with older runs. **`benchmark_decathlon.py --hard-scale` is not built yet.**
- If the 20M run finishes and passes the checks: rename `Release_CandidateV2.2`, set `DEFAULT_POLICY`, export ONNX + `.onnx.json` sidecar, `validate_deploy.py --onnx`, commit, rsync to the Pi, walk it with the user once G2 is online. Checks: calm flat falls <= 0.15 and speed >= 95% of V2.1; drift under the reference disturbance >= 50% below V2.1's; no category worse than V2.1 by more than 0.10 in falls (original ladder).
- No attribution trailers in commits; work on `development`; docs one-home rule; times in 12-hour ET; give timing estimates when launching anything.

## 6. Testing that remains on the original path (in order)
1. Wait for R3 (control) to finish and be scored (`ROUND 3 DONE` in `trained/phase_v22.log`). Re-judge R1 and R2 against it (the runner does this); decide whether R1's drift lever helped or hurt relative to the control.
2. **R4**: a milder drift disturbance (e.g. `G2E_DRIFT_TORQUE=0.25`, `G2E_DRIFT_PROB=0.5`), maybe with `G2E_FAC_HEADING` 5 -> 8 as a separate later lever, depending on the control. **R5**: yaw wobble lever (`G2E_FAC_YAW_TRACK` 9 -> 12, the lever the V2 -> V2.1 round used; `G2E_FAC_RESID_SMOOTH` 8.2 -> 10.5 is the other). **R6**: the best of each together. Add rounds by appending to `trained/v22_queue.json`; the runner waits 12 min for an entry, then goes to the check-in with the best passing round (if none pass it says so and does not start the final run: then decide with the user).
3. Hardware check-in (section 5), including: export the best 3M policy and put it on the Pi WITHOUT making it default; the user swaps servo 8 and reruns the six baseline walks (`bash tools/g2_baseline.sh start 6 <label>`, needs `G2_PI`), then walks the candidate. Compare yaw traces with `tools/walk_log_summary.py` against the 2026-10-06 baseline in `real-walk-data/2026-10-06/`.
4. Release the final run (`echo <tag> > trained/v22_final_go`), watch the 3M and 5M gates, then the full 20M (about 7.5-8 h at ~750 steps/s).
5. Build `benchmark_decathlon.py --hard-scale`; benchmark V2.1 and the new policy on both ladders; validate the deploy path; promote and deploy only if the checks hold; update STATUS, `real-walk-log.md`, `v22-log.md`, the plan and the memory notes.

## 7. Parallel paths NOT started (candidates if the sim rounds do not transfer)
- **Servo 8 swap, then rerun the six walks:** the cleanest test of whether the drift is hardware. Optional first: rerun `tools/servo_static_test.py` on a full battery.
- **Heading hold on the Pi:** set the policy's yaw command from its heading error (no retraining; works whatever the cause).
- **Mine the real logs further:** the real walks' yaw reaches +2.5 rad, far outside anything seen in training (episodes of 3 s), so the policy may be acting out of distribution; the commanded joints are asymmetric (rear hips 53 vs 60 deg). Replay the real walks' observations through the policy and the sim, and test whether training with long heading offsets changes it.
- A sixth-round idea if rounds trend well: both levers plus a modeled stuck servo (`clip:J:DEG` lever exists in `drift_probe.py`, not in the env as a training knob).

## 8. Code added in this campaign (all committed on `development`)
`rl_training/opencat-gym/opencat_gym_env.py`: `G2E_PAYLOAD_PROFILE=case` (spine 86 g / camera 15 g front / speaker 20 g rear, three welded bodies), `G2E_DRIFT_TORQUE` (+ `G2E_DRIFT_PROB`), `G2E_DRIFT_STROKE`, `G2E_DRIFT_SHOULDER_DEG`, `G2E_HARD_SCALE`, a `_motor_max` stuck-servo hook (probe only).
`drift_probe.py` (the scoring probe and lever sweeps), `phase_v22.py` (the round runner), `pi_pipeline/gait/baseline_runs.py` + `tools/g2_baseline.sh` (real baseline walks), `pi_pipeline/gait/policy_walker.py` (learned gait as the default forward gait), `pi_pipeline/link/fanout.py`.

## 9. Gotchas
- G2E env vars use the `G2E_` prefix; `DR_EVAL_FULL` is a module attribute, not an env var (my first probe silently skipped it).
- `pkill -f phase_v22.py` kills any watcher whose command line contains that text; kill the runner by pid. The training is a separate process; the runner resumes a round already training.
- Closing the Mac's lid sleeps it and pauses training. A Monitor expires after 30 minutes: re-arm it.
- 24-episode scores have roughly +-15 percentage points of noise in fall rates; do not chase small differences.
- `trained/` is gitignored (checkpoints, logs, JSON); the copies in `docs/rl/v22-data/` are snapshots only.
