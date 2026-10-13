# High-step creep: training plan and handoff (opened 2026-10-12)

A **separate** walking policy for G2 to switch to when he needs to get onto a ledge: slow, careful, three feet on the ground at all times, trained to step **up** (never down).
The goal is foot clearance; stability is not ranked, but it must not fall on flat ground. It is not V6 and is not trained on top of anything (a fresh chain from S0).
Switching between it and V6 on the Pi comes later. Approved by the user 2026-10-12 (steps 1-5 plus a 20M consolidation, run unattended, decisions made and documented by Claude,
deployment the user's call). This page replaces the "Track C, two modes in one network" path of [`high-step-gait-plan.md`](high-step-gait-plan.md).

## 1. Resume here (new session)

```bash
cd rl_training/opencat-gym
../../.venv/bin/python phase_hs.py status            # one line per step; "HALTED: ..." if it stopped
tail -30 trained/phase_hs.log                         # every state change, with clock times
cat trained/hs_report/decisions.md                    # every judgement call made while unattended
nohup bash ../../tools/hs_watchdog.sh > /dev/null 2>&1 &   # (re)start: the runner resumes from trained/hs_state.json and waits for a run already training
```

- The runner stops itself by writing `trained/hs_halt` (a HALT or a DECISION NEEDED line in the log). Fix the cause, `rm trained/hs_halt`, restart the watchdog.
- A stage that died mid-training halts with "stopped without finishing": move its `trained/hs_<stage>*` files aside (exact paths, never a wildcard over `trained/`), then restart.
- When the log says `HS COMPLETE`: publish `trained/hs_report/report.html` as an Artifact page and give the user the link plus a summary. The candidate is
  `trained/HS1cand_ppo.onnx` (+ `.onnx.json`). Nothing is promoted or deployed.
- Rebuild the report from disk at any point: `../../.venv/bin/python hs_report.py`.

## 2. Why this gait (sim measurements, 2026-10-12)

- **V6's step-up ceiling is about 8 mm (0.32 in)**: success 100% at 6 mm, 85% at 7.5, 35% at 8.25, 13% at 9, 0% from 10 mm (60 episodes each).
- **V6 is limited by its rear legs, not its front.** Its front feet get onto steps up to 15 mm in about a second; the rear paws hit the step face in about 95% of episodes from 9 mm
  and it stalls half up (both rear paws up: 35/40 at 7.5 mm, 17/40 at 9, 11/40 at 10, 1/40 at 12.5, 0/40 at 15). The benchmark's ledge "success" (half the commanded distance in 7.5 s)
  hid this: at 10 mm V6 scores 0 although its front half gets up in nearly every episode.
- **The rear leg's joints are not the limit** (it can raise the paw about 3 in); every gait uses 0.3-0.65 in of it. The rear foot never unloads: G2 carries about 54% of
  his weight at the back, and with no sideways hip joint his body tips onto the lifting rear leg, so the knee folds but the paw stays on the floor (97% contact).
- Trot-based step gaits (Petoi `vtF` made to walk forward) fixed the front feet but not the rear; playing them at the firmware's real cadence helped the rear only a little.
- **A creep (one leg in the air at a time) with sway fixes it**: while a rear leg is in the air the legs on its side straighten and the far side bends, rolling the weight over
  the three planted feet. Open loop: rear paw lift 0.76 in (V6 0.17 in, 4.5x), body 3.09 in (taller than V6), no falls on flat, 0.03-0.04 m/s. On step-ups (open loop, no
  policy) it is the first gait to get all four feet onto 15 mm (5/20; V6 0/20), but it falls often at the edge, which is what the learned correction is for.

## 3. The design

- **Base gait**: `reference_gait/build_creep_reference.py` (a parametric generator: lateral-sequence creep, sway, lean, stride, knee lift; the numbers are chosen by a sim
  parameter search, which the no-LLM-authored-keyframes rule allows). `creep_sweep.py` picks the winner and writes `reference_gait/creep_ref.npy` (+ `.json` with its
  parameters); the runner copies it to `pi_pipeline/gait/creep_ref.npy`.
- **Scorer**: `hs_probe.py` (calm 20 s flat walks: falls, speed, heading, front/rear paw lift, body height, rear knee; a step-up ladder 7.5-25 mm, 15 s episodes, judged foot by foot:
  success = not fallen, all four paws on the top surface, body at least 0.10 m past the edge).
- **Env knobs** (`opencat_gym_env.py`, all off by default; lever `hs_creep` in `g2_profile.py`): the creep base and its cadence (`G2E_SKILL_REF=creep`,
  `G2E_PHASE_RATE_NOM_CMD=0.035`, commands 0.028-0.045 m/s); trot-shaping terms off (foot phase, gait symmetry); stability turned down (upright 3 -> 1.5, rate 0.1 -> 0.05);
  anti-crouch (body floor 74 mm, one-sided; rear-knee posture floor); swing clearance targets front 25 mm / rear 22 mm, one-sided (a higher step is free), weighted so it matters;
  step-ups only (`G2E_FR_LEDGE_UP_ONLY`); 15 s hazard episodes; V6's ledge terms (stall cost halved, progress at the edge, height-scaled crossing bonus, front lift once per episode);
  new: **all four paws up** pays 150 once per episode, **touching the step face** costs 0.5 per step.
- **Pi side** (built, not deployed): `residual_policy.py` reads `base_ref` and `phase_rate_nom_cmd` from the policy sidecar, so the Pi plays the creep exactly as training did
  (test: `pi_pipeline/tests/test_residual_policy_sidecar.py`). Switching V6 <-> this policy by voice is later work (`gait_mode.py` points "hi step" at `hsF` today).

### Bug sweep before training (2026-10-12, 10:30 PM)

- **Fixed: the step-edge clearance target missed the rear paws.** V6's raised target near a step-up switches on by the BODY's position (12 cm before to 3 cm past the edge); the rear
  paws trail the body by about 10 cm, so it had switched off before they reached the edge, and it was set on the paw's centre (about 7 mm above the floor), so "ledge + 6 mm"
  asked for no real clearance. The creep now raises each paw's own target while that paw is within 6 cm before the edge and not yet on top, to ledge height + 13 mm (6 mm under
  the paw). V6's path is unchanged.
