# ARM2 plan: the arm's walking policy for the 0.2 in wide shoulders and CLpaw

Approved 2026-10-31. Goal (user): a policy ready to deploy as soon as the wide shoulder parts and CLpaw are on G2. It keeps the arm, the claw and Petoi's arm
walk; only the legs change. Nothing is promoted or deployed until the user says the parts are installed. The arm's earlier policies (ARM1, ARM1R, ARM1X) and their
hardware results: [`arm-policy-plan.md`](arm-policy-plan.md). The parts: [`../../blueprints/paws-and-wide-shoulders.md`](../../blueprints/paws-and-wide-shoulders.md).

## Decisions (user, 2026-10-31)

- **Recipe**: ARM1X's, with what its screens adopted (PPO batch 512 x 5, entropy bonus 0.005)
- **Paw grip**: Not varied in training: CLpaw trains with a free pivot; the finished policy is scored at 1.8 and 3.6 mN.m as a check only
- **Servo strength**: Not varied
- **Two 20Ms**: Both from the same S3 stage, seeds 42 and 7; the better of the four candidates (final and avg5 of each) is picked
- **The 20Ms**: Run after the screens and stages without waiting for a go
- **Leg build**: A setting, off by default, so a stock-leg policy can be trained again: `G2_BUILD=arm_wide_clpaw`
- **Snags**: Kept, fixed for all training (round cords, a measured top per build); see below
- **Final report**: ARM2 against Petoi's scripted arm walk on the same legs, as well as ARM1X

## The simulator

