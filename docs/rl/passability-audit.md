# Passability audit: the hardest course must stay passable

## Standing rule (user, 2026-10-08)

**Difficulty never ramps above what a capable policy can pass.** Every hazard category (terrain, ledge, slope, fault, and any added later) has a top threshold, found by measurement: the largest magnitude that the best available policy passes at least half the time. The difficulty ramp is limited to that threshold, so no level, hard-scale factor or combination of hazards can produce an impossible episode. "Very hard but passable" is the target for the top of the ramp; "impossible" is a bug.
Apply this to every new hazard, every change to a hazard's range, the level ceiling and the hard-scale factor: measure with `rl_training/opencat-gym/passability_audit.py` before the change goes into a run, and keep the limits in `g2_profile.py` (the `G2E_CAP_*` settings). A floor bug that puts a wall in front of G2, or a start pose inside the ground, is treated the same way as an over-hard setting: it is an impossible episode, and it is fixed before the next run.

## Why (2026-10-08)

The surface-transition floor was built from two slabs, each tilted about its own centre, so any ground tilt left a wall at the junction (11 cm at 3 deg, 29 cm at 8 deg). About one training episode in six or seven carried it, from the course stages on, including the 20M run. The user saw it as an impassable ledge. The audit below exists so a bug like that is found by a test, not by eye.

## The audit (`rl_training/opencat-gym/passability_audit.py`)

- **Part A, geometry** (`geometry`): no policy. For each hazard at a pinned level (1.0 and the 1.25 ceiling, with hard levels x1.10), generate 300 episodes with the training sampler and scan the lane ahead with rays: the forced rise (smallest wall that must be climbed in the next 1.2 m over three lanes), the ground tilt, and whether the body overlaps the ground at the start.
- **Part B, capability** (`capability`): the best policies (V2.1, K3, the 20M) against each hazard at rising magnitudes (side-hill 4-20 deg, climb 8-30 deg, descent 8-24 deg, ledge 2.5-8 cm), 20 episodes per cell; success = stayed up and covered at least half the commanded distance. The top threshold of a family is the largest magnitude the best policy passes at least half the time. Results: `trained/passability_capability.json` (local). Runs when the Mac is idle.
- **Scene checks** (`scene`): floating or sunk obstacles, obstacles on the start, overlaps.

## Results so far

- Geometry after the junction fix (300 episodes each): forced rise at most 3.5 cm (level 1.0) and 4.3 cm (1.25) for ledges alone, 6.1 cm worst case in combinations (a ledge plus a tilt); terrain at most 1.6 cm; ground tilt up to 23.9 deg at level 1.0 and 29.9 deg at 1.25.
- Scene checks (`scene`, 100 episodes per generator at levels 1.0 and 1.25, every generator forced on): the robot is never inside the ground by more than 1 cm at the start (0.0% in all 16 cases), it stands 0.6 cm above the floor (a step-down start is higher by design), and no static object floats. Nothing in the ground was found: an earlier "buried start" figure (5-12% on steep slopes) came from measuring the welded payload box, which has collisions switched off; with it excluded the worst ground overlap on a 30 deg slope is 0.5 cm (0.0 cm after the start-height lift). Rubble and snag blocks sit partly below the floor surface by design (only the exposed height counts), so "sunk" objects there are not a bug. One small item remains: with every generator on at once, 1% (level 1.0) to 2% (level 1.25) of episodes start with an obstacle overlapping the robot by more than 5 mm.
- The capability results and the resulting limits are added here once Part B has run (it waits for an idle Mac, after the 20M and its reports).
