# v2.2: fixing the drift to one side on the 422 g robot (2026-10-06)

Plan, findings and round results for the next policy. Status of the run itself is in [`../STATUS.md`](../STATUS.md); this is the working log.

## Why
Six real hard-floor V2.1 walks on the case (2026-10-06, [`real-walk-log.md`](real-walk-log.md)): no falls, but a steady turn to the right of about +142 deg over 12.7 s
(roughly 8-14 deg/s) every time, and a roll swing (std 5.7-6.2 deg) above the old sim's. G2 now weighs 422 g against the sim's 377 g
(weights and positions: [`../hardware/specs.md`](../hardware/specs.md)).

## What the sweeping stage found (V2.1 frozen, 422 g payload, full randomization, flat ground, 12.5 s, `drift_probe.py`)
- **The heavier payload alone** (no drift lever): sim roll std 5.5 deg (real 5.9), pitch 3.1 (real 2.3), 2 of 12 episodes fall (the real walks never fell). The old
  377 g model gave 3.1 deg roll, so most of the roll gap was the payload.
- **Single-leg faults barely turn V2.1 in the sim:** servo zero offsets (8 and 14 deg), a shortened shoulder swing (to 50% and 20%), motor force cuts (40% and 15%),
  and a 30% friction foot all leave the heading within about +-20 deg of straight, and the harsher ones mostly add falls.
- **A direct yaw disturbance does:** a constant yaw torque (applied on every physics substep) turns V2.1 by 22 deg mean error at 0.45, 71 deg at 0.7 and 80 deg at 0.85
  (with 9, 13 and 16 of 24 episodes falling). The real turn is about 140 deg, so the real cause is stronger than any single fault the sim models.
- **Why it can be trained out:** the policy already observes heading (the orientation quaternion, yaw zeroed at the start of each walk) and the reward already penalizes
  heading error (`FAC_HEADING` 5.0), but nothing in training pushed it off course, so it never learned to use it. The fix is therefore a persistent yaw disturbance in
  training (`G2E_DRIFT_TORQUE`, per-episode random sign and strength, on `G2E_DRIFT_PROB` of the episodes). It does not claim to model the physical cause (the front-left
  shoulder servo, the mount, ...); it teaches "steer back when the heading error grows", which helps whatever the cause is. No new observation, so the deployed code and export are unchanged.

## Method
At most six fresh 3M-step rounds (`phase_v22.py`, queue in `trained/v22_queue.json`), each judged against the frozen V2.1 in the same sim: calm flat walk (falls, speed),
the same walk under a reference yaw disturbance (heading error), yaw rate, and seven decathlon cells. A round passes if the calm walk does not regress and the drift
under the disturbance is at least halved. Then one 20M run with the best recipe plus the hard levels raised 10% (`G2E_HARD_SCALE=1.10`: shoves, slope range, overheat
cutback, obstacle and rubble heights; the nominal walk is not scaled), gated at 3M and 5M. The benchmark reports V2.1 and the new policy on the original ladder and on a
ladder with the hardest rung of each category raised 10%; results from the harder levels are marked and not compared with older runs' numbers.
Promotion to V2.2 and deployment happen only if the 20M run finishes and passes the final checks (see the plan given to the user, 2026-10-06).

Round budget (user, 2026-10-06): up to six rounds. Rounds 1-5 test one lever at a time (drift fixes and yaw-wobble fixes); the last round tests the best drift fix and
the best yaw fix together. The better of that combined round and the best single-lever round goes to the hardware check-in (testing pauses before the 20M run so the
best 3M policy can be walked on G2; the user will also swap the front-left shoulder servo around then).

## Rounds
(filled in as they finish; machine-readable results: `rl_training/opencat-gym/trained/v22_results.json`)

| Round | Recipe | State |
|---|---|---|
| V2.1 reference (same sim) | frozen `Release_CandidateV2.1` | calm walk: 29% falls, 0.043 m/s (probe), roll std 6.0 deg; under the reference yaw disturbance (torque up to 0.5): heading error 49 deg, 58% falls; cells fell T2.2 0.20, T3.2 0.30, T5.2 0.20, T7.2 0.20, T8.1 1.00, T10.1 0.20, T10.2 0.25 |
| R1 `v22_r1_drift` | yaw torque up to 0.5 N*m on 70% of episodes, 422 g payload, nothing else | started 9:03 AM 2026-10-06; 3M steps ends about 10:10 AM, scored about 10:25 AM |

