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
At most five fresh 3M-step rounds (`phase_v22.py`, queue in `trained/v22_queue.json`), each judged against the frozen V2.1 in the same sim: calm flat walk (falls, speed),
the same walk under a reference yaw disturbance (heading error), yaw rate, and seven decathlon cells. A round passes if the calm walk does not regress and the drift
under the disturbance is at least halved. Then one 20M run with the best recipe plus the hard levels raised 10% (`G2E_HARD_SCALE=1.10`: shoves, slope range, overheat
cutback, obstacle and rubble heights; the nominal walk is not scaled), gated at 3M and 5M. The benchmark reports V2.1 and the new policy on the original ladder and on a
ladder with the hardest rung of each category raised 10%; results from the harder levels are marked and not compared with older runs' numbers.
Promotion to V2.2 and deployment happen only if the 20M run finishes and passes the final checks (see the plan given to the user, 2026-10-06).

## Rounds
(filled in as they finish)
