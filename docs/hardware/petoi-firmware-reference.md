# Petoi / OpenCat firmware reference

Confirmed from `PetoiCamp/OpenCatEsp32` source (2026-09-07, IMU serial
protocol + line format re-verified against `main` again 2026-09-20), the
BiBoard/ESP32 firmware that runs on G2 (Bittle X). Captured so the
knowledge isn't lost between sessions. Verify against the repo if firmware
has moved on.

## Repositories

| repo | what |
|---|---|
| `PetoiCamp/OpenCatEsp32` (aka `OpenCatEsp32-Quadruped-Robot`) | **BiBoard/ESP32 firmware — this is G2's.** |
| `PetoiCamp/OpenCat` | NyBoard/AVR firmware (older boards) |
| `PetoiCamp/OpenCat-Old` | legacy |

`OpenCatEsp32/src/`: `src.ino` (serial parser / main loop), `imu.h` + `mpu6050/`
(IMU fusion + exception detection), `reaction.h` (`dealWithExceptions()` — auto
recovery), `skill.h` (skill runtime — a copy is vendored at
`rl_training/opencat-gym/reference_gait/skill.h`), `InstinctBittleESP.h` (keyframe
data — vendored), `OpenCat.h` (token macros + config constants).

**No official Petoi RL/sim repo.** Petoi points to community work: `ger01d/opencat-gym`
(the lineage of `rl_training/opencat-gym`) and `ger01d/opencat-gym-sim2real`, plus
forum MuJoCo/Isaac efforts. Our fork is already the canonical community base.

## Serial command tokens (`OpenCat.h` `T_*` macros)

Newline-terminated ASCII over UART. Confirmed set:

| token | name | meaning |
|---|---|---|
| `k<skill>` | `T_SKILL` | run a named skill — `kwkF`, `ksit`, `kbalance`, `kcrF`, `ktrF` |
| `m<idx> <deg> …` | `T_INDEXED_SIMULTANEOUS_ASC` | move joint(s), chainable — `m0 30 8 -35` |
| `b<tone> <ms> …` | `T_BEEP` | buzzer melody |
| `d` | `T_REST` | rest posture, servos off (ends a looping gait) |
| `P` | `T_POWER` | **print battery voltage** ← the query the link README couldn't find |
| `j` / `j <idx>` | `T_JOINTS` | **return all joint angles / one joint** |
| `f` | `T_SERVO_FEEDBACK` | servo position feedback (if the servo chip supports it) |
| `g` | `T_GYRO` | gyro function toggle (bare `g`) |
| `gU` / `gu` | `C_GYRO_UPDATE` / `_OFF` | continuous gyro data update on/off (already **on by default from boot** — `updateGyroQ = true` is set during IMU init, so `gU` is rarely needed just to get data flowing) |
| `gB` / `gb` | `C_GYRO_BALANCE` / `_OFF` | turn gyro balancing on/off |
| `gc` | `C_GYRO_CALIBRATE` | calibrate the IMU |
| `gP` | `C_PRINT` (in the `g`-context) | **start CONTINUOUS 6-axis print** — sets `printGyroQ = true`, which is what actually makes `readEnvironment()` call `print6Axis()` every loop |
| `gp` | `C_PRINT_OFF` | stop it — **NOT symmetric with `gP`**, this is "print once then stop", not a toggle; sending `gP` twice does not turn it off |
| `p` | `T_PAUSE` | pause |
| `t` | `T_TILT` | tilt command |
| `c` / `cd` | calibration / factory | **never send from the pipeline** |

**CONFIRMED 2026-09-20, corrects the previous entry here:** `v`/`V` are still
not a real token at all (grepped current `main` source directly — no match
anywhere in the command parser), and `pi_pipeline/gait/run_gait.py` /
`sysid_collect.py` were both sending it until this date, which would have
been silently ignored by the board and produced *zero* streamed IMU data —
`--probe-imu` would have hit a dead loop-timeout at first real bring-up.
Fixed in both files to send `gP`/`gp` instead, matching the actual
`T_GYRO`+`C_PRINT` mechanism traced above. `python -m pi_pipeline.gait.run_gait
--probe-imu` still needs to run against the real board to confirm this against
actual hardware (nothing above has touched a real BiBoard) — that's step 13a
of the bring-up sequence.

