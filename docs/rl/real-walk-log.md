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
  because the user steered them back; hands-off run 6 drifted +16 deg. The loop discards the IMU
  yaw, so nothing holds a heading.
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

## Not done / not measured

- Servo position feedback (`f` returns only an echo), real foot lift, per-leg load.
- Hard-floor controls for the lift/stride variants (see "Where we left off").
- A hands-off run in a longer space; V2.1 carpet repeats with the fall guard.
