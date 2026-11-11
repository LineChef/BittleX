# 2026-10-09 night / 2026-10-10 hardware session: V6 foot-trim calibration and the eased stand-up

V6 (`Release_CandidateV6_ppo.onnx`) on G2, hardwood, 9 ft lane, fresh pack 8.43 V resting at the start (about 8.15 V after the walks). Heading hold off throughout. Tape numbers: sideways offset from the lane centre line in inches (+ = right), by the user. Log yaw = firmware yaw change over the run; it reads low against the by-eye heading on long walks (the first 20 s run: log -11 deg, user 10:30 = 45 deg left), so the tape is the truth.
Procedure used (replaces timed intervals between runs): Claude runs one walk and reports; the user measures, resets G2 and replies with the numbers; that reply is the go for the next run. Runs the user marks as not ready or touched are redone and the logs kept, labelled below.

## Trim sweep (12.5 s, cmd 0.10, front-left foot trim `--foot-trim fl=X`)

- off (`v6_nat01..03`, plus `v6_first` 6 s): Log yaw (deg, per run): +71, +89, +87; Tape sideways (in): 10 R, 12.5 R, 16 R
- fl=-0.2 (`v6_trim20_01b, 02, 03`): Log yaw (deg, per run): +80, +73, +86; Tape sideways (in): 8 R, 15 R, 14 R
- fl=-0.5 (`v6_trim50_01, 02b, 03`): Log yaw (deg, per run): +51, +36, +44; Tape sideways (in): 6 R, 6 L, 1.5 R
- fl=-0.5 confirm (`v6_confirm50_01, 02b, 03`): Log yaw (deg, per run): +44, +19, +25; Tape sideways (in): 0.5 L, 2 L, 0

**Result of the short-walk sweep: fl=-0.5 (superseded by fl=-0.3 after the 20 s walks, see below)** (`DEFAULT_TRIMS` in `gait/heading_hold.py`, keyed to the file name). Roll/pitch sway 3-4 deg and 2-3 deg, no falls. Not re-tuned for tile or carpet.
Redone and discarded: `v6_trim20_01` (user not ready), `v6_trim50_02` (measurement missed), `v6_confirm50_02` (user touched G2; a 34 s run).

## Long walk (20 s, fl=-0.5)

`v6_long50_cal`: 6 ft 1 in forward (about 0.093 m/s measured, against 0.10 commanded) and 27 in LEFT, facing 10:30, log yaw -11 deg. The first long walk also ran into the wall at the end of the lane. The repeats `v6_long50_rep01` and `v6_long50_rep01b` started crooked (the stand-up jerk moved the heading, 12:30), so they are not valid and no trim was changed on the long-walk data. Redo from a clean start (with the eased stand-up) is open.

## Stand-up (isolated tests, `standup_*.csv`, `gait/standup_test.py`, IMU at 5 Hz)

- original single `i` command, 3 tries: Peak roll: 3.7 / 16.1 / 4.1 deg; Peak pitch: 4.1 / 7.3 / 2.6 deg; Heading change: 11.9 / 10.1 / 0.0 deg; User verdict: much too fast, jostles the heading
- `kbalance` then `i` (first eased try, inside a walk): Peak roll: not logged; Peak pitch: not logged; Heading change: not logged; User verdict: stood up faster, almost fell
- ramp 8 s: Peak roll: 2.6, 3.7; Peak pitch: 3.0, 3.6; Heading change: 0.5, 0.8; User verdict: far too slow
- `kup` (scripted skill): Peak roll: 3.6; Peak pitch: 2.5; Heading change: 1.8; User verdict: a bit fast
- ramp 1.6 s, 1.2 s: Peak roll: 1.3, 1.5; Peak pitch: 2.8, 2.0; Heading change: 0.0, 0.0; User verdict: too slow
- ramp 0.8 s, 5 tries: Peak roll: 1.9-2.8; Peak pitch: 2.2-3.1; Heading change: 0.1-0.3; User verdict: right; smooth; back legs even with the front; no beeping; start heading no longer disturbed

Per-step beeping seen with the first ramps was not heard at 0.8-1.2 s. The board echoes every `i` command; no error lines.

## Long-lane trim (20 s, cmd 0.10, pack 7.75-7.95 V throughout, eased stand-up, watchdog fix in)

The auto-captured logs are on the Pi in `~/g2_runs/auto/20261010/` (CSV + sidecar with the trim and surface). Tape by the user; "loc" = left of center.

