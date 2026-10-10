# 2026-10-09 night / 2026-10-10 hardware session: V6 foot-trim calibration and the eased stand-up

V6 (`Release_CandidateV6_ppo.onnx`) on G2, hardwood, 9 ft lane, fresh pack 8.43 V resting at the start (about 8.15 V after the walks). Heading hold off throughout. Tape numbers: sideways offset from the lane centre line in inches (+ = right), by the user. Log yaw = firmware yaw change over the run; it reads low against the by-eye heading on long walks (the first 20 s run: log -11 deg, user 10:30 = 45 deg left), so the tape is the truth.
Procedure used (replaces timed intervals between runs): Claude runs one walk and reports; the user measures, resets G2 and replies with the numbers; that reply is the go for the next run. Runs the user marks as not ready or touched are redone and the logs kept, labelled below.

## Trim sweep (12.5 s, cmd 0.10, front-left foot trim `--foot-trim fl=X`)

| Trim | Log yaw (deg, per run) | Tape sideways (in) |
|---|---|---|
| off (`v6_nat01..03`, plus `v6_first` 6 s) | +71, +89, +87 | 10 R, 12.5 R, 16 R |
| fl=-0.2 (`v6_trim20_01b, 02, 03`) | +80, +73, +86 | 8 R, 15 R, 14 R |
| fl=-0.5 (`v6_trim50_01, 02b, 03`) | +51, +36, +44 | 6 R, 6 L, 1.5 R |
| fl=-0.5 confirm (`v6_confirm50_01, 02b, 03`) | +44, +19, +25 | 0.5 L, 2 L, 0 |

**Result: V6 default foot trim fl=-0.5** (`DEFAULT_TRIMS` in `gait/heading_hold.py`, keyed to the file name). Roll/pitch sway 3-4 deg and 2-3 deg, no falls. Not re-tuned for tile or carpet.
Redone and discarded: `v6_trim20_01` (user not ready), `v6_trim50_02` (measurement missed), `v6_confirm50_02` (user touched G2; a 34 s run).

## Long walk (20 s, fl=-0.5)

`v6_long50_cal`: 6 ft 1 in forward (about 0.093 m/s measured, against 0.10 commanded) and 27 in LEFT, facing 10:30, log yaw -11 deg. The first long walk also ran into the wall at the end of the lane. The repeats `v6_long50_rep01` and `v6_long50_rep01b` started crooked (the stand-up jerk moved the heading, 12:30), so they are not valid and no trim was changed on the long-walk data. Redo from a clean start (with the eased stand-up) is open.

## Stand-up (isolated tests, `standup_*.csv`, `gait/standup_test.py`, IMU at 5 Hz)

| Stand-up | Peak roll | Peak pitch | Heading change | User verdict |
|---|---|---|---|---|
| original single `i` command, 3 tries | 3.7 / 16.1 / 4.1 deg | 4.1 / 7.3 / 2.6 deg | 11.9 / 10.1 / 0.0 deg | much too fast, jostles the heading |
| `kbalance` then `i` (first eased try, inside a walk) | not logged | not logged | not logged | stood up faster, almost fell |
| ramp 8 s | 2.6, 3.7 | 3.0, 3.6 | 0.5, 0.8 | far too slow |
| `kup` (scripted skill) | 3.6 | 2.5 | 1.8 | a bit fast |
| ramp 1.6 s, 1.2 s | 1.3, 1.5 | 2.8, 2.0 | 0.0, 0.0 | too slow |
| **ramp 0.8 s, 5 tries** | 1.9-2.8 | 2.2-3.1 | 0.1-0.3 | right; smooth; back legs even with the front; no beeping; start heading no longer disturbed |

Per-step beeping seen with the first ramps was not heard at 0.8-1.2 s. The board echoes every `i` command; no error lines.
