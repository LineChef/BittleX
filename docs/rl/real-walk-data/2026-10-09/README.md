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