- fl=-0.5: Forward: 6 ft; Sideways: 29 in left; Facing: 10:00; Log yaw (deg): -46
- fl=-0.4: Forward: 6 ft 7 in; Sideways: 14 in left; Facing: not recorded; Log yaw (deg): -8
- fl=-0.3: Forward: 6 ft 10 in; Sideways: 3.5 in left; Facing: 11:30; Log yaw (deg): +24
- fl=-0.25: Forward: 7 ft; Sideways: 2.5 in left; Facing: 11:30; Log yaw (deg): +26
- fl=-0.3, 24 s, old start (lane 1): Forward: 6 ft 8 in; Sideways: wall contact for the last 3 s (not a measurement); Facing: n/a; Log yaw (deg): -18
- fl=-0.3, 24 s, start moved right (lane 2): Forward: 7 ft 6 in; Sideways: 19 in left (no wall); Facing: 10:00; Log yaw (deg): +37
- fl=-0.3, 20 s, new start: Forward: 7 ft; Sideways: 2 in right; Facing: 11:45; Log yaw (deg): +62

The 27-29 in left readings of the first two rows of this table were open floor (only the 24 s lane 1 run touched the wall). **V6 default trim is now fl=-0.3** (`DEFAULT_TRIMS`; the 12.5 s trim of -0.5 above was fit on short walks and drifts left on 20 s walks). Every 20 s walk at -0.3 / -0.25 ended within 3.5 in of the line, both 24 s walks curved left: a length effect past about 20 s (open: a third 24 s run). Speed measured about 4.2 in/s (7 ft in 20 s), 3.65 in/s on the first 20 s run (the stand-up jerk); use about 0.107 m/s for "walk for x distance / seconds" estimates, tape-checked. The servo heat estimate stayed at 1% in every run, so it is not heat.

The 12.5 s trim of `fl=-0.5` (set from short walks above 8.1 V) is about 2 in at 4 ft but 29 in left at 6 ft: the drift grows faster than distance, and weakening the trim by 0.1 removes about 12 in of left drift at 6 ft. The log yaw does not track the tape in either direction (it read low at -0.5, high at -0.3), so the tape is the measure.
**Low-voltage theory (the left drift appeared as the pack fell from 8.4 V to 7.8 V): not supported.** A straight 20 s walk at fl=-0.3 on a 7.8-7.9 V pack means the long-walk result is explained by the trim and the walk length, not by the pack. Not isolated: `fl=-0.5` was not repeated on a full pack, so a small pack effect is not excluded; it is simply not needed to explain the data.
Invalid runs (user handling G2 or a cord): `policy_walk_004734` (stood up twice, the watchdog bug below), `policy_walk_005455`, the first `fl=-0.3` attempt.

## Bug found: watchdog laid G2 down during setup

The first lane runs with the eased stand-up stood G2 up, laid him down, and stood him up again un-eased. The control-loop watchdog was started before the stand-up and has a 2 s start-up grace; the 0.8 s ramp pushed the setup (gb, ramp, settle, gP, IMU priming) past it, the watchdog saw a stall and sent `d` (visible in `~/.local/share/g2/noise.jsonl` at 12:47:36 AM). The same thing explains the earlier `kbalance` try. Fixed: `wd.start()` now runs just before the control loop (test `test_watchdog_starts_after_the_stand_up_setup_not_before`).

## Threshold crossings, 1/4 in (6.4 mm) ramped strip, tile to hardwood (floor label `transition`)

Same strip and layout as the V4 session (2026-10-09): start on tile 4.5 in before the threshold, 4 ft of runway beyond it; V6 at the default trim fl=-0.3, 11 s, hold off, pack 7.82-7.85 V. Logs are the auto-captured `policy_walk_*` runs of 1:22, 1:24 and 1:26 AM on the Pi.

- 1: Cleared: clean; Forward: 3 ft 3 in; Sideways: 0; Facing: 11:45; Roll / pitch sway (deg): 3.5 / 2.5
- 2: Cleared: clean; Forward: 3 ft 3 in; Sideways: 1 in left; Facing: 12:00; Roll / pitch sway (deg): 3.5 / 2.5
- 3: Cleared: clean; Forward: 3 ft 3 in; Sideways: 0; Facing: 12:00; Roll / pitch sway (deg): 3.6 / 2.6

All three clear the 6.4 mm threshold with no snag and no speed cost (V4: about 3 ft 6 in, sway 3.5-4.0 / flat-lane sway), and heading stayed within 15 deg of straight. No taller strip available yet.
