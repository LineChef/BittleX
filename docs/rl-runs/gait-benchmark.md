# Gait Benchmark — Learned vs. Scripted

Head-to-head of the RL-trained gaits against Bittle's built-in `wkF` walk
keyframes, on the same obstacle course. Run with
`rl_training/opencat-gym/benchmark_gaits.py` — both gaits run inside the training
env with matched per-episode RNG seeds, so episode *N* is the identical course
(same obstacle scatter, same shoves, same physics) for every gait. Metrics from
`evaluate_policy.py`.

**The scripted gait here is open-loop keyframes** (each step it steers the joints
toward the current `wkf_ref.npy` frame). The real firmware adds a tuned
gyro-balance layer on top, so real-hardware scripted performance is **≥** what's
shown here — its obstacle robustness in particular is understated. The definitive
comparison is on the robot.

Difficulty sweep: flat / 20 mm / 35 mm / 50 mm scattered obstacles, with a light
push that scales with the terrain. 12 episodes per cell.

## Results (2026-08-31, sim)

Winner per row: fewer falls, else more forward distance.

| Gait (learned) | flat | 20 mm | 35 mm | 50 mm |
|---|---|---|---|---|
| **`phase3-gait`** (fast flat walker) | **learned** — 1.28 m vs 0.30 m (~4×) | scripted — learned falls 17% | scripted — learned falls 33% | scripted — learned falls 33% vs 8% |
| **`gait-v7-stumble-catch`** (crisp trot + balance-catch) | **learned** — 0.38 vs 0.30 m | **learned** | scripted — learned falls 8% | ~tie — both 8% |
| **`walk-v8-r2`** (Run 7, cautious) | ~tie — scripted slightly faster | learned edge on distance | ~tie | scripted — learned falls 17% vs 8% |

## What it says

1. **On flat ground the learned gaits win** — decisively for `phase3-gait`
   (~4× the forward distance of open-loop keyframes). This is the clean
   "RL beats scripted" case: an efficient, fast walk that no one hand-authored.
2. **On obstacle courses the scripted keyframes are hard to beat.** They're low,
   slow, conservative, and well-tuned — a robust default. None of the learned
   gaits clearly wins on obstacles; `phase3-gait` does markedly *worse* (it's
   optimised for flat speed and is brittle — high roll variance, trips easily),
   and even the balance-tuned `gait-v7-stumble-catch` only reaches parity.
3. **Why:** the traits that make a learned gait good on flat (speed, long
   committed strides) are the ones that make it trip on obstacles (momentum, less
   recovery margin). Runs 5–7 tried to train obstacle robustness in and hit the
   reactive-recovery ceiling. The scripted gait's virtue is simply that it's a
   careful repeatable pattern.
4. **Caveat direction matters:** adding the firmware's gyro-balance layer would
   make the *scripted* numbers better, widening its obstacle lead. The learned
   gait's flat-speed lead is real and should mostly survive sim-to-real.

## Implication

RL locomotion **clearly earns its place for flat-ground efficiency**. It does
**not** currently beat a well-tuned scripted gait for obstacle robustness — and
may not, without perception in the loop (see the Phase 8 "Target capability" and
`docs/behavior-ideas.md`). A sensible split: a fast learned gait for open ground,
fall back to the scripted walk (or a slower learned one) in clutter, until a
vision-fed policy can do better.

Re-run on hardware with the real firmware gait before drawing final conclusions.
