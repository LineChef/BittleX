# Carpet gait: what was tried and learned (2026-10-20)

One day of work on getting G2 (with the pod payload) to walk on carpet. **Result: no gait yet walks on the real carpet.** This page keeps what was measured so none of it is rediscovered. Where things stand now: [`../STATUS.md`](../STATUS.md). The trainer and its levers: [`training-pipeline.md`](training-pipeline.md).

## The floor and the failure

- Carpet: about 1/4 inch cut pile on a springy cushion pad; a fingertip presses in about 1/4 inch. Hardwood for comparison.
- **V7 (the deployed trot) fell on 6 of 6 first steps**, always to G2's **right**, in 1 to 1.5 s, at 0.10 and 0.05 m/s, with the firmware balance on or off. (The firmware balance does not act during a policy walk, so it made no difference.)
- On hardwood V7 had 0 falls in 23 walks, with a first-step right lean of about 9 degrees that it recovers from.
- Mechanism, from rear, front and side video: as the left legs lift, the weight goes onto the right pair, which sinks into the pile, and the tall pod carries the body over. **On carpet the give under a loaded foot makes the weight shift much larger than on hardwood.** (Owner's observation, which fits all the data.)
- Petoi's own `kcarpetF` also fell to the right with the pod on its first try (about 2 s).

## The sim carpet model

`CARPET_PAD_*` in `opencat_gym_env.py`: the flat floor becomes a soft spring (contact stiffness K, damping C, grip mu) over a hidden hard plane `DEPTH` below. `carpet_fit.py` scores any policy on any carpet setting in closed loop.

- Fit that reproduced V7's falls (all to the right, about 95%): K 120, C 2, depth 12 mm, mu 2.2, with servo strength 0.10 (the calibration's 0.15 is too strong: replayed hardwood first-step roll was 4.8 vs the real 8.8 degrees) and the pod 8 mm to G2's right.
- The sim falls about one stride later than the real G2 does.
- **Bug fixed on the way:** the elbow-contact penalty counted a lower leg sinking into the pile (-4.9 a step for V7 just standing on carpet); only the floor under the pad counts now.
- **Adaptive carpet level (`CARPET_ADAPT`)**: a per-environment difficulty 0 to 1 from a near-hard floor (K 1000, 6 mm, mu 1.0) to harsher than the fit (K 80, 14 mm, mu 2.6). Success means staying up AND covering half the commanded distance; the level rises at 70% success and falls at 40%.

## What was measured in the sim (short probes, 0.5M to 3M steps, 24 walks per score)

- **Grip, not softness, breaks the policy.** The same V7-chain policy: 0% falls at K 120 / 12 mm with grip 1.0, 62% at grip 1.3, 92% on a stiff carpet at grip 1.3. A scrubbing stance paw drags the body sideways.
- **What helped:** swing clearance 30 mm (`PAW_Z_TARGET` 0.030, `FAC_CLEARANCE` 0.3), then a **grip staircase** (train on easy carpet first and raise the grip in stages), then the adaptive ground. Best sim policy: `probe_adapt3m`, on a medium carpet 17 to 33% falls and 40 in walked in 12.5 s (hard floor 0 to 4%).
- **What did not help:** a scrub penalty, more exploration noise, a looser imitation anchor, a lower ride height, a half-speed command, a stronger recover reward (`CARPET_BALANCE_SCALE`), soft-footfall and body-bounce penalties on the V7 base, softer or deeper pads.
- **Noise is large.** The same recipe scored 21%, 67% and 38% falls on the fitted carpet in different runs. Treat a single 24-walk score as plus or minus 20 points; repeat before believing it.
- **The fitted carpet stayed at 50 to 80% falls** for every policy. Even walks that did not fall covered under 10 in.

## What was measured on the real carpet

