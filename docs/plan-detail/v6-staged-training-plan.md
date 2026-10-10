# V6 plan: a chain of short skill stages, then a consolidation run (approved 2026-10-09 with the user's changes; RUNNING since 6:49 PM)

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
- Training: the policy gets a mode input. The simulator sets the mode to high step whenever it **approaches a step up or rubble**; the user approved adding boxes, snags (cable-like) and small thresholds (the carpet-to-hard step) to those two. Not: slopes, side-hills, step-downs (these need a careful low gait, a different mode later), shoves, flat. The policy must stay safe in **both** modes everywhere, since the user can switch at any moment: about 20% of episodes use the opposite mode, and some switch mid-episode.
- It is a scripted base (the high-step file, like wkF) with the learned correction on top, one network for both modes. The mode input is designed to grow into a choice of gaits (crawl, trot, others) later.
- Sensing: none on G2 today; the user switches it by voice. A later step can let the camera's floor-boundary estimate suggest it.

## Added later the same evening
- **Gait switching from any mode** is built (`pi_pipeline/gait/gait_mode.py`): one shared state file read by the voice service, the exploration session and the walk loop; "hi step" / "high step" and "walk normally" work in the voice loop and in an exploration session; a short double beep (speaker and buzzer) plays when a gait really switches; a policy whose sidecar has no `"modes"` key (V4, V5) refuses the switch out loud and changes nothing. The 80 Hz loop will read the mode and blend the base only when the mode-trained policy exists.
- **Training go/no-go delegated (user, 2026-10-09):** the call to run the consolidation 20M is Claude's, after the checkpoint benchmark at the end of S3; promotion and deployment of a result are NOT delegated.
- **Ladder probes, corrected** (the first run did not apply the probe gait to the ladder; fixed): the unlearned high-step base makes step-ups fall less (0.05 at 22.5 and 30 mm) only because it never gets over them (success 0.00 at every size, against scripted's 0.47 at 7.5 mm), and step-downs fall 1.00 from 15 mm. It lifts only 3 mm more at the 90th percentile (13.5 -> 16.4 mm). A symmetrized scripted base gives the same ladders as scripted. So any gain on ledges has to come from a learned correction on top, with the imitation penalty relaxed, and a taller high-step reference (`build_highstep_reference.py --shoulder 14 --knee 24`) is the next thing to probe for clearance.

## Foot-clearance probe, both rounds (open-loop base gaits in the sim, no policy; `rl_training/opencat-gym/gait_probe.py`)

| Base gait | Clearance p90 | Calm-walk roll | Calm-walk speed | Calm-walk falls | Boxes falls | Rubble falls | 15 mm ledge falls |
|---|---|---|---|---|---|---|---|
| wkF (scripted) | 13.5 mm | 2.5 deg | 0.091 | 0.00 | 0.08 | 0.06 | 0.04 |
| A (+20 sh, +32 kn, rear x1.35) | 20.2 | 15.6 | 0.034 | 0.65 | 0.13 | 0.15 | 0.58 |
| B (+26, +42) | 25.5 | 19.2 | 0.021 | 0.91 | 0.42 | 0.29 | 0.57 |
| C (+32, +52) | 27.5 | 20.8 | 0.011 | 0.89 | 0.31 | 0.17 | 0.32 |
| D (+14, +40, rear x1.0) | 16.9 | 6.3 | 0.050 | 0.01 | 0.00 | 0.00 | 0.15 |
| E (+20, +32, rear x1.0) | 17.1 | 9.9 | 0.040 | 0.17 | 0.05 | 0.08 | 0.50 |
| F (+8, +46, rear x1.0) | 17.8 | 6.8 | 0.040 | 0.04 | 0.01 | 0.01 | 0.00 |

- The back-hip boost (x1.35) was the main source of the sway: without it and with the lift moved from the shoulders to the knees, D and F are stable (roll 6-7 deg, flat falls under 5%) and clear boxes and rubble better than scripted.
- No base gait crosses a ledge on its own (success 0.00 at every size for A-F; the stable ones also walk at under half the commanded speed). The tall ones that reach 25 mm of clearance (B, C) are not walkable open loop.
- So the **hi-step mode base is F** (`hsF_ref.npy`: stable, 17.8 mm, best on obstacles) with the learned correction supplying the rest of the lift and the speed; chain 1 stays on the scripted wkF base.
- The unlearned symmetrized wkF gives the same results as wkF (`wkfsym_ref.npy`), so the back-leg mismatch is not the command-drift source.

## Status log (2026-10-09 evening) -- runner `rl_training/opencat-gym/phase_v6.py`, log `trained/phase_v6.log`, state `trained/v6_state.json`, watchdog `tools/v6_watchdog.sh`
Resume: `cd rl_training/opencat-gym && ../../.venv/bin/python phase_v6.py status`; if the watchdog is not running and `trained/v6_halt` does not exist: `nohup bash ../../tools/v6_watchdog.sh > /dev/null 2>&1 &`. A halt is my own review point (the user delegated the 20M call): read the halt line, decide, `rm trained/v6_halt`, restart the watchdog. Never type the runner's or a tag's process text in a shell command (`pgrep` matches your own shell).

| Stage (steps) | Result (40 episodes per cell, 20 per ladder size) |
|---|---|
| S0 flat, 2M | flat falls 0; speed 0.103; heading 16 deg; asymmetry 1.3; ladder falls 0.07; crossing 0.31 |
| S1 terrain, 3M | rubble and snag cells 0.00; slopes got worse (no slope episodes): 10 deg cross-slope 0.97; heading 16, asymmetry 1.2 |
| S2 ledges, 3M, **first attempt** | loophole: falls fell (step-up 0.15/0.00/0.05 at 15/22.5/30 mm) but success 0.00 above 7.5 mm and 0.15 at 7.5 mm. The per-step paw-lift bonus cancelled the stall cost (hover with a paw raised). Kept as `trained/v6_a1s2_*`, score `trained/v6_a1_score_s2.json` |
| S2, **second attempt** | lift bonus paid ONCE per episode (20), stall cost 2, ledge sizes start at 2.5 / 10 mm: 7.5 mm step-up success 0.65 (scripted 0.47), 15 mm step-down 0.00 falls / 1.00 success (scripted 0.05 / 0.95); 15-30 mm step-ups fall 0.45-0.70 (they try, none crossed); calm walk heading 13, asymmetry 0.5, roll 2.4 |
| S3 slopes, 1M | mean falls over 31 cells 0.293 (V5 0.230, V4 0.189); flat 0; heading 15, asymmetry 0.8; 7.5 mm step-up success 0.60 |

**S3 go/no-go (2026-10-09 8:31 PM, my call):** the rule (mean falls at most V5's + 0.03 = 0.26) failed by 0.03, I overrode it: the shortfall is forgetting on uphill (0.50 against V5 0.00), servo fault plus uphill, snags and moderate rubble, which the 20M's mixed course retrains; flat falls none, symmetry and heading good, no avoidance. The 20M (`v6_s4`, from S3, plateau stop on, 25% ledges, stall cost 2) started 8:31 PM, due about 10:56 PM; then the average of the last 5 checkpoints, export `V6cand_ppo.onnx`, report `trained/v6_report/report.html` and `compare.txt` (V6 / V5 / V4 / scripted), about 11:20 PM. If the 40-episode lines show step-up success below 0.4 at 7.5 mm or flat falls, I intervene. Promotion and deployment stay the user's.
