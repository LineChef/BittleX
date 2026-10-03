# Sim payload bug (2026-09-23) — what needs re-evaluating

> **Moved verbatim from `docs/project-plan.md` on 2026-10-02** when the plan was trimmed to a roadmap. This is the full detail for
> the payload-inertia sim bug and its follow-up TODO list. Current state is in [`../STATUS.md`](../STATUS.md); the roadmap item is in [`../project-plan.md`](../project-plan.md).

> **⚠️ SIM BUG FOUND (2026-09-23) — much of the resilience testing since 2026-09-02
> needs re-evaluation.** The welded payload bodies (Pi + PiSugar "spine", camera
> "head"; added in `839a7bf`, 2026-09-02, gait-refinement G3) were created with no
> shape, so they had **zero rotational inertia** — which the physics engine treats
> as "cannot rotate". Welded to the torso, they **locked G2's body orientation**:
> roll/pitch/yaw moved ±0.06° while trotting, where a real trotting body rolls ~±4°.
> Fixed (`PAYLOAD_INERTIA="box"`: real inertia from a non-colliding box; `"legacy"`
> reproduces the old behaviour). Payload was on in 90–100 % of training episodes, so
> **every policy since `run20m_ppo` trained on a tilt-locked body**, and every
> payload-on evaluation measured one. Likely affected: the learned gaits' limp (it is
> this artifact), payload-on "0 % falls", stumble-catch / push-recovery and balance
> results, tilt- and IMU-related conclusions (incl. "the 5 Hz IMU costs nothing"),
> heading-hold/drift, slopes and side-hills, and learned-vs-scripted comparisons.
> Bare-robot cells were unaffected.
>
> **TODO — before building on any past resilience result:**
> 1. **Evaluate which past tests and conclusions this likely impacted** — go through
>    the RL logs (`docs/rl/*`, `hardware-gated-backlog.md`, `robustness-backlog.md`,
>    `resiliency-log.md`, `slope-ceiling-log.md`, `gait-friction-log.md`,
>    `resid30-log.md`, `phase4-decision-log.md`, `vision-in-gait.md`) for anything
>    trained or judged with the payload on, and classify each as unaffected /
>    suspect / invalidated.
> 2. **Come up with a list of trainings to re-test** on the corrected sim —
>    including approaches that were closed or reverted because of results measured
>    on the locked body (e.g. `FAC_NOSTALL`, the slope-ceiling rounds, gait-friction
>    rounds, stumble-catch / recovery work, `START_POSE_JITTER`, `FAC_FALL_PENALTY`),
>    prioritized by how much the conclusion depended on body tilt or falls.
> 3. Re-baseline the deployed policy and the scripted walk on the corrected sim
>    (started 2026-09-23; results in `docs/rl/hw1-log.md`).
> 4. **Revisit full fall-recovery in sim at some point (not in scope for the
>    current redesign).** Given how many sim details have turned out wrong
>    since 2026-09-02, the H9 get-up replay's "0/2 recovered" result
>    (`docs/rl/getup-sim-replay.md`) deserves a validated recheck before being
>    treated as settled — it is NOT payload-bug-tainted (the script loads the
>    bare URDF directly, no `OpenCatGymEnv`/payload involved), but it carries
>    its own documented approximations (open-loop, no IMU-triggered waits, no
>    gyro-balance layer, decoded keyframes). For all we know the real get-up
>    commands do work; don't treat the old sim result as final.
>    **2026-09-24 addition:** `models/bittle_esp32.urdf`'s joint limits are
>    ±90° (±1.57 rad) across every joint — confirmed by inspection. A related
>    open-source Bittle X MuJoCo model (`MarcHesse/bittle-mujoco`, found
>    researching community Bittle projects) widened its own limits to ±149°
>    (shoulders) / −70°..+149° (knees) specifically because "OpenCat's own
>    fall-recovery skill commands angles far outside the walking range." If
>    our URDF's ±90° is genuinely too narrow for `rc`'s real keyframes, the
>    sim would be physically unable to represent the recovery motion at all —
>    a concrete, checkable reason the "0/2 recovered" result could be a
>    URDF-limit artifact rather than a real recovery failure. Check this
>    before the eventual recheck: decode `rc`'s actual keyframe angles
>    (`reference_gait/build_skill_reference.py`) and see whether any exceed
>    ±90°.