| Walk | Result |
|---|---|
| V7, 6 walks (balance on and off, two speeds) | all fell right in 1 to 1.5 s |
| `adapt3m` carpet policy, 3 walks (0.10, 0.10, 0.05 m/s) | tilt past 45 degrees at 1.0, 1.6, 1.6 s; right, left, right |
| Stall-model policy (`astall3mb`), 1 walk | stepped in place, slow lean to the left, over at 3.4 s (longest so far, never walked) |
| Scripted walk with longer, higher strokes (knees x1.6, shoulders x1.3) | fell right at 1.4 s |
| Scripted crawl (one leg at a time, order FR, BL, FL, BR; `creepfr_ref.npy`), **held by hand** | completed 10 s and **propelled him across the carpet** (owner's observation); IMU log sparse |
| Petoi firmware `kcarpetF`, **held** | 10 s, roll within about +/-10 degrees, heading turned 35 degrees; **promising but the body bounced a lot and the payload travelled a lot** |
| Open-loop replay of Petoi's carpet reference (`carpet_ref.npy`) | worse than the firmware gait and stopped walking forward: the replay is not the firmware gait |
| `kcarpetF` three runs after the replay tests | G2 only stood and rested (roll +/-2 degrees); the board was probably left in joint-command mode; power-cycle the BiBoard before firmware-skill tests |

**No walk with the weight fully on G2's feet stayed up past 3.4 s.** Every hand-held run is excluded from "it works": the hands damp the roll.

## Sim versus real: what the dial-in found

- **Open-loop replay of the logged joint commands** (`replay_carpet.py`) is almost blind to the pad settings: tip times were the same for every stiffness, depth and grip. Only servo strength moved the match. Not a usable fit.
- **A flat weak servo (0.06) with the pod 16 mm right** made the carpet policy fall as fast as the real G2 (96% at 1.5 s), but a policy cannot be trained there: it fails even on a hard floor, where the real G2 walks. So it stood in for something carpet-specific.
- **Carpet stall (`CARPET_STALL`, new)**: a stance leg loses that fraction of its servo strength while its paw is in the pad. Stall 0.7 at normal strength reproduced the real fall time (67% at 1.9 s) with the hard floor untouched. **Policies trained under it learn to stand still** (0 in walked): fixed-stall runs, and runs where the stall grows with the carpet level, all ended standing or falling. The stall model is a hypothesis, not a measurement.
- A deeper, softer pad (25 mm, K 30) got closest to the real timing without stall (100% falls at 2.9 s); training on it did not help.

## What was tried as a different base gait

- **The scripted crawl** (`reference_gait/build_creep_reference.py`, the offsets re-ordered): worked as an open-loop test when held; a training probe on it was started and cancelled early, so **no crawl policy was ever scored**.
- **Petoi's carpet reference as the imitation base** (`G2E_SKILL_REF=carpet`) with body-bounce, soft-landing and stronger tilt penalties: 100% falls, 0 to 1 in walked, carpet level stuck at 0. A policy imitating that reference does not learn to walk on it in the sim (it walks in place there too).

## Ideas that were not tried

1. A crawl-based **policy** (the scripted crawl is the only thing that moved him, if held), with the carpet's give modelled so the weight shift is realistic.
2. A smaller, slower weight shift in the scripted crawl (less sway, a longer cycle), tested free with a spotter.
3. Playing Petoi's gait through the firmware (as carpet mode now does) and tuning only what the firmware allows; the bounce is the thing to reduce.
4. Measuring the carpet directly: how far each paw sinks under G2's weight, and the leg servo load while walking, instead of inferring it from falls.
5. Anisotropic friction on the paws in the sim (PyBullet `anisotropicFriction`), to model a paw that grips sideways but slides forward.

## Tools and knobs added (all in `rl_training/opencat-gym/`, uncommitted unless noted)

| What | Where |
|---|---|
| Carpet pad, servo-strength and pod-offset draws, adaptive level, stall | `opencat_gym_env.py` knobs `CARPET_*`, `MOTOR_FORCE_LO`, `POD_RIGHT_MAX`, `CARPET_STALL` |
| Short-probe runner (variants, fixed or adaptive carpet, scored on four carpets) | `phase_probe.py` (`run NAME...`, `show`) |
| Closed-loop carpet scorer | `carpet_fit.py` |
| Open-loop replay of real logs | `replay_carpet.py` |
| Chain runner for the carpet ground (round 1) | `phase_carpet.py` |
| Carpet mode on G2 (committed): "G2, carpet mode" plays Petoi's firmware carpet gait; "G2, switch to default gait" goes back | `pi_pipeline/gait/gait_mode.py`, `policy_walker.py`, `fw_skill_log.py` |

Real-walk logs of the day (raw CSVs) are kept on the dev machine, not in the repo.
