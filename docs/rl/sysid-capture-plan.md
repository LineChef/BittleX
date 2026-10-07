# Data capture for system identification (agreed 2026-10-07)

Real-robot data to fit the sim and to score policies. No video. Rules (user, 2026-10-07): real data sets the sim's numbers and ranges and serves as the real-world score; it is **never a source of drift**
(drift direction and size stay out of the sim; command drift is the Pi heading hold's job). A value only counts as confident if a fit on one session reproduces on another (different day or battery).
Why and what is in or out: [`v3-decisions-log.md`](v3-decisions-log.md). What each log carries: [`hardware-logging.md`](hardware-logging.md).

**Before the first session:** the Pi has the `--log-extra` change (the deploy watcher installs it when the Pi next comes online; check `~/g2_logs/deploy_done`).

## Session A (full pack, hardwood lane, same start spot as the baselines)

| # | What | Command | Notes |
|---|---|---|---|
| 1 | Pack voltage at rest | `check_serial send P` (g2-voice stopped) | write it down at the start and the end |
| 2 | 6 V2.1 walks, extra columns | `bash tools/g2_baseline.sh start 6 sysidA_v21` | `--log-extra` is on by default; fetch with `g2_baseline.sh fetch` |
| 3 | 6 scripted `wkF` walks (no policy) | `bash tools/g2_baseline.sh start 6 sysidA_wkF --scripted-mix abab` runs V2.1 and `wkF` alternately; use it for 12 runs | the scripted walk is the open-loop reference |
| 4 | Ground truth after every run, by tape | forward distance and sideways offset at the end (cm, + = right) | tell me the numbers in chat; no video |
| 5 | Bench servo tests (Pi off the lid, Mac USB) | `tools/servo_static_test.py`, then the H13 step test | unloaded in the air, then loaded standing; repeat with the pack at about 7.9 V |
| 6 | Low-pack walks | the same 6 V2.1 walks when the resting pack reads about 7.9 V | gives speed and servo strength against voltage (the `volt` column) |

## Session B (another day, another charge): repeat 1-4 and 6 only. The fit on A is checked against B.

## Ledge (after A; low heights only, G2 never above the floor)

One or two heights are enough (user, 2026-10-07), inside the sim's range (up to 35 mm), for example a book at about 12 mm and one at about 25 mm. Three V2.1 runs into each, tape the end position, note success or failure and where it caught. Logged with `--log-extra`.
Not a climb test; the climb skill is a separate item (B13/H7).

## How this relates to exploration mode (a separate capture)

The exploration sessions ([`../vision/exploration-object-learning-plan.md`](../vision/exploration-object-learning-plan.md)) collect **pictures** for object learning; this plan collects **walk data** for the sim.
They are different sessions with different goals. Exploration walks cross varied floors and make turns and hand interventions, so they are a poor controlled fit; they could serve later as a
robustness check on the fit (different conditions), but only if the walk log is switched on during exploration, which is not wired today. A G2-on visit can do both back to back.

## After capture

1. Fit the servo and body parameters on A (existing `sysid_replay.py` / `sim_vs_real_walk.py`, using only the `imu_n`-fresh rows and the tape distances), check on B; drop anything that does not reproduce.
2. Screen the confident set as one lever at 3M against the control (flat ground no worse, no falls, mirror gap near 0.03), then the sweep across the skill cells and the difficulty ladder.
3. Decide, with the numbers, whether it goes into the 20M run or earlier.