## IMU

- BiBoard V1 compiles support for **both MPU6050 and ICM42670** and picks
  whichever chip is physically present at runtime (`OpenCat.h` defines both
  `IMU_MPU6050` and `IMU_ICM42670` for `BiBoard_V1_0`) — don't assume MPU6050
  without checking which prefix (`MCU:` vs `ICM:`) the real board actually
  sends (see the confirmed line format below).
- DMP quaternion fusion (no hand-tuned complementary filter).
- `IMU_PERIOD 5` ms → **200 Hz** sample loop. `IMU_SKIP 1`, `IMU_SKIP_MORE 23`
  for frame-skip during motion.
- Orientation as YPR (yaw/pitch/roll ≈ body z/y/x).
- Balance hooks: `RollPitchDeviation[2]`, `balanceSlope[2] = {1, 1}`, `gyroBalanceQ`.
  Exact balance `KP/KI/KD` gains not yet pulled — TODO if the deployment balance
  loop needs matching.

### Confirmed serial line format (`imu.h` `print6Axis()`, 2026-09-20)

The function actually wired into the main loop (via `readEnvironment()`) —
**not** the similarly-named but dead `print6AxisMacro()`, which is unused
and would have been the wrong thing to match against:

```
MCU:<ax><ay><az><yaw><pitch><roll>      # MPU6050
ICM:<ax><ay><az><yaw><pitch><roll>      # ICM42670
```

`snprintf(..., "MCU:%6.2f%6.2f%6.2f%7.1f%7.1f%7.1f", ax, ay, az, -yaw, pitch, roll)`
— fixed-width, no explicit delimiter (padding makes it whitespace-safe in
practice), accel in g, angles in degrees, **yaw printed negated**.
`PRINT_ACCELERATION` is unconditionally defined in current firmware, so the
accel triplet is always present — there is no gyro-only variant.

