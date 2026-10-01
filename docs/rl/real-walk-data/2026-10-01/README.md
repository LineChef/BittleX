# Real-walk data, 2026-10-01

Raw logs from the first real-robot walks of G2, kept for historic reference when the walking
gaits are worked on again. Interpretation, conclusions and the open list are in
[`../../real-walk-log.md`](../../real-walk-log.md). `summary.txt` is `tools/walk_log_summary.py`
run over every file here (regenerate it with `python tools/walk_log_summary.py docs/rl/real-walk-data/2026-10-01/*.csv`).

**Conditions.** Hard floor and ~1/4 in (6.4 mm) pile carpet; off the stand; payload = what V2.1
was trained with but only temporarily mounted (it can shift); IMU at the stock 5.0 Hz over the Pi's
UART; battery ~7.6-7.8 V; firmware gyro balance **off** for every run below except the `kcarpetF`
firmware gaits (balance on). IMU zero re-calibrated with `gc` after `hard_v21_run01`.

**Columns.** `t` seconds; `roll,pitch,yaw` radians from the IMU (yaw = accumulated since boot,
positive = turned right; includes any hand corrections); `gx,gy,gz` always 0 (the stock stream has no
angular rate); `j0..j7` commanded joint angles in degrees, URDF order (FL-sh, FL-kn, FR-sh, FR-kn,
BR-sh, BR-kn, BL-sh, BL-kn) -- only in the policy-loop logs; `guard_state,hottest_*` thermal-guard
model estimates (not measured temperatures); `volt` battery volts where logged.

## Files

| file | what | notes |
|---|---|---|
| `hard_v21_run01.csv` .. `run06.csv` | V2.1 policy, `--cmd 0.10`, 12.5 s (10 gait cycles), hard floor | run01 is before `gc`; runs 02-05 had small hand corrections to stay on the desk; run06 hands off. All upright |
| `carpet_v21_run01.csv` | same, on carpet | fell at 2.0 s and ~11 s (user flipped it back in between, so only the first fall is clean) |
| `carpet_fw_carpetF_run01.csv` | firmware `kcarpetF`, 10 s, carpet | stayed up, walked in place, BR leg sagged |
| `hard_fw_carpetF_run01.csv` | same, hard floor | walked forward ~1 ft 9 in, no sag |
| `carpet_ol_lift16_run01.csv` | scripted `wkF` open-loop, all joints x1.6, 6 cycles, balance off | fell at 2.7 s (sideways) |
| `carpet_ol_lift20_run01.csv` | same, x2.0 | fell at 2.7 s (sideways) |
| `carpet_ol_knee20_sh07_run01.csv` | knees x2.0, shoulders x0.7, no ramp | fell at 0.7 s (start transition) |
| `carpet_ol_knee20_sh07_ramp_run01.csv` | same + 1-cycle ramp, 8 cycles | 2 good steps, fell at 2.9 s |
| `carpet_ol_knee175_sh01_ramp_run01.csv` | knees x1.75, shoulders x0.1, ramp, 8 cycles | fell sideways at 3.0 s |
| `carpet_ol_knee175_sh01_volt_run01.csv` | same, voltage logged | **INVALID as a fall test -- the user held G2 up for most of it.** Voltage column is valid |
| `hard_ol_knee175_sh01_volt_run01.csv` | same variant on hard floor, voltage logged | fell at 3.3 s (flipped) |

The first open-loop scripted runs (hard floor ~3 ft in 6 cycles, curved left; carpet x1.0, fell with the
feet catching) and the first aborted attempts have no log.

## Measurements without a CSV

- **IMU in `kbalance`, firmware balance ON, before `gc`:** roll -18.9 / pitch +11.2 deg (24 frames, steady),
  FR foot pushed out. Balance OFF, same pose: roll -0.4 / pitch 1.7 (earlier 0.7 / -0.7 after `gc`).
- **After `gc`:** balance OFF roll 0.7 / pitch -0.7; balance ON roll 0.8 / pitch -0.8 (41 frames, std 0.2).
  At rest: roll -3.2 / pitch -0.3 (was +0.9 / +1.1 before `gc`).
- **Standing on carpet, balance off:** roll -0.8 (std 1.0) / pitch -0.5 (std 0.4), 52 frames.
- **Battery voltage (`P`):** 7.81 V rest, 7.77 V standing, 7.77 V after the x1.6 run (pre-run reading
  7.65-7.70 during later runs); see the volt column for in-run values (7.37 V in the last 2 s of the
  hand-held run).
- **Servo position feedback (`f`):** only an echo came back, with the servos relaxed and powered.
- **Sim replay of the hard-floor V2.1 logs** (`rl_training/opencat-gym/sim_vs_real_walk.py`, corrected
  payload inertia): runs 01 and 05 stay upright in the sim -- distance 1.21 / 1.24 m (real ~1.47 m), roll std
  4.1 / 3.6 deg (real 6.6 / 7.0), yaw -37 / -31 deg (real +132 / -15); runs 02-04 and 06 fall over in the open-loop
  replay (the commands came from a closed loop). Actuator `--fit` gave no usable result.
- **Foot lift / stride estimates** (forward kinematics of the commanded joints, body fixed): see the table in
  `real-walk-log.md`.
