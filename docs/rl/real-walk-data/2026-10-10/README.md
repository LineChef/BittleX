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

**Result of the short-walk sweep: fl=-0.5 (superseded by fl=-0.3 after the 20 s walks, see below)** (`DEFAULT_TRIMS` in `gait/heading_hold.py`, keyed to the file name). Roll/pitch sway 3-4 deg and 2-3 deg, no falls. Not re-tuned for tile or carpet.
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

## Long-lane trim (20 s, cmd 0.10, pack 7.75-7.95 V throughout, eased stand-up, watchdog fix in)

The auto-captured logs are on the Pi in `~/g2_runs/auto/20261010/` (CSV + sidecar with the trim and surface). Tape by the user; "loc" = left of center.

| Trim | Forward | Sideways | Facing | Log yaw (deg) |
|---|---|---|---|---|
| fl=-0.5 | 6 ft | 29 in left | 10:00 | -46 |
| fl=-0.4 | 6 ft 7 in | 14 in left | not recorded | -8 |
| fl=-0.3 | 6 ft 10 in | 3.5 in left | 11:30 | +24 |
| fl=-0.25 | 7 ft | 2.5 in left | 11:30 | +26 |
| fl=-0.3, 24 s, old start (lane 1) | 6 ft 8 in | wall contact for the last 3 s (not a measurement) | n/a | -18 |
| fl=-0.3, 24 s, start moved right (lane 2) | 7 ft 6 in | 19 in left (no wall) | 10:00 | +37 |
| fl=-0.3, 20 s, new start | 7 ft | 2 in right | 11:45 | +62 |

The 27-29 in left readings of the first two rows of this table were open floor (only the 24 s lane 1 run touched the wall). **V6 default trim is now fl=-0.3** (`DEFAULT_TRIMS`; the 12.5 s trim of -0.5 above was fit on short walks and drifts left on 20 s walks). Every 20 s walk at -0.3 / -0.25 ended within 3.5 in of the line, both 24 s walks curved left: a length effect past about 20 s (open: a third 24 s run). Speed measured about 4.2 in/s (7 ft in 20 s), 3.65 in/s on the first 20 s run (the stand-up jerk); use about 0.107 m/s for "walk for x distance / seconds" estimates, tape-checked. The servo heat estimate stayed at 1% in every run, so it is not heat.

The 12.5 s trim of `fl=-0.5` (set from short walks above 8.1 V) is about 2 in at 4 ft but 29 in left at 6 ft: the drift grows faster than distance, and weakening the trim by 0.1 removes about 12 in of left drift at 6 ft. The log yaw does not track the tape in either direction (it read low at -0.5, high at -0.3), so the tape is the measure.
**Low-voltage theory (the left drift appeared as the pack fell from 8.4 V to 7.8 V): not supported.** A straight 20 s walk at fl=-0.3 on a 7.8-7.9 V pack means the long-walk result is explained by the trim and the walk length, not by the pack. Not isolated: `fl=-0.5` was not repeated on a full pack, so a small pack effect is not excluded; it is simply not needed to explain the data.
Invalid runs (user handling G2 or a cord): `policy_walk_004734` (stood up twice, the watchdog bug below), `policy_walk_005455`, the first `fl=-0.3` attempt.

## Bug found: watchdog laid G2 down during setup

The first lane runs with the eased stand-up stood G2 up, laid him down, and stood him up again un-eased. The control-loop watchdog was started before the stand-up and has a 2 s start-up grace; the 0.8 s ramp pushed the setup (gb, ramp, settle, gP, IMU priming) past it, the watchdog saw a stall and sent `d` (visible in `~/.local/share/g2/noise.jsonl` at 12:47:36 AM). The same thing explains the earlier `kbalance` try. Fixed: `wd.start()` now runs just before the control loop (test `test_watchdog_starts_after_the_stand_up_setup_not_before`).
