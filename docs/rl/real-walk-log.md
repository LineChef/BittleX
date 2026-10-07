# Real-hardware walk log

First walks of G2 on real floors. Started 2026-10-01. Hard floor and ~1/4 in (6.4 mm) pile
carpet, off the stand, payload = what V2.1 was trained with but **mounted only temporarily**
(it can shift between runs; not accounted for yet). Run logs are CSVs written by
`run_gait.py --log`, `run_gait.py --openloop --log` and `fw_skill_log.py` (`~/g2_runs/` on the
Pi, copied to the dev machine); summarize them with `tools/walk_log_summary.py`.

> **Status: paused on 2026-10-01. Read "Where we left off" first.**
>
> Raw logs, an index of every file and the non-CSV measurements are archived in
> [`real-walk-data/2026-10-01/`](real-walk-data/2026-10-01/README.md).

## Where we left off

> **2026-10-06:** the gait's next steps are in [`v3-retrain-plan.md`](v3-retrain-plan.md) (start at §0), which supersedes the open questions
> below for walking. The drift is explained as far as the data allows in "Why V2.1 drifts right" further down. Carpet questions (3-4 below)
> are deferred to their own session. The "Uncommitted at the pause" note at the end of this list is out of date (everything is pushed).

**State of the robot**
- Deployed gait: `Release_CandidateV2.1` (`DEFAULT_POLICY`; sidecar `cmd_send_every_n: 3`, so the
  loop sends a joint command every 3rd tick, as it was trained). Firmware balance is turned off
  by `run_gait.py` for a run and restored (`gB`) on exit.
- Pi <-> BiBoard link works (needed `XS` over USB once; wires TX2->pin 10, RX2->pin 8). IMU reads
  the stock 5.0 Hz on the Pi's UART. Camera is on the Pi's USB (`/dev/ttyACM0`, mounted rotated
  90 deg so it must be turned upright) and was **not** used in the walks.
- IMU calibrated with `gc` (see `hardware/petoi-firmware-reference.md`). **Confirmed to survive a full
  power cycle (2026-10-01):** after the BiBoard and Pi were powered off and on, balance-on `kbalance`
  reads roll 1.0 / pitch -1.1 (std 0.1), balance-off 0.8 / -1.0, at rest -2.8 / 0.0. `XS` also persisted
  (the Pi link worked straight away).
- Walk loop has a fall guard (`--fall-abort-deg`, default 60 deg for 0.3 s -> rest).

**Open questions, in the order I would take them**
1. *Which gait changes survive on the hard floor at all?* The lift/stride variants below were
   only ever run on carpet, and the lightest one **also falls on hard floor** (3.3 s), so the
   scaled `wkF` variants are themselves unstable open-loop; the carpet is not the only cause.
   Hard-floor controls to run first, each 8 cycles with `--ramp-cycles 1 --openloop-balance-off`:
   (a) `--lift-scale 2.0 --lift-joints knees --shoulder-scale 0.7` (the one that took 2 good
   steps on carpet), (b) knees 1.5 / shoulders 0.85, (c) all joints x1.3, (d) the best of those
   at half speed (`--hz 40`). Only variants that walk 8 cycles on hard floor go to carpet.
2. *Hands-off drift runs in a larger space* (V2.1, nobody touches G2): measure lateral offset +
   heading with a tape, plus the clean yaw trace. Run 6 (hands off, short lane) drifted ~16 deg
   right, "hard early, then stabilizes a little".
3. *V2.1 on carpet, 3+ runs, with the fall guard* -- first carpet run fell twice (details below).
4. After those: choose a direction for carpet (nothing decided): a higher-lift/shorter-stride gait
   base, Petoi's `carpetF`, or a retrain with a pile/drag model (H10).
5. When the rest of the hardware is on and weighed: re-set the payload model and **retrain**
   (backlog H2); today's runs are the baseline for that. Re-do `XS`/`gc` after any reflash (both persist across power cycles).

**Uncommitted at the pause:** everything described here (code, tests, docs) is local. Nothing has
been pushed since the camera/IMU-link work (`development` at `6a2e7e7`).

## Servo troubleshooting -- where we left off (2026-10-02)

Raw data and printed tables: [`real-walk-data/2026-10-02/`](real-walk-data/2026-10-02/README.md). Detail below
under "Servo feedback tests".

**Symptoms (user, after re-calibrating the limbs):** (1) the FR shoulder visibly lags/sags *after* the servos relax --
the rest pose is right when the leg first drops into it; (2) the firmware step gait moved G2 laterally right (this
**went away** after the IMU `gc` calibration + recalibration: `kvtF` now runs steadily, ~1 inch drift left, yaw -29 deg).

