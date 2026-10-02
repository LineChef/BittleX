# Servo troubleshooting data, 2026-10-02

After the user re-calibrated the limbs. Interpretation and the open list: see "Servo troubleshooting --
where we left off" in [`../../real-walk-log.md`](../../real-walk-log.md).

Servo position feedback (`f`) works only over the BiBoard's **USB** cable to the Mac (the Pi's UART returns just an
echo). Servos 8..15 = FL, FR, BR, BL shoulders, then FL, FR, BR, BL knees (confirmed by eye: servos 8, 9, 10, 11 move
FL, FR, BR, BL). Feedback streams ~5 rows/s, 8 values per row; any new command stops the stream, so restart it with
`f` after a move has settled. Noise is about +-0.5 deg.

## Files

| file | what |
|---|---|
| `servo_response.csv` | `tools/servo_response_test.py` output. **Not trustworthy past the baseline:** that script sent `f` 0.15 s after each move and cut moves short. Use `servo_static_test.py` instead |
| `servo_static.csv` | `tools/servo_static_test.py`, G2 standing on the floor, balance off |
| `servo_static_unloaded.csv` | same, G2 held in the air, legs free |
| `hard_fw_vtF_bal_on_run01.csv` | firmware step gait `kvtF`, 6 s, hard floor, untethered, balance on (`walk_log_summary.py` works on it) |

## Results that were only printed (no CSV)

**Rest pose, relaxed, fresh boot (mean of 10 rows):** FL-sh 70.4, FR-sh 71.2, BR-sh 75.9, BL-sh 75.6 | FL-kn -52.2,
FR-kn -58.0, BR-kn -60.4, BL-kn -57.7.

**Standing on the floor, every joint commanded to shoulders 50 / knees 0, repeated 5 times (2.5 s after each command):**

| attempt | FL-sh | FR-sh | BR-sh | BL-sh | FL-kn | FR-kn | BR-kn | BL-kn |
|---|---|---|---|---|---|---|---|---|
| 1 | 35.3 | 49.3 | 49.4 | 49.8 | -0.8 | -3.4 | -21.9 | -22.0 |
| 2 | 42.3 | 49.4 | 50.4 | 49.8 | -1.8 | -5.1 | -20.4 | -18.0 |
| 3 | 42.2 | 49.3 | 50.4 | 49.2 | -1.1 | -9.6 | -20.8 | -14.0 |
| 4 | 42.3 | 49.3 | 50.3 | 49.6 | -2.3 | -11.1 | -23.7 | -17.5 |
| 5 | 42.4 | 49.2 | 50.2 | 49.3 | -4.2 | -11.4 | -23.7 | -18.6 |

**Unloaded staircase (`servo_static_unloaded.csv`), reading at commands 35 / 50 / 65 (shoulders) and -15 / 0 / 15 (knees):**
all four knees gain 0.96-0.98, offset ~0. BR and BL shoulders 35.2/48.8/63.5 and 35.5/49.0/63.7. **FL shoulder
35.6 / 42.2 / 63.4. FR shoulder -3.5 / 48.4 / -15.0** (a one-off glitch; a repeat with raw readings tracked 34-35, 48-50, 63).

**Raw FR shoulder, G2 held in the air, 3 s per target:** 35 -> 34..36; 50 -> 48..49; 65 -> 63; 50 -> 50..51; 35 -> 34..36 (clean).

**Raw FL shoulder, same setup, 2.2 s per target:** 35 -> 35..36; 45 -> 42..44; 50 -> 42..43; 55 -> 47; 50 -> 49..50;
65 -> **42**; 50 -> **42**; 40 -> 40..41; 50 -> 48..49.

**Hysteresis sweep, G2 held in the air, mean feedback after each command (targets 40 44 48 50 52 56 60 65), two passes
each, approaching from below then from above:**

| | 40 | 44 | 48 | 50 | 52 | 56 | 60 | 65 |
|---|---|---|---|---|---|---|---|---|
| FL-sh below #1 | 39.0 | 36.2 | 18.6 | 42.6 | 42.5 | 42.2 | 42.7 | -- |
| FL-sh below #2 | 38.9 | 42.6 | 42.4 | 41.3 | 19.5 | 54.3 | 58.3 | 63.2 |
| FL-sh above #1 | 39.7 | 40.6 | 42.9 | 41.4 | 41.8 | 42.5 | 60.3 | 63.1 |
| FL-sh above #2 | 39.0 | 30.1 | -- | 27.1 | 41.7 | 40.4 | 42.7 | 42.6 |
| FR-sh below #1 | 1.7 | 42.4 | 46.2 | 47.8 | 50.4 | 54.3 | 58.0 | 62.8 |
| FR-sh below #2 | 38.1 | 42.4 | 46.1 | -21.3 | 50.0 | 54.1 | 57.9 | 62.9 |
| FR-sh above #1 | 38.2 | 15.0 | 48.3 | 49.9 | 51.9 | 56.4 | 60.1 | 65.0 |
| FR-sh above #2 | -16.3 | 44.1 | 48.3 | 50.0 | 50.4 | -25.4 | 58.1 | 17.1 |

**Slow FL-shoulder sweep (servo 8 only, ~2 s per step, user watching the leg; G2 stood on the floor):**
commands 40 45 50 55 60 65 60 55 50 45 40 read 31.1 42.9 42.0 35.1 42.3 42.4 42.6 21.3 42.5 40.7 40.7.
**The user's observation of what the leg actually did during this sweep was not reported before the session paused.**