`legs_model.py` builds the leg model from the arm's body model: the four leg servo mounts 5.08 mm further out (track 2.76 to 3.16 in) and a hinged plate on
each foot from `CLpaw.stl` (in the owner's prototypes folder, outside the repo; the folder is set in `~/.local/share/g2/prototypes_dir` or `G2_PROTOTYPES_DIR`):
pivot 4.5 mm above the sole, stops 30 deg toe up and 13 deg toe down, the stock foot showing 1 mm through the sole, 3.3 g a paw (the STL's volume in PETG at 100%).
Collision is the paw's convex hull. About 8 g of shoulder plastic is estimated on the body (not weighed): about 553 g in all. The build's settings and tops are the
`arm_wide_clpaw` entry in `rl_training/opencat-gym/build_limits.json`.

Checked before training (2026-10-31):
- Stock legs are unchanged: a fixed walk in the arm and pod worlds matches the old code step for step (every observation and reward, with resets).
- The paws sit on the feet, swing between their stops and touch the floor; no paw touches G2's own body.
- Training with the paws is 34% slower (7.59 against 5.67 min per million steps): the physics engine's four extra hinged parts and floor contacts. A simpler paw
  hull gained about 6% and changed the shape by up to 0.08 in; not adopted.

Bugs fixed for the new legs: a foot standing on its paw counted as in the air (the slip, clearance and gait rewards read it); four tools used fixed link numbers that
shift when paws are fitted (the benchmark's step-up probe among them); the body's weight scale also scaled the paws; parallel environments could read a half-built model.

## Hazard tops for this build

- **Step-ups: 15 mm kept.** Measured with ARM1X on the new legs: the front paws get onto 10 / 12.5 / 15 mm in 75 / 45 / 5% of episodes (stock legs 85 / 30 / 5%),
  none above; the claw jams from about 20 mm whatever the feet.
- **Snags: size 0.5 (7 mm) for the arm builds.** Cable height = 10 mm x (0.4 + 0.6 x size). The arm walk lifts its feet about 8 mm front, 4 mm back, and
  nothing got over a 10 mm cord.

## Snags (all training, user 2026-10-31)

The snag hazard (a cable across the path) could not be passed at most of its sizes:
- The benchmark ladder did not scale the cable with its size: every rung was the same 10 mm cable, so its snag scores never measured size. The ladder now scales
  snag height and rubble exposure as training does (`benchmark_v5.run_ladder`), so ladder numbers for those two hazards before 2026-10-31 do not compare with later ones.
- Training ramped the cable to 16 mm, which no policy crossed on any build.
- The cable was a square-edged bar; it is now a round cord by default (`G2E_SNAG_ROUND`, 0 = the old bar). Round cords are easier: V7 crossed 10 mm 83% round against
  33% as a bar.

Measured tops (round cords, 12 episodes a size): the pod world (V7 on wkF) crosses 7 / 10 / 13 / 16 mm 100 / 83 / 42 / 0%: top size 1.5 (13 mm), also the default
when no build is set. The arm on stock legs: 5.5 / 7 / 10 mm 67 / 33 / 0%: top 0.5 (7 mm), the same for the new legs.

## Training (unattended runner `phase_arm2.py`)

1. **Baselines** in the new-leg world, 100 episodes a test: ARM1X unchanged, and Petoi's scripted arm walk.
2. **Two 3M screens:** `arm2_ctrl` (the recipe) and `arm2_ev15` (a slope bin counts after 15 outcomes, was 30: ARM1X's slope frontiers waited on evidence).
   Rule, set before the results: `arm2_ev15` is adopted if its flat-ground falls are 0, its mean ladder falls no more than the control's + 0.005, its ladder success
   no less than the control's - 0.02 and its roll no more than the control's + 0.5 deg.
3. **S0 to S3** (9M), fresh, with what was adopted.
4. **Two 20Ms** from S3, seeds 42 and 7, no plateau stop, progress checks every 2M (the snag ladder included).
5. **Pick:** final and avg5 of each 20M scored in full; no flat-ground falls first, then the lowest mean ladder falls. Exported as `trained/ARM2cand_ppo.onnx` with its
   sidecar (`legs: arm_wide_clpaw`).
6. **Verdict** against ARM1X on the new legs, reported only: no flat-ground falls; ladder falls no higher; roll no more than + 0.5 deg; heading no more than + 5 deg and
   under 20; calm-walk speed at least 90%. Then the grip check (the pivot at 1.8 and 3.6 mN.m) and the comparison with Petoi's scripted walk.

Log `trained/phase_arm2.log`; `python phase_arm2.py status`; halt file `trained/arm2_halt`.

## When the parts are on G2

Weigh G2 (a retrain on the real number is offered if he is more than 15 g off 553 g); promote ARM2 for the arm only (`promote_release.py ... --attachment-only`;
`DEFAULT_POLICY` does not change) and deploy with the Pi idle; add a hardware epoch for the new legs. The first walks follow the blueprint's install checklist. Also collect
the open details in "The arm in the sim against the real arm" below.

## Sim-to-real settings found off (sweep of 2026-11-01)

The real-size claw was off; it is now on. Others that exist in the simulator to narrow the gap and are off in the ARM2 recipe. **Owner decision 2026-11-01: no changes to these.** They stay off; the table is the record of what they are:

- **`G2E_MOTOR_SCALE_RAND` (in the `faults` lever, 0.12)**: What it models: Battery sag: a full pack sags 0.3 to 0.45 V walking, motors lose strength; Why it is off / state: Not in the V5 to ARM2 recipe; the faults lever was left out of the 20M plans (`archive/rl/next-20m-plan.md`) and no measured negative result is recorded. Owner's call: the real sag is measured, so it fits the "on if it narrows the gap" rule
- **`G2E_FAULT_STUCK_PROB`, `FAULT_WEAK_PROB`, `FAULT_OFFSET_PROB` (the `faults` lever)**: What it models: Sticky, weak or offset servos (the real front-left shoulder sticks); Why it is off / state: Same as above
- **`G2E_DRIFT_TORQUE`, `DRIFT_STROKE`, `DRIFT_SHOULDER_DEG`**: What it models: One-sided drift in training; Why it is off / state: Owner decision 2026-10-07: no drift training; the policy is heading-blind and the Pi steers
- **`G2E_PAW_PIN_DAMP`, `PAW_SPRING_K`, `PAW_REST_DEG`**: What it models: The paw pivot's friction, return spring and resting angle; Why it is off / state: Unknown real values (owner: paw grip not varied in training); see the open details below
- **Roll disturbance**: What it models: Real roll about 1.7 to 2 times the sim's (ARM2 sim 1.8 deg); Why it is off / state: No setting yet. The largest known and measured gap. Candidate for the next training plan once real ARM2 walks exist to calibrate against
- **Foot slip / friction**: What it models: Real G2 travels about 16% further than the sim for the same command (2026-10-06 note); Why it is off / state: Friction and servo-gain sweeps did not help in 2026-10; the Pi scales the commanded speed instead

## The arm in the sim against the real arm (2026-11-01, from the user's photos)

Eight photos of G2's arm in the rest pose (top, side, front, underside, close-ups; no CAD, no calipers; scaled against the pod and the 29 x 47 mm camera case, good to about 10%).

What the photos settled and what changed:
- **The claw's shape and size.** The real claw is a round orange base (printed, honeycomb infill) with two black pointed, hollow jaws and a small spring across them: 1.9 in wide,
  0.6 in tall, about 2.7 in from the base's back edge to the jaw tip. The sim collided with two thin bars, 0.9 in wide and 0.4 in tall, reaching about 1.3 in less far.
  The viewers draw the real claw (`arm_shapes.py`), and the sim collides with the same outline (`G2E_CLAW_REAL`, on in both arm builds in `build_limits.json` since 2026-11-01; same weight, same height off the floor; the older ARM runs trained with the bars).
- **The camera** matches what the sim had: a 29 x 47 mm case, upright, lens centred and facing forward. No change.
- **The claw servo** lies forward with its output face into the claw base, as in the sim. No change.
- **Not modelled, details needed (below):** the arm is sprung (a pair of black crank arms and a long tension spring) where the sim's is rigid; a coiled USB cable runs from the
  pod's top to the camera; servo and power wires loop loose in front of the chest; the arm's real weight.

### Real-size claw check (2026-11-01, sim only, nothing retrained)

ARM2 (final weights) and Petoi's walk scored again on the new legs with the claw's real outline as the collision shape (`G2E_CLAW_REAL=1`: 1.9 in wide, 0.6 in tall, about 1.3 in further forward), same scorer, seeds and episode counts as the results above (`trained/arm2_report/arm2_realclaw.json`, `scripted_realclaw.json`). Ladder success, thin bars -> real-size claw:

- **Overall**: ARM2: 76.4 -> 76.8%; Petoi's walk: 66.8 -> 67.0%
- **Step-up**: ARM2: 27.5 -> 24.4%; Petoi's walk: 20.0 -> 18.8%
- **Rubble**: ARM2: 38.8 -> 38.8%; Petoi's walk: 20.0 -> 21.2%
- **Boxes**: ARM2: 43.1 -> 44.4%; Petoi's walk: 18.8 -> 20.0%
- **Snag cord**: ARM2: 38.8 -> 45.0%; Petoi's walk: 1.9 -> 1.2%
- **Switchback turn**: ARM2: 91.9 -> 91.9%; Petoi's walk: 85.0 -> 85.6%
- **Slopes, step-down, rough floor**: ARM2: 100% unchanged; Petoi's walk: 93 to 100% unchanged

No falls either way; flat-ground speed, roll and heading unchanged. Every difference is inside the scorer's noise (about 5 points). The claw's real size does not change the sim results because the obstacles in the course are lower than the claw is held (about 1.25 in), so the claw rarely meets them. It is on in the arm builds anyway: it is the more accurate claw, and the earlier numbers stand. What could still change this: the claw's real height and reach while walking (the open details below), and a claw held lower.

### Open details to provide once G2 is assembled (legs recalibrated, wide shoulders and paws on)

- [ ] **Side photo standing in the walking pose:** level with the claw and square-on, with a coin or ruler next to the claw at the same distance from the camera. Gives the claw's
      real reach ahead of the pod and its height off the floor (the sim's 1.25 in was measured on stock legs; the paws and the new pose may change it). The reach is the one
      size the rest-pose photos could not give.
- [ ] **Front photo standing**, the same way: is the claw centred, and are the jaws closed while walking?
- [ ] **Weights (kitchen scale, grams):** G2 in full (the sim assumes about 553 g), the coiled cable alone, and if the arm comes off easily, the arm with the camera. The sim
      assumes 78 g of arm and camera, varied by plus or minus 20%.
- [ ] **How springy the arm is:** push the claw gently up, down and sideways with a finger and say how far it moves (in) and whether it springs back. A slow-motion phone
      video from the side of G2 walking shows whether the claw bounces. The sim's arm is rigid; a bouncing claw could be part of why the real roll is about 2x the sim's.
- [ ] **The coiled cable while walking:** how high it rises above the pod, whether it pulls the claw sideways or touches a leg, and whether it could be shortened or clipped down.
- [ ] **The loose wires:** tie the servo and power wires in front of the chest out of the legs' way (a hardware fix), and a photo afterwards.
- [ ] **Does the claw touch the floor while walking?** Scuff marks, or watching a few walks. The sim keeps it 1.25 in up.

- [ ] **The paws' pivot (CLpaw):** how stiff it is by hand (flops freely, drags a little, or holds its angle), the angle it rests at when lifted, and whether it springs back toe-up or toe-down. The sim has a free pivot with no spring (`G2E_PAW_PIN_DAMP`, `G2E_PAW_SPRING_K`, `G2E_PAW_REST_DEG` all 0; checked only at 1.8 and 3.6 mN.m of grip). A video of one foot lifting would do.
- [ ] **The lift-servo angle while walking** (the claw's carrying height): which direction raises the claw and how many inches one degree gives, from two or three photos at set angles (`python -m pi_pipeline.attachments walk-lift N`, below). The setting exists and defaults to the firmware's own angle.

Each answer goes into this section with its date; what changes in the sim follows from it (the claw position, the arm's weight, a sprung arm if it bounces).

## Results

### ARM2 sim result, 2026-11-01 (training 1:58 AM to 10:45 AM; report: Artifact "ARM2 Training Report")

The run needed no fixes and never halted. Baselines on the new legs: ARM1X success 74%, Petoi's scripted walk 67%. Screens: `arm2_ctrl` and `arm2_ev15` (slope evidence 15) both no falls, success 76%; `arm2_ev15` adopted by the rule. S0 to S3 done 4:27 AM; 20Ms ("seeds 42 and 7") done 7:05 AM and 9:43 AM, every 2M-step check showing no falls, roll 1.8 to 2.0 deg, heading 3 to 4 deg. **The second 20M was an exact repeat of the first** (identical at every check and in every scored number): a chained stage ignores `G2E_SEED` (train.py reads it only for a fresh policy), and the runner set nothing else. Fixed in `phase_arm2.py` (`G2E_CHAIN_SEED` for the extra 20M; test in `test_legs.py`); a real second seed has not been run, so the run-to-run spread is unmeasured. The candidates (final and avg5, scored twice each) scored alike (success 76 to 77%, step-ups 28%, no falls); the final weights were picked (tied on falls) and exported as `trained/ARM2cand_ppo.onnx`.

All in the new-leg world, 100 episodes per test:

- **Calm-walk speed (m/s)**: Petoi's walk: 0.101; ARM1X: 0.114; ARM2: 0.111
- **Roll / heading (deg)**: Petoi's walk: 1.2 / 1; ARM1X: 1.6 / 3; ARM2: 1.8 / 3
- **Ladder success**: Petoi's walk: 67%; ARM1X: 74%; ARM2: 76%
- **Snag / boxes / rubble / step-up**: Petoi's walk: 2 / 19 / 20 / 20%; ARM1X: 30 / 33 / 35 / 22%; ARM2: 39 / 43 / 39 / 28%

Promotion checks against ARM1X on the new legs: all five pass (reported only; nothing promoted or deployed). Paw pivot at 1.8 and 3.6 mN.m: no falls, success 80 and 81%, step-ups 37 and 36%, heading 6 and 5 deg.

Stock legs against the new legs (`compare_legs.py`, scored the same day; `trained/arm2_report/legs_compare.json`): ARM1X on stock legs falls 1.8% over the hazards, roll 2.2, heading 7, success 73%, snag 46%, step-ups 26%; ARM1X on the new legs 0 falls, roll 1.6, heading 3, success 74%, snag 30%, step-ups 22%; Petoi's walk gains most from the parts (success 58% to 67%, step-down 57% to 96%, no falls). The parts help steadiness and hazard falls, cost cord and step-up crossing; ARM2 recovers part of it (snag 39%, step-ups 28%). Differences under about 5 points of success are inside the noise. Not tested: heavy loads (where the earlier sim tests found the parts' biggest gain), servo load and heat, the printed fit, the real pivot friction.

Still stuck at 20M: step-ups, rubble, boxes (as ARM1X). Training with the paws ran 34% slower per step.

## ARMW: the wide shoulders on the stock feet (2026-11-03)

The CLpaw feet did not fit G2's feet (user, 2026-11-03), so only the 0.2 in wide shoulder part is fitted. ARM2 was trained for shoulders plus paws, so a new policy was trained for the build the robot actually wears:
`G2_BUILD=arm_wide` (`build_limits.json`: `G2E_SHOULDER_WIDEN_MM` 5.08, no paw, claw as measured, body mass scale as `arm_wide_clpaw`, about 540 g, not weighed; the arm's own hazard tops, step-ups 15 mm and snags 7 mm, not re-measured:
the feet are the stock ones). Runner `rl_training/opencat-gym/phase_armw.py` (babysitter `armw_babysit.sh`, log `trained/phase_armw.log`, reports `trained/armw_report/`): baselines, S0..S3 (9M, fresh, ARM2's adopted `slopes:15`, no screens), ONE 20M (seed 42, user's decision), pick final or avg5,
export `ARMWcand`, verdict against ARM1X on the same legs. Promotion and deploy were automated and unconditional (user: the new build needs its own policy; `tools/armw_finish.sh`): promoted for the arm only (`--attachment-only`, `DEFAULT_POLICY` unchanged), hardware epoch `hw-2026-11-03` added.

Training 12:57 AM to 4:31 AM; the 20M took 2:12 AM to 4:14 AM. No flat-ground falls at any 2M check; ledge-up, rubble and boxes were marked stuck by the frontier from 8M (as for ARM2); snag crossing rose to 84% at 20M. The pick was avg5 (0.000 against 0.001 ladder falls for the final weights). All on the new legs, 100 episodes a test (40 for the ladder):

- **Flat-ground falls**: ARMW: 0.00; ARM1X (the arm's gait until now): 0.00; ARM2 (trained with paws): 0.00; Petoi's walk: 0.00
- **Calm speed (m/s)**: ARMW: 0.113; ARM1X (the arm's gait until now): 0.112; ARM2 (trained with paws): 0.109; Petoi's walk: 0.096
- **Roll / heading (deg)**: ARMW: 2.0 / 7; ARM1X (the arm's gait until now): 1.8 / 6; ARM2 (trained with paws): 1.9 / 6; Petoi's walk: 1.3 / 4
- **Ladder falls**: ARMW: 0.000; ARM1X (the arm's gait until now): 0.002; ARM2 (trained with paws): 0.002; Petoi's walk: 0.003
- **Ladder success**: ARMW: 80%; ARM1X (the arm's gait until now): 75%; ARM2 (trained with paws): 77%; Petoi's walk: 60%
- **Step-up success**: ARMW: 39%; ARM1X (the arm's gait until now): 27%; ARM2 (trained with paws): 34%; Petoi's walk: 16%

Verdict PASS on all five rules (the scorer's noise is about 5 points, so the gain over ARM1X is modest; ARM2 transfers to the paw-less legs about as well). Not done: the real weight (retrain if more than 15 g off 540 g), the hazard tops re-measured on these legs, a second 20M seed. The first walks on G2 are the real test; deployed to the Pi when it next comes online.