**Findings so far**
- **Front-left shoulder servo (servo 8) is faulty or mis-sensing -- the strongest result.** Loaded and unloaded it
  keeps landing on ~42 deg whatever it is commanded to (44-60), sometimes reaching the target, with random readings
  of 18-27. 8 deg low at the stand angle (50), which is the centre of every gait run. Reproducible; independent of load.
  Not yet known whether the leg itself moves to the commanded angle (the user's view of a slow sweep was not recorded).
- **Front-right shoulder (servo 9):** mostly accurate, but ~6 of 32 readings in a sweep were wild (-25..+17 at targets
  40-65). Looks like feedback glitches, not movement. An earlier unloaded run showed the same.
- **Back shoulders and all four knees track well unloaded.** Knees sag under load (rear knees ~20 deg short of 0 when
  standing; FL knee erratic) -- load/torque/supply, to re-test on a full battery (pack read ~7.6-7.8 V).
- The leg-to-servo map is right (8, 9, 10, 11 = FL, FR, BR, BL).
- The FL shoulder is a *shoulder* servo, which on a Bittle X uses a **short** servo cable (Petoi assembly guide); the
  joint index does not map to a PWM pin number, so find the connector by following the cable.
- Suspects, not separated: worn/flat position sensor in servos 8 (and 9), a loose/damaged connector or cable on the
  adjacent servo 8/9 channels, a slipped horn or screw, a stripped gear.

**Next, in order**
1. Ask what the FL leg physically did during the slow servo-8 sweep (smooth, stuck, or twitching) -- sensor fault vs
   servo/mechanical fault.
2. Wiggle test: stream servo 8 (and 9) feedback while gently wiggling each connector/cable (servo end, then BiBoard end).
3. Reseat servos 8 and 9 connectors (power off, inspect pins); then swap servos 8 and 9 (or just their cables) and rerun
   `tools/servo_static_test.py` -- does the fault follow the servo or stay with the leg?
4. Hand check, servos relaxed, G2 upright: move each front shoulder by hand and compare.
5. Full-battery rerun of the static test; capture the rest-relaxation (feedback from the moment `d` is sent) for the
   FR shoulder -- needs a fixed `servo_response_test.py`.
6. If servo 8 is the culprit: replace it (Petoi spare), recalibrate the joint, re-run the walk comparisons. Everything walk-wise
   logged on 2026-10-01 was run with this leg's shoulder ~8 deg low, so re-check the hard-floor/carpet results afterwards.
7. Remaining gait A/B not run: `kvtF` with balance off, `kwkF`, `kcrF` (step gait is fine now, so lower priority).
- G2 must not be put on its back: the Pi and BiBoard are exposed. Unloaded tests are done by holding it upright in the air.
- Protocol notes: feedback works only over the Mac USB cable (unplug it for untethered walks, plug it back for servo tests).

## Is the learned gait actually better than the scripted one? (evidence as of 2026-10-03)

**Not proven.** The scored head-to-head on the real robot (H1) has not been run.

- **In sim, after the payload-inertia fix:** `Release_CandidateV2` beat scripted on ledges (13.3 % vs 26.7 % falls) and was faster than V1 in every
  category; `V2.1` (the deployed policy's lineage) is recorded as faster than scripted in every cell and with fewer falls on the 25 mm ledges
  (10 % vs 40 %). The per-cell speed margins are not written in the text (they are in the linked report), so "how much" is unquantified here.
- **Earlier sim numbers are suspect:** `hw1_20m` was measured on a tilt-locked body — flat ground 0.108 vs 0.101 m/s (+7 %), rough ground
  0.038 vs 0.015, 20 mm obstacles 0.050 vs 0.015, 20° descent 0.069 vs 0.022 — big on hard terrain, small on flat; invalidated by the bug.
- **On the real robot:** V2.1 on hard floor ~0.118 m/s vs the scripted open-loop walk ~0.12 m/s (different conditions, not a matched test), V2.1 drifts and
  rolls ±6°, and both fail on carpet. The learned gait's unproven advantages are speed/heading command following, hard-terrain performance and
  mid-walk catching; the firmware has no mid-walk catch.

## What the hardware looks like now

- **Hard floor, V2.1, 10 cycles (12.5 s, `--cmd 0.10`):** upright and steady in all 6 runs,
  ~4 ft 10 in (~1.47 m, ~0.118 m/s) -- about the speed of the scripted open-loop walk (~0.12 m/s),
  slightly over the 0.10 command. Gait period 1.25 s (100 ticks) as designed. Thermal guard `ok`
  throughout (the guard names the FR shoulder as hottest in ~95% of ticks; it is a model estimate,
  not a measured temperature).
- **Roll swing is large and steady:** std 5.9-7.0 deg, range about -19 to +9 deg, pitch std ~3.5 in
  every V2.1 run. The sim body rolls ~4 deg std in the same replay (see "Sim vs real").
- **Heading drifts right** (log yaw positive = right; includes hand corrections). Run 1 (before the
  IMU calibration) was a steady ~10 deg/s right turn (+132 deg); later runs wander a few degrees
  because the user steered them back; hands-off run 6 drifted +16 deg. (Corrected 2026-10-06: the loop
  does feed the rebased yaw to the policy, since `79da931`, but with the opposite sign to the sim's and V2.1
  ignores it, so nothing holds a heading; see [`v3-retrain-plan.md`](v3-retrain-plan.md) §1.1.)
- **Distance is consistent run to run**; drift is the part that varies.
- **Policy command bias (from the logs):** averaged over the hard-floor runs V2.1 commands the
  back-left shoulder ~+7.5 deg and back-right knee ~-7.8 deg off the scripted pose (the uneven
  diagonal correction the sim notes describe).

### Hard-floor runs

Numbering matches the log files (`hard_v21_runNN`). Roll/pitch mean / std in degrees. Yaw = change
at 25/50/75/100% of the run.

| run | distance | seen | roll | pitch | yaw |
|---|---|---|---|---|---|
| open-loop scripted `wkF`, 6 cycles | ~3 ft | stood cleanly, no grinding, signs OK; curved left | -- | -- | -- |
| 01 (before `gc`) | ~5-6 ft (eyeballed) | curved right, steady turn | -2.7 / 6.6 | +0.9 / 3.5 | +24 +68 +120 +132 |
| 02 | 4 ft 10 in | slight right; small push near the end | -1.8 / 5.9 | -1.8 / 3.5 | -7 -8 -29 -22 |
| 03 | same | drifted right, corrected by hand (desk edge) | -1.3 / 6.3 | -2.1 / 3.6 | +5 -17 -8 +2 |
| 04 | same | drifted right, corrected | -1.3 / 6.2 | -2.0 / 3.4 | +2 -11 +5 +18 |
| 05 | same | drifted right, corrected | -2.1 / 7.0 | -1.4 / 3.5 | +11 +12 -39 -15 |
| 06 (hands off) | ~4 ft 2 in straight line | drifts hard early, then stabilizes; not touched | -1.8 / 6.7 | -2.1 / 3.9 | +11 +19 +16 +16 |

## Carpet (~6.4 mm pile)

| attempt | result |
|---|---|
| V2.1 policy, 10 cycles | fell at 2.0 s and again at ~11 s, each time rolling over the FR shoulder (once head-first); feet catch in the pile. Roll -52 / 68 over the run |
| scripted `wkF` x1.0 open-loop | fell, feet catching on the pile (no log; firmware balance probably on) |
| firmware `kcarpetF` (~27 mm lift) 10 s | **stayed up but walked in place**; back-right leg sagged while stepping. Roll -10.5 / 11.6 (range -36..+8). The same gait on hard floor walked forward ~1 ft 9 in, no sag, roll +0.4 / 3.5 |
| scripted, all joints x1.6 (~21 mm lift, stride +55%) | walked forward a little, fell sideways at 2.7 s; roll swung -45..+14 before the fall |
| scripted, all joints x2.0 (~31 mm, stride +85%) | same: fell sideways at 2.7 s (roll -43..+15). User: the long strides cost stability; feet only snag occasionally |
| knees x2.0 + shoulders x0.7, no ramp (~26 mm, stride ~80 mm) | fell at 0.7 s -- the jump from the stand pose into the first scaled frame |
| same, 1-cycle ramp-in | 2 good steps, fell at 2.9 s. User: the carpet is a little bouncy; shorter steps may help |
| knees x1.75 + shoulders x0.1, ramp (~25 mm, stride ~50 mm) | fell sideways at 3.0 s (roll -77, pitch stayed within -16..+11) |
| same variant, voltage logged | **invalid as a fall test: the user was holding G2 up for most of it.** Voltage held 7.60-7.72 V for the first 8 s (incl. the first tilt at 1.3 s) then read 7.37 V in the last 2 s while it was held/thrashing |
| same variant on **hard floor** | **fell at 3.3 s (flipped)**; voltage 7.70 flat |

Standing in `kbalance` on the carpet, balance off: roll -0.8 / pitch -0.5, level -- the carpet
does not make the static stance lopsided.

### Foot lift and stride (estimates)

Forward kinematics of the commanded joint angles in the sim's robot model, body held fixed;
mean over the four paws. Real lift is lower (servo lag, easing, rate limit; the `f` servo
readback returned nothing, so it is unmeasured) and a planted foot sinks into the pile.

| gait | peak foot lift | stride (fore-aft foot travel) |
|---|---|---|
| scripted `wkF` | ~9 mm | ~75 mm |
| V2.1 commanded | 15-21 mm (same on both surfaces) | -- |
| Petoi `carpetF` | ~27 mm | ~36 mm (different rest posture: shoulders mean ~61 vs 47-53, knees ~-11 vs +6) |
| `wkF` all joints x1.6 / x2.0 | ~21 / ~31 mm | ~117 / ~140 mm |
| knees x2.0 | ~23 mm | ~94 mm |
| knees x2.0, shoulders x0.7 | ~26 mm | ~80 mm |
| knees x1.75, shoulders x0.1 | ~25 mm | ~50 mm |

Shoulders mostly set the stride but the knee bend adds some; shrinking the shoulders alone cannot
get below ~63 mm at knees x2.

### What the carpet data says (and does not)

- Every gait tried on this carpet falls or stalls: scripted, V2.1, the lift sweep, `carpetF`.
  More lift alone did not fix it (V2.1's ~17 mm and the x2.0 sweep's ~31 mm both fall).
- Falls are **sideways, toward negative roll (the right)**, with pitch calm, in every run that has a
  log; the user saw the FR shoulder roll over (V2.1) and the BR leg sag (`carpetF`).
- **Not the cause:** battery (7.6-7.8 V, no sag at the early falls), the static stance (level on
  carpet), a fixed 3 s timer (fall time ranged 0.7-3.3 s).
- **The scaled-`wkF` experiments are confounded:** the same light variant falls on hard floor, so
  those variants are unstable by themselves. Only the unmodified gaits give clean evidence about
  carpet (scripted x1.0 and V2.1: fine on hard floor, fall on carpet).
- Candidate explanations, not separated: right-side servo(s) weak under load; payload shifting or
  off-centre on the temporary mount; pile drag at low clearance (backlog H10); the carpet's bounce.

## Oddities (no changes made; user: address later)

- **Front-right leg sags at rest** -- present since first power-on (before the Pi was connected, as
  far as known) and seen again after the IMU calibration. In `kbalance` with balance off the body
  is level, so it is not a servo offset in that pose.
- **Later observation (user, after the IMU `gc`):** the firmware's own step gait no longer falls down;
  it walks sideways a little toward the FR leg, and the FR sag at rest looks better. Nothing was done
  to the servo calibration (no calibration commands were sent); the only BiBoard changes were `XS`,
  `gc` and balance toggles, so `gc` (balance had been chasing a wrong IMU zero) is the likely cause,
  unproven. The sag has come and gone between observations, which argues against a fixed servo offset.
  User plans to re-calibrate the leg with Petoi's procedure; afterwards re-run the level check and walks.
- Right-hand drift; large roll swing; the right side collapsing on carpet (above).
- Firmware gyro balance was miscalibrated until `gc` (below).
- Yaw sign convention vs the real board: positive = right was inferred from run 1 vs observation.

## Bring-up findings from the same day

- **Serial-2:** the BiBoard ignores the Pi's UART until `XS`; `X?` prints the module table (`S=1`).
- **IMU line format:** over the Pi's UART frames end in a TAB, not a newline, and the yaw field is
  the yaw accumulated since the BiBoard booted -- at |yaw| >= 10000 deg (or <= -1000) it fills its
  7-character column and glues onto accel-Z (`10.4017640.5`), which made a whitespace split fail
  ("no parseable IMU frame"). `imu_parse` now falls back to fixed-width slicing; `SerialLink`
  splits IMU frames on tabs.
- **`gc` IMU calibration:** before it, balance-on `kbalance` pushed the FR foot out and tilted the
  body ~19 deg roll / ~11 deg pitch; balance-off was level. After `gc` (the body rocks between front
  and back legs for several seconds while it runs; no reply is printed) balance-on reads 0.8 / -0.8.
  The V2.1 walks are unaffected (balance off).
- **Camera:** works on the Pi; the raw frame is rotated ~90 deg, so the model (trained on upright
  frames) only fired when the user turned their head until the module was rotated upright.
- **Battery:** 7.6-7.8 V throughout (2-cell pack: ~8.4 V full, so roughly half charge).
- `--openloop` now stands G2 for 2 s first, takes `--lift-scale/--lift-joints/--shoulder-scale/
  --ramp-cycles/--volt-every/--log/--openloop-balance-off`, and has the fall guard.

## Sim vs real

- `rl_training/opencat-gym/sysid_replay.py` built its payload with zero rotational inertia (the bug
  fixed in the env on 2026-09-23, `b086208`), so the replayed body could not tilt and every tilt gap it
  printed was just the real tilt. **Fixed 2026-10-01** (spine 61 g + head 15 g as real box inertia,
  collisions off). `sim_vs_real_walk.py` replays logs and prints real vs sim swing/distance/yaw.
- Open-loop replay of the V2.1 hard-floor logs (the logged commands came from a closed loop, so
  4 of 6 replays simply fall over in the sim; trust the other two):
  - distance: sim 1.21-1.24 m vs real ~1.47 m (sim ~16% short);
  - roll std: sim 3.6-4.1 deg vs real 6.6-7.0; pitch std 2.7-2.9 vs 3.5; heading: sim -30..-37 vs real +132 / -15.
- `sysid_replay.py --fit` (actuator `max_force`, `kp`, `kd`, latency): run 1 found no improvement; run 5
  "improved" the rate gap to 0 by driving the tilt gap to 128 deg (a degenerate solution where the sim
  robot falls). **Nothing applied.** Open-loop replay of closed-loop commands cannot pin down the actuator
  model; the script's own advice is to look at friction, CoM and the IMU frame.
- The IMU frame offsets the tool removes: roll ~-1.8..-4.6 deg, pitch ~-2..+3.9 deg between logs.

### Candidate sim changes for the next training run (evidence, not yet applied)

1. **Carpet needs a pile model** (H10): the sim floor is flat with nothing above it to catch a swinging
   foot. Real pile 6.4 mm; commanded V2.1 foot lift 15-21 mm still fails; real clearance is smaller.
2. **Real roll swing is ~1.7x the sim's** (std 6-7 vs ~4 deg): more body-roll disturbance / lateral
   randomization may be warranted.
3. **Heading has no feedback in the real loop** and drifts run to run: consider heading-drift
   randomization (a small constant leg-length/stride asymmetry) in training, or a yaw-hold on the Pi.
4. **Sim travels less than real** for the same commands (~16%): worth a friction / foot-slip check.
5. **IMU bias:** the IMU zero moved ~4 deg in roll between calibrations at rest; training uses +-2 deg
   (`IMU_BIAS_DEG`). One data point, not enough to change the default yet.
6. Re-set the payload model to the measured final build (H2) before the next run.

## Fresh hard-floor baseline on the sturdier mount (2026-10-06)

The case was installed (camera at the front, speaker at the very back, microphone on the lid, G2 about 422 g, 2026-10-06). Six closed-loop
`Release_CandidateV2.1` walks on the same hard floor, `run_gait.py --cmd 0.10 --seconds 12.5`, fall guard on, hands off, G2 put back at the same start
spot between runs (`tools/g2_baseline.sh`, runner `gait/baseline_runs.py`). Logs: `real-walk-data/2026-10-06/`. Fresh, fully charged pack (8.51 V at rest).

| run | roll mean / std (deg) | roll range | pitch std | yaw change at 25 / 50 / 75 / 100 % (deg, + = right) |
|---|---|---|---|---|
| 1 | +0.2 / 5.9 | -13 .. +11 | 2.7 | +35 +85 +130 -108 (wrapped or hand-corrected; ignore the last value) |
| 2 | +0.8 / 5.8 | -11 .. +9 | 1.9 | +35 +72 +111 +150 |
| 3 | +0.8 / 6.2 | -10 .. +10 | 2.4 | +44 +87 +129 +176 |
| 4 | +1.4 / 5.7 | -10 .. +11 | 2.3 | +31 +68 +101 +144 |
| 5 | +1.0 / 5.9 | -10 .. +11 | 2.2 | +34 +69 +101 +136 |
| 6 | +1.3 / 6.0 | -9 .. +10 | 2.5 | +15 +44 +64 +103 |

- **No falls, no stops**; the policy step took about 1.85 ms on average. The user saw a clear drift to the right on every walk; the yaw trace agrees
  (runs 2-6: +103 to +176 deg over 12.7 s, mean about +142, so roughly 8-14 deg/s).
- **Against the temporary mount** (six runs 2026-10-01/02, roll std 6.6-7.0, pitch std about 3.5): roll swing is about 12% lower (5.7-6.2) and pitch swing about
  one third lower (1.9-2.7). The drift to the right is unchanged. The sim's roll std is 3.6-4.1 (open-loop replay), so the roll gap is still about 1.5x.
- **Battery under load:** 9 readings during the walks, 8.07 to 8.45 V (diag event `gait/battery.load`); the pack sat at 8.51 V before and 8.34 V after. So walking
  sags a full pack by about 0.3-0.45 V. The sag on a nearly empty pack is not measured; G2 browned out walking at a resting 7.58 V (2026-10-06, 12:12 AM).
- **Not measured:** distance walked (no tape measure this time) and a weight breakdown (body vs Pi stack) and balance point.

## After replacing the front-left shoulder servo (2026-10-06 afternoon)

The user replaced and recalibrated servo 8 (FL shoulder). Same hard floor, same `run_gait.py --cmd 0.10 --seconds 12.5` walks, `Release_CandidateV2.1`, hands off,
G2 put back at the start spot each run. Pack under load 7.8-8.1 V (not a full charge). Logs: `real-walk-data/2026-10-06b/`. Yaw change over 12.7 s, + = right.

| Series | Runs (deg) | Mean | vs before the swap |
|---|---|---|---|
| Before the swap (six walks, case mounted, 2026-10-06 morning) | +103, +136, +144, +150, +176 (run 1 unusable) | about +142 | |
| After, series A (new yaw sign, deployed 1:17 PM) | +18, +7, +7, +40, +44, +77 | +32 | |
| After, series B (ABBA: the yaw sign alternated, order sealed from the user) | NEW sign: +80, +64, +29, -5 / OLD sign: +15, +46, +37, +49 | NEW +42, OLD +37 | |

- **The drift fell from about +142 to about +35-40 deg per 12.7 s after the servo swap and recalibration.**
- **The yaw-sign fix is not what cured it:** with the pre-fix sign (OLD, `G2_POLICY_YAW_SIGN=+1`) the mean is +37 vs +42 with the corrected sign; within-group spread is about +-27 deg, so a 5 deg gap is noise. (My first reading, that the fix and the swap could not be told apart, was right to be cautious; the interleaved test separates them.)
- **Run-to-run spread is large** (-5 to +80 deg) with no steady trend in series B (series A drifted upward, +18 to +77, which did not repeat). The user's eye and the IMU agree: runs called "super straight" were +29 and -5; runs called "curved" were +37 and more. Roll std 4.9-5.4 deg and pitch std 2.3-2.7 are unchanged from before the swap.
- Distances (user, series A): 4 ft 11 in, 4 ft 10 in, 4 ft 12 in for the first three (the rest curved and were not measured).
- Series A early runs looked like the policy visibly steering back on course; the ABBA test shows that is not a sign effect.
- **Conclusion:** the old servo 8 fault caused most (about 100 of the ~140 deg) of the drift. About +40 deg +- 27 remains, which is consistent with V2.1's small learned
  asymmetry (the open lever in `v3-retrain-plan.md`). The direct servo readings (`servo_static_test.py`, `servo_step_test.py`) on the new servo are the next step.
- Tooling added for this: `baseline_runs.py --yaw-sign {-1|+1|abba}` and `G2_POLICY_YAW_SIGN` (A/B tests only; the default is -1), logged in each CSV header.

## Why V2.1 drifts right (investigation, 2026-10-06)

> **Update (afternoon):** the servo swap above removed about 100 of the 140 deg, so the drift was mostly the faulty servo 8. The analysis below (yaw sign, learned asymmetry,
> sim servo-speed limit) is still the record of what was ruled out and what remains open for the residual +40 deg.

The six walks above all turned about +142 deg right in 12.7 s. This section is the record of what was tested and what it shows; the plan
built on it is [`v3-retrain-plan.md`](v3-retrain-plan.md). Raw results and the exact commands: [`v3-data/`](v3-data/README.md).

**Ruled out: the Pi's yaw sign.**
- The firmware stream reports + yaw for a right turn (confirmed with `kvtF` on 10-02, below). PyBullet, where the policy was trained,
  reports + yaw for a left turn. `run_gait.py` fed the rebased yaw into the policy unflipped from `79da931` (2026-09-23) until 2026-10-06,
  so the policy's heading input on G2 had the wrong sign.
- In the sim, V2.1 drifts the same however heading is fed (`drift_probe.py --lever yawflip|yawzero`, 422 g, 24 x 12.5 s). Mean heading
  change: normal +9.4 deg, negated +8.4, always 0 +9.1; 0 falls in all three; joint means equal to 0.1 deg. **V2.1 doesn't use heading**,
  so the sign couldn't cause the turn.
- Offline replay of these six walks through the ONNX policy (`replay_real_obs.py`) reproduces 100% of the logged joint commands, so the Pi
  ran V2.1 exactly. Negating yaw moves the commands only 1-4 deg, and only once G2 is already far off course.
- Why V2.1 ignores heading:
  - Training episodes are 3.1 s, so heading error barely builds up.
  - Nothing pushed it off course in training.
  - Heading is only available inside the orientation quaternion.
  - The quadratic heading penalty is nearly flat near straight.
- **Fixed anyway on 2026-10-06** (`run_gait.POLICY_YAW_SIGN`, `c292431`): any policy that does learn heading would otherwise steer the wrong
  way. Logs keep the firmware convention (+ = right).

**What causes it, as far as the data goes: an asymmetry V2.1 learned in the sim.**
- The scripted walk is left/right symmetric: mean URDF deg `[46.9 6.0 46.9 6.0 53.0 8.2 53.0 8.2]` (FLsh FLel FRsh FRel BRhip BRkn BLhip
  BLkn). Mirrored and shifted half a cycle it matches itself to within 4.2 deg.
- V2.1 holds a fixed asymmetry, BL hip about 60 deg vs BR about 53, in the sim (`[49.1 2.4 48.0 1.3 53.8 2.6 60.2 3.8]`) and on G2 (these six
  walks: `[47.2 5.3 49.2 3.1 52.9 1.0 60.1 4.8]`).
- The scripted walk curves **left**, both in the sim (`hw1-log.md` Round 4, called a solver artifact there) and on G2 (open-loop, 10-01
  table above). V2.1 learned a constant correction against that pull. In the sim it nets a slight left turn (+9 deg / 12.5 s); on G2's real
  floor the same correction steers far harder (about 140 deg right).
- Consistent with:
  - G2 turns at full rate from the first second (run 2: +35 / +72 / +111 / +150 deg at 25/50/75/100%), before any heading error exists.
  - An open-loop sim replay of these commands also turns right (-30..-37 deg, "Sim vs real" above).
  - The sim travels about 16% short on the same commands, so its foot contact differs.
  - `hw1-log.md` Round 4 warned that countering a sim bias could produce the opposite bias on real hardware.
- **Status: leading hypothesis, not yet confirmed.** The check is the V3 plan's Phase 1: a sim whose contact/friction is calibrated to G2
  should turn V2.1 right as well. The fix in V3 is structural: a left/right mirror-symmetry loss in training, so a one-sided bias can only
  be corrected through feedback.
- **Servo 8 (FL shoulder) is not ruled out, and its fault is not confirmed.** The scripted walk drives it above its ~42 deg sticking point
  63% of each cycle and still curved left. The user is replacing it, then these six walks get repeated.

**Update 2026-10-06 (afternoon): the sim's servo-speed limit is the dominant sim-vs-G2 gap, and it hides the right turn.** The first version of this
section used `drift_probe.py`, which did not force the commanded speed (the env redrew the command ~9 times per 1000 steps), so its speeds were too
low and its "V2.1 slows down on long walks" reading was wrong. Re-measured with a forced command (`benchmark_v4.py`, V2.1, 422 g, the 12.5 s calm
walk "N1", 20 episodes; raw results in [`v3-data/`](v3-data/README.md)):

| Sim servo speed limit (deg/s) | Falls | Speed (m/s) | Heading change over 12.5 s | Roll std | Pitch std |
|---|---|---|---|---|---|
| 90 | 0% | 0.067 | +7.3 (left) | 2.26 | 1.44 |
| **137 (what V2/V2.1 and the V3 profile assume)** | 0% | 0.089 | **+9.3 (left)** | **2.64** | 1.70 |
| 180 | 0% | 0.091 | +1.8 | 3.83 | 2.27 |
| 250 (the firmware's own `i` easing) | 10% | 0.086 | **-10.8 (right)** | **5.92** | 3.97 |
| 400 | 10% | 0.081 | -15.8 | 6.68 | 4.89 |
| none | 5% | 0.081 | -23.3 | 6.51 | 4.77 |
| **G2 (six walks)** | 0 / 6 | ~0.118 (10-01 taped) | **-142 (right)** | **5.7-6.2** | 1.9-2.7 |

- Raising the limit from 137 to 250 deg/s moves the sim's roll swing onto G2's and turns V2.1 **right** for the first time. The 137 figure
  was borrowed from another project (never measured on G2), and the firmware's own easing is already 250 deg/s, so the extra limit probably
  over-damps the sim's legs. This is the first thing Phase 0 / Phase 1 of the V3 plan measures (`tools/servo_step_test.py`).
- The sim still does not reach -142 deg, its pitch swing overshoots at 250 (3.97 vs 1.9-2.7), and it falls 10% where G2 fell 0 / 6; other
  parameters (foot contact, motor strength) are still to calibrate.
- Speed with a forced command: sim 0.089 vs G2 ~0.118 (about 25% short, not half as first reported); no slow-down over 12.5 s (0.09 early vs
  0.09 late). The command path doesn't explain the gap: sending every tick gives 0.089, an ideal path 0.083. The old 377 g payload gives the same
  as the 422 g one (0.090).
- Not yet reproduced by the sim: G2's turn rate from the first second (the sim's yaw rate at 250 deg/s is much smaller than -11 deg/s).

### Stationary yaw drift, 2026-10-07 12:51 AM (is the firmware yaw a usable heading?)

`pi_pipeline/gait/yaw_drift_check.py --seconds 60` with G2 resting (`d`, servos off, balance off, untouched), 5 Hz IMU print, charged pack. Raw log: `v3-data/yaw_drift/yaw_drift_rest_01.csv`.

- The firmware's accumulated yaw jumped by exactly -360 deg twice in 60 s (at 11.0 s and 41.8 s) with nothing moving. Walking logs wrap the yaw with `math.remainder`, so exact 360 jumps do not reach the controller.
- With the jumps removed the yaw drifts **+0.14 deg/s** at rest (+7.5 deg over the last 55 s; the first 5 s show +5.5 deg as the legs settle after `d`). Scatter about the line 0.3 deg.
- Against the walking drift at u = 0 (about 9.6 deg/s in the 2026-10-07 `recheck2` runs) that bias is about 1.5%: it adds roughly 2 deg to a 12.5 s walk, so a gyro bias at rest does **not** explain a disagreement between the log and what is seen on the floor. This does not test the yaw while walking (roll swing of about 5 deg at every stride could still leak into it).

### Sim steering sweep, 2026-10-07 (does the sim steer the way G2 does?)

`steer_probe.py` on V2.1: a fixed stride difference u (left legs scaled by 1 - u, right legs by 1 + u, so u > 0 = longer RIGHT strides), 12 episodes of 12.5 s per value, both payload models. Raw output: `v3-data/steer_sweep/`. Heading change in degrees, sim sign + = left:

| u (probe) | -0.30 | -0.20 | -0.10 | 0 | +0.10 | +0.20 | +0.30 |
|---|---|---|---|---|---|---|---|
| new payload (`case2`) | +32 (6/12 fell) | +35 | +17 | -2 | -16 | -29 | -47 |
| old payload (`case`) | +20 (6/12 fell) | +27 | +18 | -3 | -21 | -32 | -42 |

- **The sign is still opposite to G2's.** In the sim longer right strides turn the robot RIGHT; on G2 they turn it LEFT (u = -0.20 in the G2 convention, which is longer right strides, took +90 deg to +1 deg of right drift). The payload model does not change this.
- **The sim's steering is 3 to 4 times weaker**: about 10-12 deg/s per unit u against about 40 deg/s per unit on G2 (the G2 figure from the 2026-10-07 `recheck2` runs: u = 0 drifts +9.6 deg/s, u = -0.20 about +1.3 deg/s).
- Falls rise at |u| = 0.30 on the longer-left-strides side (6 of 12) in both models.
- Consequence: a policy trained to steer in this sim learns a lever that points the wrong way on G2, so learned in-policy steering cannot be trusted on hardware until the sim's steering sign and strength are understood. The measured Pi-side lever stays the steering path. A cause for the sign difference is not found; candidates are foot-ground contact and how the real legs slip on the hardwood, which the sim models as a fixed friction.

### Hip angle offset: scripted `wkF` vs V2.1, sim and G2 (2026-10-07)

Mean commanded joint angle over a calm walk, degrees, URDF joint order (the sim's N1 cell, 30 episodes of 12.5 s; G2 from the `recheck2` run 1 log at u = 0, after the first second; the scripted walk from `reference_gait/wkf_ref.npy`):

| | FL sh | FR sh | BR hip | BL hip | BL - BR hip | BR kn | BL kn |
|---|---|---|---|---|---|---|---|
| scripted `wkF` | 46.9 | 46.9 | 53.0 | 53.0 | 0.0 | 8.2 | 8.2 |
| V2.1 in the sim, old payload | 49.5 | 50.1 | 54.6 | 61.6 | +7.0 | 0.3 | 4.1 |
| V2.1 in the sim, new payload | 49.3 | 50.3 | 54.5 | 61.6 | +7.2 | -0.3 | 3.9 |
| V2.1 on G2, u = 0 | 49.6 | 49.3 | 54.2 | 60.4 | +6.2 | 0.4 | 4.8 |

- The scripted walk is exactly left/right symmetric. V2.1 holds the back-left hip about 7 degrees above the scripted value and the back-right hip only about 1 degree above it, a 6-7 degree one-sided offset that is the same in the sim and on G2 (same policy, similar inputs). With steering (u = -0.20) the hips read 55.4 and 58.4, because the stride scaling pulls the left hip in.
- This is the learned asymmetry the leading drift hypothesis names. It confirms the policy adds a one-sided offset the scripted walk does not have; it does not show that the offset causes G2's right drift. That needs the scripted-versus-V2.1 comparison on G2 (six open-loop `wkF` walks against six V2.1 walks in one session), which is still undone.

### Scripted `wkF` open-loop playback was slow and made the BiBoard click (2026-10-07), fixed

First scripted runs of the postcal batch (hardwood, pack 7.96 V): the scripted walk took 22.8 s for 10 cycles (a 12.5 s walk at 80 Hz), the user heard constant rapid clicking from the board (not the motors) the whole run, on both scripted runs and on neither V2.1 run (`~/g2_logs/postcal4/`, raw). Causes found in `run_gait.openloop`: it slept `dt` after each frame's work (a serial send blocks about 5 ms at 115200 baud), so frames ran at about 44 Hz, and it sent a joint command on every frame (about 44 per second) where the policy loop sends every 3rd tick (i@27). Fix: deadline pacing and `send_every=3` (CLI default for `--openloop`; `--send-every 1` restores the old cadence). After the fix one scripted run: normal speed, no clicking (user). So the faster command stream (and/or its uneven timing) is what makes the board click; V2.1's 27 Hz stream never did.

### Scripted `wkF` against V2.1, interleaved, hardwood, after the user's joint calibration (2026-10-07 8:13 AM, `postcal5`)

Twelve walks in one batch (`g2_baseline.sh start 12 postcal5 --scripted-mix abab`), pack about 7.9 V: odd runs the scripted open-loop `wkF` walk (10 cycles, 12.5 s, the fixed pacing), even runs V2.1 at u = 0 (no heading hold). Net yaw over the walk, degrees, right positive, firmware yaw. Raw logs: `real-walk-data/2026-10-07/`.

| Pair | scripted | V2.1 next | V2.1 minus scripted |
|---|---|---|---|
| 1-2 | +34 | +65 | +30 |
| 3-4 | +20 | +99 | +79 |
| 5-6 | +62 | +117 | +56 |
| 7-8 | +88 | +113 | +25 |
| 9-10 | +97 | +118 | +21 |
| 11-12 | +86 (raw -274: the firmware's yaw counter jumped by exactly -360 mid-walk; the scripted logs are not wrapped) | +153 | +66 |

- Scripted mean +64 deg (about +5 deg/s), V2.1 mean +111 deg (about +8.7 deg/s). V2.1 is more to the right than the scripted walk in all six pairs, by about 46 deg per 12.5 s (+3.7 deg/s, range +21 to +79).
- **The scripted walk is NOT straight on this floor**: it drifts right too. The early observation that it curves left (one qualitative open-loop test before the servo swap and the case) did not reproduce. Most of G2's right drift (about 5 of 8.7 deg/s) is in the hardware, floor or calibration; the policy adds about 40% on top.
- Both walks drift more as the session goes on (scripted +2.7 deg/s in the first run, +7 to +8 in runs 7-11; V2.1 +5 to +12): something that changes over time (servo temperature, pack voltage 7.96 V at the start, wear in) moves the drift by a factor of 2-3 within 15 minutes.
- Roll swing: scripted 4.3 deg sd, V2.1 5.6.

### IMU after the gyro calibration (2026-10-07, about 9:30 AM)

`gc` run through the Pi with G2 standing level and untouched (`yaw_drift_check.py`, raw logs in `real-walk-data/2026-10-07/imu/`). Firmware balance off for every reading.

| | before `gc` | after `gc` |
|---|---|---|
| yaw drift at rest, 60 s | +0.14 deg/s (scatter 0.3 deg) | 0.000 deg/s (scatter 0.05 deg) |
| rest pose mean roll / pitch | +0.59 / -1.22 deg | +0.24 / +1.69 deg |
| standing (`kbalance`, then `gb`), 40 s, 185 frames | not measured | roll -0.69 deg, pitch -0.07 deg (zero error); sd 0.09 / 0.08 deg; yaw 0.00 deg/s |
| IMU frame interval | | median 0.202 s (4.96 Hz) |

- A first standing run read pitch sd 5.5 deg and a -4 deg mean: the user rested G2 during it; discarded. The standing order matters: `kbalance` can switch the firmware balance back on, so `gb` goes after it (`yaw_drift_check.py --stand` does that now).
- Sim settings set from this: IMU roll/pitch zero error +-0.7 deg (was +-2), IMU noise 0.001 in the quaternion (was 0.02; the real sensor noise is about 0.09 deg = 0.0008), hold 16 steps unchanged (5 Hz). Everything not yet run uses them; earlier runs and the replicate set in the queue keep the old values (`g2_profile.IMU_WORLD_A`).

### More stride-difference authority, hardwood, after the gyro calibration (2026-10-07 8:45 AM, `auth2`)

`g2_baseline.sh start 12 auth2 --const-u=0,-0.20,-0.30 --hold-umax 0.30` (interleaved order 0, -0.20, -0.30, -0.30, -0.20, 0, ...; pack 7.86 V; fixed u, no feedback; u < 0 = longer right strides = a left turn). Net yaw over 12.5 s, right positive. Raw logs `real-walk-data/2026-10-07/auth2_*`.

| u (applied) | runs | net yaw per run | mean | sd |
|---|---|---|---|---|
| 0 | 1, 6, 7, 12 | +111, +108, +98, +64 | +95 deg (+7.6 deg/s) | 19 |
| -0.20 (-0.19) | 2, 5, 8, 11 | +14, -27, -17, -48 | -20 deg (-1.6 deg/s) | 22 |
| -0.30 (-0.28) | 3, 4, 9, 10 | -56, -24, -31, -65 | -44 deg (-3.5 deg/s) | 17 |

- **The lever still works, and the signs are right**: more negative u turns G2 further left. No falls at -0.30; the back-right foot landing flat was not reported (the user did not track the runs).
- **Authority flattens beyond -0.2**: from 0 to -0.19 the turn changes by -9.2 deg/s (about 48 deg/s per unit of u), from -0.19 to -0.28 by only -2 deg/s (about 22 deg/s per unit): the joint-range clamp (`heading_hold.JOINT_RANGE_DEG`) limits the stride change. So raising the limit from 0.20 to 0.30 buys about 2 more deg/s of left turn.
- **The cancel point is about u = -0.16** now (drift +7.6 deg/s); the old estimate was -0.19 at +3.3 deg/s... the drift at u = 0 is about 2x what it was after the servo swap. The u = 0 runs did not keep rising this time (111, 108, 98, 64).
- **Run-to-run spread at a fixed u is about 17-22 deg per 12.5 s** (+-1.5 deg/s), so a fixed correction lands anywhere in a 40 deg band; only feedback can narrow it.

### Closed-loop heading hold works: six straight runs (2026-10-07 8:56 AM, `hold1`)

`g2_baseline.sh start 6 hold1 --hold on --hold-ff=-0.16 --hold-kp 0.01 --hold-ki 0.001 --hold-umax 0.30` on the hardwood after the gyro calibration (pack 7.82 V; V2.1 with the Pi-side stride-difference hold; the hold's target is the heading at the start of each walk). Raw logs `real-walk-data/2026-10-07/hold1_*`.

| run | final yaw (right +) | u mean | u range |
|---|---|---|---|
| 1 | -5.6 | -0.14 | -0.24 .. 0.00 |
| 2 | -3.3 | -0.12 | -0.23 .. 0.00 |
| 3 | -3.1 | -0.15 | -0.25 .. 0.00 |
| 4 | -1.1 | -0.15 | -0.23 .. 0.00 |
| 5 | -2.4 | -0.14 | -0.26 .. 0.00 |
| 6 | -2.2 | -0.11 | -0.22 .. 0.00 |

- Final heading mean -3.0 deg, sd 1.4 deg, every run within 6 deg of straight (the same walks with a fixed u had a 40 deg band, +111 to -65). The user saw slight left curves in most runs, none to the right, and called run 6 the straightest in a while: matches the log.
- The output never reached its 0.30 limit (peak -0.26) and settled near -0.14, so the loop is not authority-limited at today's drift (+7.6 deg/s at u = 0). The slight left bias (-3 deg) says the -0.16 feed-forward is a touch strong; about -0.14 would center it.
- Caveats: six runs, one session, 12.5 s walks, one pack level; the drift has moved 2-3x within a session before.
- Meaning: the drift is correctable outside the policy with the lever measured on G2, with the yaw calibrated. Not yet the default: `--heading-hold` is off unless asked.

## Not done / not measured

- Servo position feedback (`f` returns only an echo), real foot lift, per-leg load.
- Hard-floor controls for the lift/stride variants (see "Where we left off").
- A hands-off run in a longer space; V2.1 carpet repeats with the fall guard.

## Servo feedback tests, 2026-10-02 (after the user re-calibrated the limbs)

User symptoms: some lag in the FR shoulder at rest, and the firmware step gait (`vtF`) moves G2 laterally
to the right. Tools: `tools/servo_response_test.py`, `tools/servo_static_test.py` (data in
`real-walk-data/2026-10-02/`). **Servo position feedback works over the BiBoard's USB** (`f` starts a
~5 rows/s stream of 8 values = servos 8..15; any new command stops it, so restart it with `f`); over the
Pi's UART `f` returned only an echo.

- **Leg mapping confirmed by eye:** servos 8, 9, 10, 11 move FL, FR, BR, BL (the code's labels are right).
- **At rest (relaxed):** shoulders left-right within 1 deg; FL knee ~6 deg less flexed than the other three.
- **Standing on the floor, every joint commanded to the stand pose (shoulders 50, knees 0), 5 repeats:**
  FL shoulder stays ~42 (8 deg low); FR/BR/BL shoulders 49-50; rear knees ~20 deg short of 0 (BR -21..-24,
  BL -14..-22), FR knee drifts -3 -> -11, FL knee -1..-4. Not a timing effect.
- **Unloaded (G2 held off the ground), per-joint staircase:** all four knees track perfectly (gain 0.96-0.98,
  offset ~0), so the rear-knee droop and erratic FL knee are load-dependent (torque or supply; battery was
  ~7.6-7.8 V, roughly half charge -- a full-battery rerun is still to do).
- **FL shoulder (servo 8) is the real anomaly:** unloaded it follows some commands but intermittently sticks at
  ~42 deg and will not go higher, even when commanded to 65; steady while stuck (no hunting). Sequence read
  35->35, 45->44, 50->42, 55->47, 50->49, 65->42, 50->42, 40->40, 50->49. The stand angle (50) is the centre of
  every gait run so far, so this leg's shoulder has probably sat ~8 deg low and had its swing clipped in all of
  the walks logged. Suspects: slipping/stripped gear, slipped horn or screw, mechanical jam, cable/connector.
- **FR shoulder (servo 9):** read -3.5 / -15 at commands 35 / 65 in one unloaded run but tracked perfectly
  (34-35, 48-50, 63) when repeated; treated as a one-off glitch, still on the watch list.
- Next: swap servos 8 and 9 (or their cables) and rerun `servo_static_test.py` to see whether the fault follows
  the servo; hand-check the FL shoulder; full-battery rerun; then the gait A/B (`vtF` vs `kwkF`/`kcrF`).

### Firmware step gait (`kvtF`), 2026-10-02, hard floor, untethered, balance on, 6 s

Stayed up; roll +2.3 / std 1.4 (range 0..+5), pitch -1.2 / 1.2, yaw -29 deg (25/50/75/100%: -11 -15 -23 -29).
User: "step gait looked good this time", drifted slightly **left** (~1 inch) instead of right. This agrees with
the log (negative yaw = left) and confirms the yaw sign for the firmware IMU stream. The earlier lateral-right
movement in the step gait (before the `gc` IMU calibration and the limb recalibration) is gone. The
balance-off `vtF`, `kwkF` and `kcrF` comparisons were not run. The rest-pose symptom is unchanged: the pose is right
when it first drops to rest and the FR shoulder visibly lags/sags *after* the servos relax.

## Firmware turn rates, 2026-10-06 (V3 Phase 0 step 3)

`tools/g2_turns.sh start 6` (kbalance stand, then the firmware skill for 10 s, IMU logged, hard floor; raw CSVs in `v3-data/turns/`).
Yaw rate is a least-squares line through the unwrapped IMU yaw (firmware convention, + = right):

| Skill | Runs (deg/s) | Mean |
|---|---|---|
| `kwkL` | -10.9, -13.4, -12.1 | -12.1 |
| `kwkR` | +18.7, +18.1, +19.0 | +18.6 |

Right turns are about 50% faster than left, repeatably (spread about 1 deg/s per side): a steady rightward bias of about 3 deg/s, the same size as V2.1's
right drift, in a scripted firmware gait with no policy running. The bias belongs to G2's body / servos, not to the learned gait.

**Turning gate (plan Phase 1): fails.** `turn_gate_probe.py` runs the calibrated sim open-loop (zero residual, `TURN_BLEND`, payload on, 4 episodes per
direction, nominal cadence): sim `wkL` -0.8 deg/s and `wkR` +0.5 deg/s, i.e. 7% and 3% of the real rates (gate: 50%). The blended pose is applied
(left-leg swing about 1/3 of wkF's) and G2 walks 0.48 m in 10 s, but the sim body hardly yaws where the real one turns 120-190 degrees. So Y4 (turn
curriculum), Y6 and the S5 screen stay off (`trained/v3_turning_gate_pass` not created); turns stay firmware tokens and straightness rests on the
mirror loss plus heading feedback.

## Pi-side heading hold A/B, 2026-10-06 (V3 Phase 0)

`tools/g2_baseline.sh start 16 hold_v21 --hold abba` (V2.1, 0.10 m/s, 12.5 s, hard floor, pack charged; hold off, on, on, off, off, on, on, off ...; raw logs in
`v3-data/hold_ab/`; filenames carry the condition). Heading change over the walk, firmware convention (+ = right):

| Hold | n | Mean | Sd | Range | Roll std |
|---|---|---|---|---|---|
| OFF | 8 | +65 deg | 18 | +43 .. +100 | 5.6 deg |
| ON | 8 | +82 deg | 19 | +57 .. +115 | 4.1 deg |

The hold did **not** reduce the drift: ON turned about 17 degrees MORE to the right (difference of means 17 deg, standard error about 9, so suggestive, not
conclusive). The controller output was pinned at its limit (u = -0.20, longer left strides) for the whole of every ON run, so it asked for the most correction it
can give and the heading still went right. Either the stride-scaling lever has the opposite sign on the real G2 from the sim (`steer_probe.py`: u = -0.2 -> +27 deg left),
or it has far less authority there (the policy sees the changed joint history and may undo it). The roll std fell from 5.6 to 4.1 deg with the hold on, so the lever
does change the walk. Drift also grew over the series (OFF runs: 43, 49, 46, 66, 69, 85, 100, 66 deg), which the alternating order balances across the two conditions.
Next: measure the real authority and sign directly with constant u (no feedback), e.g. u = -0.2 / 0 / +0.2, a few runs each.

### The stride-difference lever has the opposite sign on G2 from the sim (2026-10-06, fixed-u walks)

**Longer RIGHT strides turn G2 LEFT** (as with a vehicle whose right wheel runs faster). The sim (`steer_probe.py`) and the first version of `heading_hold.py`
had it the other way round, so the hold in the A/B above steered into the drift. Fixed-u walks (`g2_baseline.sh start 12 const_u --const-u=-0.2,0,0.2`, u as defined
before the fix: u > 0 = longer right strides; no feedback; order -0.2, 0, +0.2, +0.2, 0, -0.2 ...; raw logs in `v3-data/const_u/`), heading change over 12.5 s,
right-positive:

| u | n | Mean | Sd | Runs |
|---|---|---|---|---|
| -0.20 (longer LEFT strides) | 4 | +114.5 deg | 3.0 | 118, 114, 117, 110 |
| 0 | 4 | +90.0 deg | 13.6 | 68, 91, 106, 95 |
| +0.20 (longer RIGHT strides) | 4 | -29.2 deg | 11.0 | -47, -30, -20, -20 |

- **Authority is large:** u = +0.2 swings the walk by about 120 deg (about 10 deg/s) from the u = 0 drift, more than enough to cancel it. The response is not linear: from
  0 to +0.2 it is about -600 deg per unit u, from -0.2 to 0 only about -120. The zero crossing of the drift is near u = +0.15 in the old sign (-0.15 in the
  corrected sign, where u > 0 = longer LEFT strides = a right turn).
- **The drift itself grew through the evening** (u = 0 runs: +44 deg in the first pilot run, +65 mean over the A/B, +90 here), so a fixed offset is not enough
  and the feedback (integral) term is needed on top of any feed-forward.
- **Fix:** `heading_hold.apply_stride_difference` now scales the left swing by (1 + u) and the right by (1 - u), so the controller's own logic is unchanged (a
  rightward error gives a negative u, which is longer right strides, a left turn). The unit tests pin the sign. Anything written from the sim's `steer_probe`
  about this lever's direction is wrong for the real G2.
- **Open:** the sim's steering sign is opposite to the real one. Until that is understood (a left/right leg mapping in the sim, or foot slip), do not use the sim to tune
  anything that steers by stride length.

### Dial-in round 1: fixed stride difference near the cancel point (2026-10-06 8:16-8:25 PM, corrected sign: u < 0 = longer RIGHT strides = a left turn)

`g2_baseline.sh start 12 dial1 --const-u=-0.10,-0.15,-0.20` (no feedback; raw logs `v3-data/dial1/`), heading change over 12.5 s, right-positive:

| u | n | Mean | Sd | Runs (in run order) |
|---|---|---|---|---|
| -0.10 | 4 | +64 deg | 18 | 43, 62, 59, 93 |
| -0.15 | 4 | +11 deg | 24 | -19, -5, 33, 37 |
| -0.20 | 4 | +1 deg | 11 | -9, -7, 19, 3 |

Straight walking needs u of about -0.19 (linear interpolation), at the old +-0.20 limit, so there is no headroom: the drift crept up through the series (within each u the later
runs turn further right, about +30 deg over ten minutes), which a fixed offset cannot follow. The feedback needs more authority than +-0.20 (untested beyond it).