## Where to resume (written 2026-10-06 ~9:50 AM, for a new session)
- **Everything runs on the Mac in `rl_training/opencat-gym/`**: the runner `phase_v22.py` (log `trained/phase_v22.log`, output `trained/phase_v22.stdout`), the training
  (`trained/<tag>_console.log`), the queue `trained/v22_queue.json`, results `trained/v22_results.json`, V2.1 reference `trained/v22_baseline.json`.
  `ps -axo pid,etime,command | grep -E "[t]rain.py --tag|Python phase_v22"` shows what is alive. The runner and the training survive the Claude session ending.
- **Notifications belong to the Claude session that armed them.** A new session will NOT be told when a round finishes: read `trained/phase_v22.log` (lines starting
  `[v22 ...]`: `ROUND n START/DONE PASS|FAIL`, `HW CHECKIN`, `FINAL ...`) or arm a new Monitor on it.
- **To add the next round** (after a `ROUND n DONE` line) append an entry to `rounds` in `trained/v22_queue.json`: `{"tag": "v22_r2_...", "desc": "...", "extra": {"G2E_...": "..."}}`.
  The runner reads the file between rounds and waits 12 minutes for a new entry; with none it goes to the hardware check-in with the best passing round.
  Cap: six rounds (`MAX_ROUNDS`). Plan: rounds 1-5 single levers (drift, then yaw wobble e.g. `G2E_FAC_YAW_TRACK` 9 -> 12 and `G2E_FAC_HEADING` 5 -> 8); round 6 the best of each together.
- **Hardware check-in:** after the rounds the runner logs `HW CHECKIN` and PAUSES (no 20M run). Export the best round's policy (`export_onnx.py`, with its `.onnx.json` sidecar), put
  it on the Pi WITHOUT making it the default (`run_gait.py --policy <onnx>`), ask the user to walk it (the user will have swapped the front-left shoulder servo by then). To go on:
  `echo <round tag, or nothing> > trained/v22_final_go`; the runner then starts `v22_20m` (20M, `G2E_HARD_SCALE=1.10`, gates at 3M and 5M that stop the run on a regression).
- **Pass bar for a round:** calm falls <= min(0.15, V2.1 + 0.05) and speed >= 90% of V2.1, and heading error under the reference disturbance at least 50% below V2.1's. (V2.1 itself
  falls 29% on the calm walk in this sim, so the 0.15 bar is demanding; if no round passes the runner does NOT start the final run and says so.)
- **Pitfall:** `pkill -f phase_v22.py` also kills any watcher whose command line contains that text. Kill the runner by pid
  (`ps -axo pid,command | awk '/Python phase_v22/ && !/awk/ {print $1}'`); the training is a separate process and is not affected. The runner resumes a round that is already training.
- **Mac sleep:** closing the lid sleeps the Mac and pauses training (`caffeinate -i` only stops idle sleep). Keep the lid open or use clamshell mode on power.
- **After a successful 20M run** (finished, gates passed): export, benchmark V2.1 and the new policy on the original ladder AND on a ladder with the hardest rungs raised 10%
  (add a `--hard-scale` option to `benchmark_decathlon.py` first; not built yet), validate the deploy path (`validate_deploy.py --onnx`), then name it `Release_CandidateV2.2`, set
  `DEFAULT_POLICY` in `pi_pipeline/gait/residual_policy.py`, commit, `rsync` to the Pi, and walk it with the user once G2 is online. Promote only if the user's pass checks (see
  below) hold; otherwise stop and report.
- **Promotion checks (agreed 2026-10-06):** calm flat falls <= 0.15 and speed >= 95% of V2.1 on the original ladder; drift under the reference disturbance at least 50% below V2.1's;
  no category worse than V2.1 by more than 0.10 in falls on the original ladder.
