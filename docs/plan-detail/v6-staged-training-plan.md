# V6 plan: a chain of short skill stages, then a consolidation run (drafted 2026-10-09, NOT approved to launch)

Why: on the same 31-cell benchmark V4 (a chain: two long stages and two fine-tunes) beat V5 (one fresh 20M): mean falls 0.189 against 0.230 (scripted 0.216), with better symmetry
(calm-walk left/right difference 0.5 against 1.3) and far fewer falls on the 10 deg cross-slope, boxes, dense rubble and step-ups at 25-35 mm. V5 was better at the smallest step-ups
(7.5 mm success 0.95 against 0.62) and rubble crossing. Full V5 report: `trained/v5_report/report.html` (local); decision in `../STATUS.md` 0e.

## Decisions so far (user, 2026-10-09)
- The scripted wkF gait stays the base of the policy and the comparison gait. A back-leg-symmetrized wkF was probed in the sim: heading +2.7 deg against +1.3, left/right difference 0.49 against 0.36, mean falls 0.207 against 0.216, so the 1 deg back-leg mismatch is **not** the command-drift source (`reference_gait/build_symmetric_reference.py`, `G2E_SKILL_REF=wkfsym`).
- The unlearned high-step base (`highstep_ref.npy`) is **not** comparable: mean falls 0.366 against 0.216, calm-walk roll 7.2 against 2.5 deg, foot clearance only 13.5 -> 16.4 mm. So it is not the default comparison gait; it can only come back as a mode with a learned correction on top.
- Averaging: the last **5** checkpoints, not 3 (avg3 fixed V5's heading and symmetry; a longer window and a learning rate decayed to near zero at the end).
- Ledges: **falls first, success second**; target step-up and step-down of **25 mm, stretch 30 mm**; the pass gate for ledges lowered (V5's step-up band scored 0.59 against a 0.62 bar for the whole run).
- Progress lines that drive decisions use 40 or more episodes (12 was too noisy).
- V4 stays the deployed default. V5 is not promoted.

## Chain (each stage starts from the previous stage's final weights; the first is fresh, so the whole chain is one new candidate)
S0 flat foundation 2M (flat only, light nudges, strong mirror loss) | S1 terrain skills 3M (rubble, boxes, snags, rough floor, servo faults, shoves; 70% terrain, 30% flat) | S2 ledges 3M (step-up and step-down to 30 mm, 60% ledges, 20% flat, fixed sizes not gated, crossing bonus, imitation relaxed near the edge, a stall penalty at an edge, a foot-clearance bonus at an edge) | S3 slopes 1M (25% slopes) | S4 consolidation 20M (the V5 recipe, mixed). Every stage keeps 20-30% flat walking against forgetting. About 3.5 h in all at V5's pace. **Decision point after S3:** benchmark that checkpoint against V5's 9M line and V4 before spending the 20M.

## Step mode (a gait the user switches on the fly)
- Voice: **"hi step"** (also accept "high step") turns it on, **"walk normally"** turns it off; G2 echoes back ("hi step on" / "walking normally"). The Pi sends the mode to the policy and **blends the base gait** between wkF and the high-step reference over about one cycle on a switch.
- Training: the policy gets a mode input. The simulator sets the mode to high step whenever it **approaches a step up or rubble**; additions proposed: boxes, snags (cable-like), small thresholds (the carpet-to-hard step). Not: slopes, side-hills, step-downs (these need a careful low gait, a different mode later), shoves, flat. The policy must stay safe in **both** modes everywhere, since the user can switch at any moment: about 20% of episodes use the opposite mode, and some switch mid-episode.
- It is a scripted base (the high-step file, like wkF) with the learned correction on top, one network for both modes. The mode input is designed to grow into a choice of gaits (crawl, trot, others) later.
- Sensing: none on G2 today; the user switches it by voice. A later step can let the camera's floor-boundary estimate suggest it.
