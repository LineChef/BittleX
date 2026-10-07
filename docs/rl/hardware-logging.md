# Hardware walk logging: what each log carries

What `run_gait.py --log` writes, what the firmware can and cannot give us, and what is worth using as training evidence. Written 2026-10-07.

## Columns

| Log | Columns | Rate |
|---|---|---|
| Policy walk (`run_gait.py --log`) | `t, roll, pitch, yaw, gx, gy, gz, j0..j7, guard_state, hottest_j, hottest_tier, hottest_frac, duty_s` (+ `steer_u` with heading hold) | one row per control tick (80 Hz); `j0..j7` are the **commanded** joint angles; `gx..gz` are zero (rate mode `zero`) |
| Same, with `--log-extra` | adds `ax, ay, az, imu_n, imu_age_s, volt` | `ax..az` from the IMU line, in m/s^2 (the first kitchen logs show about 10 at rest on az, so the unit is m/s^2 and not g); `imu_n` counts IMU frames received (rows with the same number share one held frame, so a fresh reading is where it changes); `volt` is the last pack voltage (asked every 5 s while walking, so it is stale between readings) |
| Open-loop `wkF` (`--openloop --log`) | `t, roll, pitch, yaw, gx, gy, gz, guard_state, volt` | the walk's own commands are not logged; `--volt-every S` sets the voltage rate |

## What cannot be logged during a walk

- **Measured joint angles.** The firmware's `f` feedback stream stops whenever a new command arrives (`tools/servo_response_test.py` notes this), and the 80 Hz loop sends a command every
  tick. Measured joint angles therefore come only from bench tests: in the air, standing still, and single-joint steps (`tools/servo_static_test.py`, `servo_response_test.py`, the H13 step tests).
- **IMU faster than 5 Hz.** The firmware prints a frame at most every 200 ms; between frames the log repeats the held frame. Use `imu_n` to keep only fresh rows when fitting.
- **Motor current, foot contact, servo temperature:** not available on this hardware (temperature in the logs is the estimated I2t heat).
- **Position, speed and heading ground truth:** not from the robot; a phone video with a marker, or a tape measure.

## Use `--log-extra` like this

`python pi_pipeline/gait/run_gait.py --cmd 0.10 --seconds 12.5 --log ~/g2_runs/x.csv --log-extra` (works with the other flags). Default logs are unchanged.