**Open gap, not yet resolved:** this line carries acceleration, not
angular velocity. The firmware's raw-gyro print path exists in source but
is dead code (commented out in `print6AxisMacro()`, which isn't even
called) — no true gyro/angular-rate is available over stock-firmware
serial at all. `pi_pipeline/gait/residual_policy.py`'s `ResidualGaitPolicy`
needs real roll/pitch angular velocity as an observation input, which this
stream cannot supply. `parse_imu_line()` in `run_gait.py` deliberately
returns zero rather than smuggling accel into the gyro slot. Needs a real
decision before the policy loop is trustworthy on hardware: finite-differencing
consecutive `ypr` samples in the Python control loop (the policy's own
training observations already rely on a finite-diff angular-accel channel,
so there's precedent), or revisiting the no-firmware-fork decision
(`docs/project-plan.md`, 2026-09-10) for just a gyro-print re-enable.

### Exception detection (`imu.h` `getImuException()`)

| exception | trigger |
|---|---|
| `IMU_EXCEPTION_FLIPPED` (-1) | `fabs(ypr[roll]) > 85°` **and** accel-Z near/below 0 |
| `IMU_EXCEPTION_LIFTED` (-2) | `pitch < -50°` or `pitch > 75°` |
| `IMU_EXCEPTION_KNOCKED` (-3) | Z-axis accel shock vs previous frame |
| `IMU_EXCEPTION_PUSHED` (-4) | X/Y accel shock ≈ 4.9 g (X) / 7.3 g (Y) |
| `IMU_EXCEPTION_FREEFALL` (-6) | — |
| `IMU_EXCEPTION_TURNING` (-7) | — |

`gFactor = GRAVITY / 8192 ≈ 0.00122`.

### Self-right auto-trigger (`reaction.h` `dealWithExceptions()`)

```c
if (gyroBalanceQ) {
  ...
  case IMU_EXCEPTION_FLIPPED:
    soundFallOver();
    token = 'k'; strcpy(newCmd, "rc"); newCmdIdx = -2;   // run skill "rc" once
}
```

- Fires **only if gyro assist is on** (`gyroBalanceQ`).
- Runs skill `rc` **once**, same skill for supine and side falls (no differentiation).
- **No retry / give-up logic** — if still flipped after `rc` finishes, the exception
  re-triggers next tick → effectively "keep trying `rc`" until upright or gyro off.

**Sim-fidelity gap (why self-right failed to train — see `self-righting-research.md`):**
our sim terminates the episode at 1.3 rad ≈ **74° tilt**, *below* the firmware's
85° `FLIPPED` line — the policy never sees the flipped state the real robot
recovers from. And the scripted `rc` keyframes were never an available action in
sim. Real-robot recovery = detect flip → scripted `rc` → repeat. To reproduce in
sim: raise/remove the tilt cutoff for a recovery window, and expose `rc_ref.npy`
(below) as a scripted action or imitation target.

## Skill keyframe format (`skill.h` `Skill::dataLen`)

`InstinctBittleESP.h` stores each skill as `const int8_t <name>[] PROGMEM = {…}`.

| period `p` | kind | header | frame |
|---|---|---|---|
| `p > 1` | **gait** (loops) | 4 bytes `[period, expRoll, expPitch, ratio]` | 8 int8 leg-joint angles (DOF 8..15) |
| `p == 1` | **posture** | 4 bytes | 16 int8 full-DOF angles |
| `p < -1` | **behaviour** | 7 bytes `[period, expRoll, expPitch, ratio, loopStart, loopEnd, loopCycles]` | 16 angles + 4 timing params |

`ratio` (`angleDataRatio`): 1 or 2 — angles are divided by it on storage if any
exceed 128, so multiply back on read. Petoi leg-column order
`[FLs,FRs,BRs,BLs, FLk,FRk,BRk,BLk]`; skill names end `F` (forward) or `L`
(turn-left); `R` variants are the L/R mirror (pure column swap, sagittal joints).

## Extracted references (`reference_gait/build_skill_reference.py`)

Generalises `build_wkf_reference.py` to any skill → `<name>_ref.npy`, shape
`(100, 8)`, radians, URDF joint order — same as `wkf_ref.npy`, so any is a
drop-in `FAC_IMITATION` anchor via `G2E_SKILL_REF=<name>` (env re-loads
`WKF_REF`/`STAND_POSE`; unset = wkF, byte-identical).

| ref | firmware | period | per-joint deg (min…max) | vs wkF | what it is |
|---|---|---|---|---|---|
| `wkf_ref` | `wkF` | 116 | knee-swing ≈ 42° | — | the standing walk (current anchor) |
| `cr_ref` | `crF` | 103 | shoulders 22…110, **knees −52…−29 (always flexed)** | **mean 34.8°** | **crawl — deep crouch, biggest coordination delta.** Best "add a skill" test anchor. |
| `tr_ref` | `trF` | 48 | knee-swing **48°** (widest) | mean 20.5° | trot — faster, bouncier, biggest foot lift |
| `vt_ref` | `vtF` | 37 | knees −22…9, higher shoulders | mean 11.7° | "step" — stiff marching step, *smaller* knee swing than wkF (not a high-step) |
| `bk_ref` | `bkF` | 43 | knee-swing 21° | mean 11.6° | backward walk |
| `rc_ref` | `rc` | 5 (behaviour) | knees to 200°, shoulders to −176° | mean 55° | **self-right keyframes** (approx — timing params dropped). Reference for the sim self-right work, not a locomotion gait. |

**Note for the adapter skill probe:** `cr` (crouch) is a better test skill than a
hand-tuned "high-step" `PAW_Z_TARGET` — it's a real firmware trajectory with the
largest limb-coordination difference from wkF, so it's the clearest yes/no on
"can a frozen base + adapter acquire a new skill." `tr` (trot) is the natural
second skill for the 2-skill control run. See `docs/rl/adapter-skill-probe-spec.md`.
