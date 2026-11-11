# Servo troubleshooting data, 2026-10-02

After the user re-calibrated the limbs. Interpretation and the open list: see "Servo troubleshooting --
state at the end of the session" in [`../../real-walk-log.md`](../../real-walk-log.md).

Servo position feedback (`f`) works only over the BiBoard's **USB** cable to the Mac (the Pi's UART returns just an
echo). Servos 8..15 = FL, FR, BR, BL shoulders, then FL, FR, BR, BL knees (confirmed by eye: servos 8, 9, 10, 11 move
FL, FR, BR, BL). Feedback streams ~5 rows/s, 8 values per row; any new command stops the stream, so restart it with
`f` after a move has settled. Noise is about +-0.5 deg.

## Files

- `servo_response.csv`: `tools/servo_response_test.py` output. **Not trustworthy past the baseline:** that script sent `f` 0.15 s after each move and cut moves short. Use `servo_static_test.py` instead
- `servo_static.csv`: `tools/servo_static_test.py`, G2 standing on the floor, balance off
- `servo_static_unloaded.csv`: same, G2 held in the air, legs free
- `hard_fw_vtF_bal_on_run01.csv`: firmware step gait `kvtF`, 6 s, hard floor, untethered, balance on (`walk_log_summary.py` works on it)

## Results that were only printed (no CSV)

Rest pose, relaxed, fresh boot (mean of 10 rows): FL-sh 70.4, FR-sh 71.2, BR-sh 75.9, BL-sh 75.6 | FL-kn -52.2,
FR-kn -58.0, BR-kn -60.4, BL-kn -57.7.

**Standing on the floor, every joint commanded to shoulders 50 / knees 0, repeated 5 times (2.5 s after each command):**

- 1: FL-sh: 35.3; FR-sh: 49.3; BR-sh: 49.4; BL-sh: 49.8; FL-kn: -0.8; FR-kn: -3.4; BR-kn: -21.9; BL-kn: -22.0
- 2: FL-sh: 42.3; FR-sh: 49.4; BR-sh: 50.4; BL-sh: 49.8; FL-kn: -1.8; FR-kn: -5.1; BR-kn: -20.4; BL-kn: -18.0
- 3: FL-sh: 42.2; FR-sh: 49.3; BR-sh: 50.4; BL-sh: 49.2; FL-kn: -1.1; FR-kn: -9.6; BR-kn: -20.8; BL-kn: -14.0
- 4: FL-sh: 42.3; FR-sh: 49.3; BR-sh: 50.3; BL-sh: 49.6; FL-kn: -2.3; FR-kn: -11.1; BR-kn: -23.7; BL-kn: -17.5
- 5: FL-sh: 42.4; FR-sh: 49.2; BR-sh: 50.2; BL-sh: 49.3; FL-kn: -4.2; FR-kn: -11.4; BR-kn: -23.7; BL-kn: -18.6

**Unloaded staircase (`servo_static_unloaded.csv`), reading at commands 35 / 50 / 65 (shoulders) and -15 / 0 / 15 (knees):**
all four knees gain 0.96-0.98, offset ~0. BR and BL shoulders 35.2/48.8/63.5 and 35.5/49.0/63.7. **FL shoulder
35.6 / 42.2 / 63.4. FR shoulder -3.5 / 48.4 / -15.0** (a one-off glitch; a repeat with raw readings tracked 34-35, 48-50, 63).

Raw FR shoulder, G2 held in the air, 3 s per target: 35 -> 34..36; 50 -> 48..49; 65 -> 63; 50 -> 50..51; 35 -> 34..36 (clean).

Raw FL shoulder, same setup, 2.2 s per target: 35 -> 35..36; 45 -> 42..44; 50 -> 42..43; 55 -> 47; 50 -> 49..50;
65 -> **42**; 50 -> **42**; 40 -> 40..41; 50 -> 48..49.

**Hysteresis sweep, G2 held in the air, mean feedback after each command (targets 40 44 48 50 52 56 60 65), two passes
each, approaching from below then from above:**

- FL-sh below #1: 40: 39.0; 44: 36.2; 48: 18.6; 50: 42.6; 52: 42.5; 56: 42.2; 60: 42.7; 65: --
- FL-sh below #2: 40: 38.9; 44: 42.6; 48: 42.4; 50: 41.3; 52: 19.5; 56: 54.3; 60: 58.3; 65: 63.2
- FL-sh above #1: 40: 39.7; 44: 40.6; 48: 42.9; 50: 41.4; 52: 41.8; 56: 42.5; 60: 60.3; 65: 63.1
- FL-sh above #2: 40: 39.0; 44: 30.1; 48: --; 50: 27.1; 52: 41.7; 56: 40.4; 60: 42.7; 65: 42.6
- FR-sh below #1: 40: 1.7; 44: 42.4; 48: 46.2; 50: 47.8; 52: 50.4; 56: 54.3; 60: 58.0; 65: 62.8
- FR-sh below #2: 40: 38.1; 44: 42.4; 48: 46.1; 50: -21.3; 52: 50.0; 56: 54.1; 60: 57.9; 65: 62.9
- FR-sh above #1: 40: 38.2; 44: 15.0; 48: 48.3; 50: 49.9; 52: 51.9; 56: 56.4; 60: 60.1; 65: 65.0
- FR-sh above #2: 40: -16.3; 44: 44.1; 48: 48.3; 50: 50.0; 52: 50.4; 56: -25.4; 60: 58.1; 65: 17.1

**Slow FL-shoulder sweep (servo 8 only, ~2 s per step, user watching the leg; G2 stood on the floor):**
commands 40 45 50 55 60 65 60 55 50 45 40 read 31.1 42.9 42.0 35.1 42.3 42.4 42.6 21.3 42.5 40.7 40.7.
**The user's observation of what the leg actually did during this sweep was not reported before the session paused.**
