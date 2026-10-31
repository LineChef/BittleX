# ARM2 plan: the arm's walking policy for the 0.2 in wide shoulders and CLpaw

Approved 2026-10-31. Goal (user): a policy ready to deploy as soon as the wide shoulder parts and CLpaw are on G2. It keeps the arm, the claw and Petoi's arm
walk; only the legs change. Nothing is promoted or deployed until the user says the parts are installed. The arm's earlier policies (ARM1, ARM1R, ARM1X) and their
hardware results: [`arm-policy-plan.md`](arm-policy-plan.md). The parts: [`../../blueprints/paws-and-wide-shoulders.md`](../../blueprints/paws-and-wide-shoulders.md).

## Decisions (user, 2026-10-31)

| | |
|---|---|
| Recipe | ARM1X's, with what its screens adopted (PPO batch 512 x 5, entropy bonus 0.005) |
| Paw grip | Not varied in training: CLpaw trains with a free pivot; the finished policy is scored at 1.8 and 3.6 mN.m as a check only |
| Servo strength | Not varied |
| Two 20Ms | Both from the same S3 stage, seeds 42 and 7; the better of the four candidates (final and avg5 of each) is picked |
| The 20Ms | Run after the screens and stages without waiting for a go |
| Leg build | A setting, off by default, so a stock-leg policy can be trained again: `G2_BUILD=arm_wide_clpaw` |
| Snags | Kept, fixed for all training (round cords, a measured top per build); see below |
| Final report | ARM2 against Petoi's scripted arm walk on the same legs, as well as ARM1X |

## The simulator

`legs_model.py` builds the leg model from the arm's body model: the four leg servo mounts 5.08 mm further out (track 2.76 to 3.16 in) and a hinged plate on
each foot from `CLpaw.stl` (in the owner's prototypes folder, outside the repo; the folder is set in `~/.local/share/g2/prototypes_dir` or `G2_PROTOTYPES_DIR`):
pivot 4.5 mm above the sole, stops 30 deg toe up and 13 deg toe down, the stock foot showing 1 mm through the sole, 3.3 g a paw (the STL's volume in PETG at 100%).
Collision is the paw's convex hull. About 8 g of shoulder plastic is estimated on the body (not weighed): about 553 g in all. The build's settings and tops are the
`arm_wide_clpaw` entry in `rl_training/opencat-gym/build_limits.json`.

Checked before training (2026-10-31):
- Stock legs are unchanged: a fixed walk in the arm and pod worlds matches the old code step for step (every observation and reward, with resets).
- The paws sit on the feet, swing between their stops and touch the floor; no paw touches G2's own body.
- Training with the paws is 34% slower (7.59 against 5.67 min per million steps): the physics engine's four extra hinged parts and floor contacts. A simpler paw
  hull gained about 6% and changed the shape by up to 0.08 in; not adopted.

Bugs fixed for the new legs: a foot standing on its paw counted as in the air (the slip, clearance and gait rewards read it); four tools used fixed link numbers that
shift when paws are fitted (the benchmark's step-up probe among them); the body's weight scale also scaled the paws; parallel environments could read a half-built model.

## Hazard tops for this build

- **Step-ups: 15 mm kept.** Measured with ARM1X on the new legs: the front paws get onto 10 / 12.5 / 15 mm in 75 / 45 / 5% of episodes (stock legs 85 / 30 / 5%),
  none above; the claw jams from about 20 mm whatever the feet.
- **Snags: size 0.5 (7 mm) for the arm builds.** Cable height = 10 mm x (0.4 + 0.6 x size). The arm walk lifts its feet about 8 mm front, 4 mm back, and
  nothing got over a 10 mm cord.

## Snags (all training, user 2026-10-31)

The snag hazard (a cable across the path) could not be passed at most of its sizes:
- The benchmark ladder did not scale the cable with its size: every rung was the same 10 mm cable, so its snag scores never measured size. The ladder now scales
  snag height and rubble exposure as training does (`benchmark_v5.run_ladder`), so ladder numbers for those two hazards before 2026-10-31 do not compare with later ones.
- Training ramped the cable to 16 mm, which no policy crossed on any build.
- The cable was a square-edged bar; it is now a round cord by default (`G2E_SNAG_ROUND`, 0 = the old bar). Round cords are easier: V7 crossed 10 mm 83% round against
  33% as a bar.

Measured tops (round cords, 12 episodes a size): the pod world (V7 on wkF) crosses 7 / 10 / 13 / 16 mm 100 / 83 / 42 / 0%: top size 1.5 (13 mm), also the default
when no build is set. The arm on stock legs: 5.5 / 7 / 10 mm 67 / 33 / 0%: top 0.5 (7 mm), the same for the new legs.

## Training (unattended runner `phase_arm2.py`)

1. **Baselines** in the new-leg world, 100 episodes a test: ARM1X unchanged, and Petoi's scripted arm walk.
2. **Two 3M screens:** `arm2_ctrl` (the recipe) and `arm2_ev15` (a slope bin counts after 15 outcomes, was 30: ARM1X's slope frontiers waited on evidence).
   Rule, set before the results: `arm2_ev15` is adopted if its flat-ground falls are 0, its mean ladder falls no more than the control's + 0.005, its ladder success
   no less than the control's - 0.02 and its roll no more than the control's + 0.5 deg.
3. **S0 to S3** (9M), fresh, with what was adopted.
4. **Two 20Ms** from S3, seeds 42 and 7, no plateau stop, progress checks every 2M (the snag ladder included).
5. **Pick:** final and avg5 of each 20M scored in full; no flat-ground falls first, then the lowest mean ladder falls. Exported as `trained/ARM2cand_ppo.onnx` with its
   sidecar (`legs: arm_wide_clpaw`).
6. **Verdict** against ARM1X on the new legs, reported only: no flat-ground falls; ladder falls no higher; roll no more than + 0.5 deg; heading no more than + 5 deg and
   under 20; calm-walk speed at least 90%. Then the grip check (the pivot at 1.8 and 3.6 mN.m) and the comparison with Petoi's scripted walk.

Log `trained/phase_arm2.log`; `python phase_arm2.py status`; halt file `trained/arm2_halt`.

## When the parts are on G2

Weigh G2 (a retrain on the real number is offered if he is more than 15 g off 553 g); promote ARM2 for the arm only (`promote_release.py ... --attachment-only`;
`DEFAULT_POLICY` does not change) and deploy with the Pi idle; add a hardware epoch for the new legs. The first walks follow the blueprint's install checklist.

## Results

(filled in as the run goes)
