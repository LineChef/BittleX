# Heavy-load policy: a gait that stays stable carrying up to 1 lb (planned 2026-10-19, not started)

Goal (user, 2026-10-19): a new policy that is clearly **more stable** than V7 when G2 carries a heavy load. The most he carries is **1 lb (454 g)**. He may walk **slower** under the load;
speed is traded for stability, never the other way round.

Assumption to confirm: 1 lb is the whole payload, the block on his back plus the head (today 185 g + 42 g = 227 g), so the heaviest case adds 227 g.

## The load, as the sim already models it (`opencat_gym_env.py`, `PAYLOAD_PROFILE == "pod"`)
- A large block on his back (`PAYLOAD_BOX_HALF` 94 x 59 x 38 mm), centred 9.2 mm behind the middle of the torso (`PAYLOAD_POS` x = -0.0092), sitting flush on it. It weighs 185 g today.
- A large head at the front (`HEAD_MASS_POS` x = +0.068), 42 g.
- The heavier load goes into **the block**: same box, same place, more mass, up to 412 g (454 g in all with the head). The head stays at 42 g.
- Today the pod profile has no weight variation and the policy has no idea what it carries (`PAYLOAD_MASS_RAND = 0`, set 2026-10-18 because the pod is weighed). Only the general +-18% link-mass jitter (`RANDOM_MASS`) varies.

## Step 1: find the real limit and fit the sim to it (hardware, one session, each walk on the user's go)
The sim's servo strength (`MOTOR_FORCE` 0.2) has never been checked under a heavy load. A sim that is too strong teaches a gait the real servos cannot hold.
- Add weight on top of the pod in steps: today (227 g payload), +60 g, +120 g, +180 g, +227 g (1 lb). A taped bag of coins, centred on the pod.
- At each step: stand (eased), one 12 s V7 walk on hardwood. Log body sag, knee angle error (servo feedback), battery sag, speed and drift.
- Stop the ladder at the first step where he cannot stand or walk cleanly. **That step is the top of the training range** (standing rule: difficulty never above what a capable policy can pass).
- Fit the sim's servo strength and battery sag (`_torque_scale` sag) to those logs. This also covers the V7 sysid capture already planned (`../rl/sysid-capture-plan.md`).

## Step 2: environment changes (a new `heavy` payload profile; nothing changes for V7)
1. **Load range:** each episode gets a block mass between 185 g and 412 g, drawn with extra weight toward the heavy end (most of the training time is spent where stability matters).
   Ramped with the existing adaptive level (`ADAPTIVE_LEVEL`): the top of the range rises as the policy succeeds, and never past the measured hardware top.
2. **The policy is told the load:** one new input, the carried weight. On G2 it comes from the attachment setting (`g2attach` already says what he wears; a weight field is added).
   In training it is randomized +-15% around the true value, so a slightly wrong number does not break him.
3. **Speed follows the load:** the commanded speed range narrows as the load grows, to about 60% of today's top speed at 1 lb. A slow, steady walk at 1 lb counts as full success.
4. **Rewards (on top of the V6 recipe):**
   - body roll and pitch steadiness, weighted more as the load grows;
   - servo heat (the same I2t model as the Pi's `gait/thermal_guard.py`), so he does not win by straining;
   - foot slip;
   - a lower body height is allowed under load (it lowers the centre of mass), but dragging the belly or feet is penalized.
5. **Disturbances stay on:** shoves, servo faults, rough floor. A heavy top load is exactly when a shove tips him.

## Step 3: training (standing rules: fresh from S0, 3M cap on screens, 20M only on the user's go)
- **Three 3M screens, each a fresh run** (about 25 min each, about 1.5 h for all three; times from `tools/eta.py`):
  - **A:** the load range only.
  - **B:** A plus the load input.
  - **C:** B plus the load-scaled stability, heat and slip rewards and the speed scaling.
- **Gate for each screen:** learnable (fewer falls and less roll than V7 at the heaviest load), and no regression at today's 227 g payload (V5 benchmark mean falls within noise of V7).
- **Staged chain like V6**, using the winning screen, fresh from S0: flat foundation under load, terrain under load, slopes and the ledges only up to what passes under load.
- **One 20M consolidation run** (about 2 h 20 min of training) only on the user's go.

## Step 4: how it is judged (sim)
- A new **load ladder benchmark:** payload 227 / 300 / 380 / 454 g, crossed with the calm 12.5 s walk, 5 and 10 deg cross-slopes, downhill, shoves, rubble and a 15 mm ledge.
- **Measured at each load:** falls, roll and pitch steadiness, peak tilt, speed against the command, drift, time at the servo force limit, servo heat after 60 s, body height.
- Compared against V7 and the scripted walk at every load.
- `passability_audit.py` confirms the heaviest load stays passable on every cell used in training.
- **Promotion bar:** at 454 g, clearly fewer falls and less roll than V7; at 227 g, no worse than V7. Promotion and deployment stay the user's call.

## Step 5: on G2
- The same weight ladder as step 1, one walk per step on hardwood, each on the user's reply.
- Logged: servo feedback, battery %, heat guard, roll and pitch.
- Any walk that tips or trips the heat guard ends the ladder.
- Pi side: the walk loop passes the load input (the policy sidecar says the policy takes one); `g2attach` gets the weight.

## Risks
- The real limit may be below 1 lb (plastic-geared servos, the PiSugar S browning out under current). Step 1 finds out before any training.
- A heavier load drains the battery faster and heats the servos sooner; walks get shorter.
- A high, heavy block is what tipped him in the check pose (2026-10-18). Tricks and poses stay as they are; this plan is only the walk.

## Attempt 2 (2026-10-19, running): V7 fine-tuned for the pod

Attempt 1 (a fresh run with a random load range and a load input) was not better than V7; its terrain curriculum stalled under the mixed loads. The user then set the goal more
precisely: make the default walk steadier with **today's** payload, with headroom up to 1 lb for the arm. Changes, all approved by the user:
- **Training on top of V7**, a one-time exception to the rule against training on a finished 20M, with the trainer's fine-tune learning rate and the action noise reset to std 0.15.
- **Weight as in V7** (+-18% on G2's own parts), plus: half the episodes at today's payload, the rest with up to 227 g more in the block, the cap rising from 0 over the first 6M.
- **A small crouch**: 1.5 mm lower at today's payload, growing to 4 mm (0.16 in) at 1 lb. No paw-height penalty in training (crouching and high paw lift together could make the
  gait unstable); paw lift is a pass rule instead.
- **12.5 s obstacle episodes** (the obstacles stay where they were), slower commands only with extra weight (60% at 1 lb).
- **Up to 20M**, checked every 2M at 100 episodes per cell; cut off once three checks in a row do not improve the today's-payload score (not before 12M).
- Rules, finalists and pass bar: `rl_training/opencat-gym/phase_heavy2.py` docstring. Nothing is promoted or deployed without the user.
- **Control run (added before any result, user-approved):** after the fine-tune is scored, the same fine-tune of V7 without the weight changes (no extra load, no crouch, no
  slower commands; same 12.5 s obstacle runs, noise reset and learning rate), for as many steps as the fine-tune ran. It answers whether V7 improves just from a second pass over
  the same ramping difficulty (the curriculum restarts easy), and whether the weight changes help beyond that.