- **Fixed: combo episodes run only 3 s** (too short for the creep to reach a step's top): 5% for the creep instead of 15%.
- **Fixed: a flaky V6 test** (unseeded reset sometimes placed an obstacle whose bonus doubled the expected value) that could have failed a preflight at random.
- Checked and fine: chained runs restart checkpoint numbering at 0 (one every 200k, so the tracker's 2M names exist); the preflight replay check rebuilds each episode from its own
  recorded settings; forcing "no hazards" in the scorer really gives a clean floor; the Pi plays the base on the same phase clock as training.
- S0 had started under the runner's old settings (no ledges in S0, so the combo change does not touch it); the runner was restarted at 10:31 PM so S1, S2 and the 20M use the fixed
  settings; S0 kept training.
- Base chosen by the corrected sweep: sway 12, lean 8, stride 10, rear knee dip 42 (`reference_gait/creep_ref.json`). Open loop (no learning): no flat falls, rear paw lift 15.8 mm
  (V6 4.6), body 78.0 mm; step-up success 0.85 / 0.45 / 0.25 / 0.05 at 7.5 / 10 / 12.5 / 15 mm (V6 0.85 / 0.10 / 0.07 / 0.00) with more falls at the edge (0.15-0.65).
  Clips: the "G2 Creep Base Gait" Artifact page.

## 4. The chain (`phase_hs.py run`)

| Step | What | About |
|---|---|---|
| V6 baseline | V6 through `hs_probe` at 0.10 m/s (20 flat walks, 40 episodes per step-up size): the bar | 4 min |
| Base sweep | 36 creep candidates open loop on flat ground, gates below; every passing one gets step-ups at 7.5 / 12.5 / 15 mm; the best score (success + all four up - falls / 4) wins | 15 min |
| Base check | the winner, open loop, full flat + ladder (the "no policy" row of the report) | 3 min |
| Preflight | `preflight.py` on the recipe with the S2 stage: tests, wiring, audits, a 100k smoke run, replay check | 15 min |
| S0 flat | 2M, fresh, 85% flat (small rubble/snags, cutback) | 20 min |
| S1 low steps | 3M from S0, 55% step-ups 0-15 mm (frontier) | 30 min |
| S2 tall steps | 3M from S1, 60% step-ups, frontier floor 8.3 mm, top 25 mm | 30 min |
| Go / no-go | flat-ground safety and posture (mine) | - |
| S4 20M | from S2, 45% step-ups (floor 6 mm, top 25 mm), 35% flat, plateau stop on; a tracker every 2M (10 flat walks, 10 episodes at 10 / 12.5 / 15 / 20 mm) | 141 min |
| Pick + export | the final and the average of the last 5 checkpoints, both scored in full (30 flat, 40 per size); export `trained/HS1cand_ppo.onnx` | 15 min |
| Report | `trained/hs_report/report.html` | 1 min |

Launched about 10:30 PM 2026-10-12; expected done about 5 AM 2026-10-13 (range 4:30-6:30 AM).

## 5. Gates and decision rules (set before the run)

- **Base sweep (round A)**: no falls in 8 calm walks, rear paw lift at least 2x V6's, front paw lift at least 1.5x V6's (relaxed to 1.35x / 1.25x only if none pass; 2026-10-12: rear lift 3x with front 1.0x left only a 1.09x front lift and weak step-ups; ranking all gates together fixed it), body height at least V6's, mean rear knee at least V6's minus 5 deg, speed at least 0.025 m/s.
  Nothing passing halts the runner (the gates are not loosened without a review).
  First run (10:22 PM): round B took only the 4 highest rear lifts, all sway 18 deg, which fall 80-100% at an edge open loop; stopped before any training, re-run with every
  passing candidate in round B and a score that weights all four feet up over falls (training fixes falls, not clearance).
- **Every stage**: flat falls at most 5%, speed at least 0.025 m/s, body at least V6's minus 1 mm, rear knee at least V6's minus 5 deg. A stage failing this is retried
  once with seed 43; a second failure halts before the 20M.
- **Stage step-up targets** (reported in the decisions, not gating; the 20M keeps training step-ups): S1 60% success at 10 mm, S2 50% at 12.5 mm.
- **20M safety**: at 4M, 6M and 10M, more than 25% falls on the calm walk stops the run for review.
- **Pick**: safe on flat ground first, then the highest 80% step-up ceiling, then the mean ladder success, then fewer flat falls.
- **Ledge top 25 mm** (decision): the open-loop creep got all four feet onto 15 mm and its front feet onto 20 mm, and the paw reach is far beyond 25 mm; the frontier curriculum only
  samples a size once the one below passes, so the top limits the ramp without forcing impossible episodes.

## 6. Success criteria (set before the run; the report checks each)

| | |
|---|---|
| Minimum | 80% step-up success at 12.5 mm (0.49 in) |
| Target | 80% at 15 mm (0.59 in), about double V6 |
| Stretch | 60% at 20 mm (0.79 in) |
| Flat ground | at most 5% falls on calm walks, at least 0.025 m/s, no crouch |
| Clearance | rear paw lift at least 2x V6's; front paw lift at least 1.25x V6's |
| Higher than V6 | 80% step-up ceiling above V6's |

## 7. Files

`rl_training/opencat-gym/`: `phase_hs.py` (runner), `hs_probe.py` (scorer), `creep_sweep.py`, `hs_report.py`, `reference_gait/build_creep_reference.py`, `test_hs_creep.py`;
env knobs in `opencat_gym_env.py`; levers `hs_creep`, `hs_s0_flat`, `hs_s1_low`, `hs_s2_tall`, `hs_s4_all` in `g2_profile.py`; `export_onnx.py --sidecar-extra`.
`tools/hs_watchdog.sh` (log `~/g2_logs/hs_watchdog.log`). Run outputs (local, gitignored): `trained/phase_hs.log`, `trained/hs_state.json`, `trained/hs_report/`,
`trained/hs_s*_ppo.zip`, `trained/hs_s4_curve.jsonl`, `trained/HS1cand_ppo.onnx`.

## 8. Open items after the run

- The user reviews the report and decides on deployment. Deploying needs: `creep_ref.npy` and `HS1cand_ppo.onnx` (+ sidecar) on the Pi, and the walk loop loading this policy
  for the hi-step mode (one network per mode; today one network serves every mode). First hardware walks follow the hardware rules: on his feet, hands near, one walk per go.
- Sim caveats: the rear paw scraping up an edge may behave differently on the real floor; the creep's sway relies on knee straightening under load (servo torque on G2).
