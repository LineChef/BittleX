# Learning a new G2 skill — the method

Settled 2026-09-08 after the Phase F climb runs (1–5). This is the standard
recipe for teaching G2 a new motor skill (climb, get-up, a special move). Follow
it; deviate only with a reason written down.

The frozen walk (`run20m_ppo`) is never retrained. Every new skill is a small
**specialist policy** that the `SkillSwitch` swaps in for a second or two, then
hands back — a neural-net payload in place of a keyframe array.

---

## 1. Author a scripted BASE motion

A hand-designed keyframe sequence that captures the **structure** of the skill —
its phases and mechanical logic. It does **not** have to work end-to-end; it's a
scaffold that gets the robot into the configurations from which the hard part is
*learnable*.

- Design it from mechanics, not guesswork. Probe joint→effect signs first (a
  small script: hold `stance + Δ` on one joint group, measure paw x/z, body
  pitch). Reason about the CoM and the support polygon.
- Name each phase for what it achieves ("rear up nose-high", "front anchors on
  the ledge", "rear push", "rear step-up", "settle").
- The scaffold's job is to remove the exploration problem: PPO from a standing
  start essentially never discovers a multi-phase whole-body motion. From a good
  base it only has to *finish and balance*.
- Sanity-check the base **alone** (zero policy action) every iteration: render it,
  confirm it doesn't flip and reaches the setup state. Keep this in the loop.

## 2. Policy = a BOUNDED residual on the base

`joint_target = base(phase) + policy_action · RES_DEG`, position-controlled.

- **`RES_DEG` small** — 20–30°. The base does most of the motion; the policy
  nudges and balances. Too large and an untrained policy overrides the base into
  chaos ("looks frozen / falls over").
- **Small initial action std** — `log_std_init ≈ −1.4` (std ~0.25). Early in
  training the residual is near-zero, so the base executes cleanly and the policy
  learns gentle corrections from a good starting point instead of thrashing.
- The policy's real value is **closed-loop balance** — it takes the IMU every
  tick, which is the one thing the open-loop keyframe can't do.

## 3. Build the right sim challenge

A narrow task env (standalone PyBullet — do **not** subclass the walk env).

- Domain-randomise the thing that matters (ledge height, obstacle type/shape).
- **Curriculum**: start easy enough that there's positive signal, ramp difficulty
  over the first ~half of training (a `BaseCallback` that calls an env setter).
- Spawn in the pose/velocity the walk actually hands off in.
- **Don't stack two unsolved problems.** If the skill needs perception, feed it
  **ground-truth** from the sim for the first runs. Prove the motion is
  learnable, *then* wire the real detector.

## 4. Iterate on the REWARD — this is most of the work

Watch what the policy actually does, name the failure mode, change one thing,
rerun, write a one-line update. Hard-won rules:

- **Don't penalise per-step the thing the skill needs.** A heavy per-tick body-
  pitch penalty made the climb policy refuse to lean → it did nothing. Make
  aversive states **terminal-only** (big penalty for an actual flip) or gate
  them (free up to a threshold).
- **Kill the do-nothing optimum.** "Stand still and stay safe" will win if it
  can. Add an anti-stall penalty / require forward progress / end the episode on
  a long stall.
- **Intermediate rewards get hacked.** Examples we hit: a "front feet on the
  ledge" bonus → policy parks there; an asymmetric-clipped "height-gain" term →
  policy oscillates the feet to farm it. Prefer **potential-based shaping**:
  `R += SCALE · (Φ(s′) − Φ(s))` where `Φ` is negative distance-to-goal. It
  telescopes over the episode, so per-step up/down gaming cancels — only net
  progress toward the goal pays.
- **Trust the eval, not the training curve.** If `ep_rew_mean` rises while a
  deterministic eval gets *worse*, that's reward hacking. Every iteration: run
  `eval_climb.py`-style N-episode deterministic eval + render the best episode.
- Big **terminal bonus** for the true success state; big **terminal penalty**
  for the failure state.
- Change ideally one reward knob per run; keep the runs short (300k–1M steps,
  ~5–15 min) so iteration is cheap.

## 5. Deploy

Export to ONNX (`export_onnx.py`-style). Add a `GaitMode` for the skill; the
`SkillSwitch` runs `skill_policy.predict(obs)` in place of a keyframe, via-stance
blend in/out, walk paused then resumed. On the Pi it's a second ONNX file; the
switch picks which net feeds the servos. Sub-ms either way.

---

## Checklist per iteration

1. Zero-action base render — sane? not flipping?
2. Train (short run, curriculum, one reward change).
3. Deterministic N-episode eval + render the best episode.
4. Name the failure mode. One-line update: last result + what's changing.
5. Repeat until it does the skill, or the evidence says the sim/mechanics can't.

Harnesses: `climb_env.py` / `train_climb.py` / `eval_climb.py` / `climbwatch`
(Phase F) are the template. `climb_test.py` is the keyframe-base authoring +
scoring tool.
