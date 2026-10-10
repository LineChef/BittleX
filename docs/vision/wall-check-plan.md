# Periodic wall check while exploring (plan, 2026-10-09; recommended, not yet built beyond the dry run)

Goal (user): G2 looks often enough to notice a wall coming, not so often that constant pictures slow everything down. No Claude API call is involved; everything runs on the Pi.

## What exists
- `vision/wall_distance.py`: finds the floor/obstacle boundary row in five vertical strips, converts it to centimetres with a tape calibration (`Calibration`, box at 20/30/40/60/100 cm), says "clear", "blocked" or "nearest N cm, would turn left/right" (near threshold 30 cm).
- `explore_session.py`: the wall estimator reads the interest watch's cheap peek (a camera snapshot that is assessed, not saved, every `G2_INTEREST_EVERY_S`, default 10 s) and only LOGS to `~/.local/share/g2/wall_dryrun.jsonl` (`G2_WALL_DRYRUN`, default on). It never moves G2. The vision avoider is unwired until the user says.

## Recommendation
**Look once per leg, at the stand between legs, and shorten the next leg to what was seen. Nothing continuous.**
1. **When:** at the end of every walk leg while G2 is standing still (7 s legs, so a look about every 8-10 s of motion), plus once at the start of the session and after every turn. A still body gives a sharp picture and the stand already exists, so the look costs no extra stop. A peek is a camera grab plus a few milliseconds of image maths; the picture is not saved.
2. **Why this rate:** at the exploration speed (about 0.05-0.10 m/s) one leg covers 35-70 cm. A look per leg means he never walks farther than he last saw. The current 10 s peek timer is close, but it is not tied to the legs (it can fire mid-stride, blurred).
3. **Leg length from distance:** next leg seconds = min(default 7 s, (nearest cm - 25 cm margin) / speed). Clear beyond 100 cm: full leg. Nearest under about 40 cm: turn toward the open side (the estimator already names it) before walking. Under about 20 cm or "blocked": no forward leg, turn in place, look again.
4. **Cost control:** no look while sleeping, resting or during a picture stop (the survey picture counts as a look); never faster than once per 3 s; the last 20 estimates are kept in memory and only the log line per look is written (a flagged "turn" case also saves its jpeg to a small ring of 10 for review).
5. **Failure handling:** two bad grabs in a row (camera error) keeps the current behavior (short legs of 3 s) and logs it; the wall logic must never block the safe stop.

## Steps
1. Calibrate on hardware (hardware plan block 5): `wd.calibrate()`, box at 20/30/40/60/100 cm; check the logged distances against tape within about 5 cm.
2. One dry-run exploration session with the per-leg look wired to the log only; review the log for false positives (table legs, rugs, shadows, floor seams, tile lines, a person standing).
3. On the user's word only: let the leg planner use the estimate (step 3), first in a cleared room with soft barriers, with the user near.
4. Tests (no hardware): fake snapshots with known boundary rows; the leg planner returns the shorter leg and the turn side; camera failure falls back; the safe stop still works.

Open questions: wall seen at an angle (the boundary is slanted: use the nearest strip); glossy floor reflections; what to do at a step-down edge (the floor ends: the same boundary maths reads far away, so edges need their own cue; not covered here).
