# 2026-10-09 hardware session: V4 on G2, hardwood lane and a threshold ramp

V4 (`Release_CandidateV4_ppo.onnx`, deployed 2026-10-09) on G2 for the first time. Pack 8.54 V at the start (resting), 8.20 V after the session. Floor labels: hardwood (lane), transition (ramp).
Tape numbers: first = forward, second = sideways (+ = right), inches, measured by hand from the start line (ramp runs mostly measured, partly estimated, about +-2 in). Scripted = the `wkF` walk with no policy.
Logs in this folder (CSV, `run_gait --log-extra` columns). Logged yaw = firmware yaw, change over the run; "facing" = the user's by-eye estimate of G2's final heading (clock face, 12 = straight, 2 o'clock about 60 deg right).

## Air walk and lane, heading hold ON (front-left foot hold, trim limit -0.6)

| Log | What | Result |
|---|---|---|
| v4_air_01 | V4 held in the air, 6 s | level (roll +1.5, pitch -1.4), yaw +5, no faults |
| v4_lane_20261009_run01 | V4 12.5 s | 4 ft, 10 in left of the line; yaw +31; hold pinned at -0.6 |
| v4_laneB_run01 / 02 / 03 | V4 12.5 s | run 2: 4 ft 1 in, 9 in left; run 3: 4 ft, centered with the body turned left at the end; yaw +27 / +23 / +24 |

## Capture A, heading hold OFF, 12.5 s, alternating scripted / V4 (sysidA2_run01..12)

| Run | Walk | Tape (fwd, side) | Logged yaw |
|---|---|---|---|
| 1 | scripted | 48, +12 | +1 |
| 2 | V4 | 55, +6 | +72 |
| 3 | scripted | 48, +10 | +2 |
| 4 | V4 | 48, +6 | +108 |
| 5 | scripted | 48, +4 | +1 |
| 6 | V4 | 54, +6 | +101 |
| 7 | scripted | 48, +8 | +2 |
| 8 | V4 | 51, +4 | +112 |
| 9 | scripted | 52, +6 | +2 |
| 10 | V4 | 51, +6 | +112 |
| 11 | scripted | 48, +6 | -5 |
| 12 | V4 | 54, +6 | +103 |

V4 mean 52.2 in forward, 5.7 in right, roll sd 3.9 deg; scripted mean 48.7 in, 7.7 in right, roll sd 4.6 deg. No falls in any run.

## Facing check, V4, hold OFF (facing2_run01..03)

Facing 2 o'clock (about 60 deg right) after all three runs; logged yaw +102 / +108 / +104. V4 turns right about 8 deg/s with the hold off (the log reads higher than the by-eye angle).

## Threshold ramp, 1/4 in (6.4 mm) high, ramp up / flat / ramp down on both sides, hardwood to tile, hold OFF, 11 s for V4 (transS_run01..06)

Started on tile 4 in before the ramp, 4 ft of floor beyond. All six cleared it. Forward about 42 in. Sideways: scripted 6 left, 6 right, 9 right; V4 12 right, 10 right, 1 right. Roll sway 3.5-4.0 (V4), 4.3-4.5 (scripted): the same as on the flat lane.

## Conclusions

- V4 walks stably on G2 at the commanded speed, with no falls and less sway than the scripted walk.
- V4 turns right about 8 deg/s with the hold off (60-100 deg over 12.5 s); the hold at its old limit (-0.6) cut that to about +25 deg and sat at the limit the whole walk. Limit raised to -0.9 the same evening.
- The path stays near straight on tape while the body turns; unexplained.
- A 6.4 mm ramped threshold costs neither walk any speed or stability.
- Not done: the taller threshold, the low-pack repeat, bench servo tests. `real2sim.py --fit` waits for an idle Mac.

## Sim-versus-real replay and fit (run 2026-10-09 evening, Mac idle)

`real2sim.py` replays the joint commands G2 actually sent through the training environment (no randomization) and compares the body motion with G2's IMU. Nine V4 hold-off hardwood logs (capture A runs 2, 4, 6, 8, 10, 12 and the three facing-check runs; the scripted-walk logs have a different format and were not replayed):

- **Per log:** real roll sway 3.5-4.3 deg against 2.7-2.9 in the sim (the sim sways about 30% less), pitch 1.9-2.9 against 1.7-1.9, dominant sway frequency 0.77-0.79 Hz real against 0.79 sim (matches). Gap score 0.02-0.10 (mean about 0.04).
- **Fit** (`real2sim_fit.json`, 60 grid points over servo speed limit, motor force and ground friction): best gap 0.028 at servo speed 320 deg/s (the sim uses 200), motor force 0.18-0.22, friction 1.0-1.3. The five best points differ by under 0.002 in gap, so the data does not separate these three settings: **not confident, nothing applied.** It must reproduce on a second session (another day or battery) and pass `tools/g2_calibrate.py`'s gates before any value goes into training. Heading is not part of the fit (real data never sets drift).
- **Ingest** (`tools/g2_ingest.py` on the Pi's automatic logs, 196 runs): 35 usable (119 s of steady walking), all from hardware epoch 2026-10-07 on tile; 153 quarantined (65 with a steady window under 2 s, 60 steering-test runs, 55 whose floor was not confirmed for that time, 50 with too few rows); 8 excluded. Today's explicit-log capture runs are not in the store (they have no automatic sidecar); they feed `real2sim.py` directly.
