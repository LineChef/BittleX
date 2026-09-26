# Get-up sim replay (H9) — 2026-09-10

The hardware-gated backlog's one **do-now** item for self-righting: replay the
firmware get-up keyframes in PyBullet and see whether they *plausibly* work,
before the real robot is here to test them.

Script: `rl_training/opencat-gym/reference_gait/verify_getup_reference.py`
(`python verify_getup_reference.py --gif --sheet`). Outputs in that folder:
`getup_prone_flat.gif`, `getup_supine.gif`, `getup_contact_sheet.png`.

## What was replayed

- **`rc`** ("recover") — the firmware self-right for a side / front fall.
- **`rl`** ("roll") — flips a supine robot onto its side; firmware then chains
  `rc`. So supine = `rl` → `rc`.

Both decoded from `InstinctBittleESP.h` by `build_skill_reference.py rc rl` →
`rc_ref.npy` / `rl_ref.npy`, (100, 8) rad, URDF joint order. Driven open-loop
through the 8 leg joints via `POSITION_CONTROL` (`FORCE = 0.40` N·m/joint, above
`verify_wkf`'s 0.2, in the spirit of Run 6's torque boost).

## Result — 0 / 2 recovered

| fall state | start \|roll\|/\|pitch\| | end \|roll\|/\|pitch\| | end z | verdict |
|---|---|---|---|---|
| prone, belly-down flat | 0.00 / 0.00 | 0.00 / 0.00 | 0.022 m | **no** — `rc` reaches a transient 4-leg crouch mid-play (tilt-sum hits 0.0) then collapses flat again |
| supine, on its back | 3.14 / 0.00 | 3.02 / 0.07 | 0.030 m | **no** — `rl` → `rc` flails the legs; the roll-over never happens, ends still on its back |

## Why this is expected, and what it does / doesn't tell us

The replay is a **crude lower bound**, and a poor result was the predicted
outcome, not a surprise:

1. **The refs are approximate.** `rc`/`rl` decode as *behaviours* — 5–6 keyframes
   resampled to 100, with the per-frame timing params dropped and the
   **IMU-triggered mid-sequence waits removed** (`skill.h` `imuException`
   checks). The real skill is not a smooth 100-step interpolation.
2. **Open-loop.** On the real robot `rc` runs *with the gyro-balance layer
   active* (`gyroBalanceQ`), which is exactly what would hold the transient
   stand that `rc` reaches in the prone case. The sim replay has no such loop.
3. **No stable side-lie or nose-down rest in this URDF** (measured: a mild tip
   flops back belly-down; anything past ~1.1 rad roll goes fully supine). The
   real Bittle rests stably on its flank / face — the poses firmware `rc` is
   actually designed for. The sim can only present "belly-flat" and "supine".
4. **Bare `plane.urdf`** — no carpet-like friction/compliance for the feet to
   push against.

**Takeaway for the hardware plan (H9 / project-plan.md "Recovery"):** the sim
cannot validate the firmware get-up — it neither confirms nor rules it out.
Treat `krc` / `krl` as *unverified* on arrival:

- enable gyro assist (`g`) first — the prone-case transient stand suggests `rc`'s
  posture is roughly right and just needs the balance loop to hold it;
- test stock `rc` / `rl` against the fall types real RL sessions actually
  produce, and expect to re-author them in Skill Composer;
- a fall-orientation classifier (IMU roll/pitch → which recovery) is still
  needed — `RecoveryFSM` in `pi_pipeline/link/recovery.py` is the seam.

Consistent with the standing conclusions: no roll-axis DOF (learned self-right
impossible, Run 6), firmware self-right covers slow falls only, and contact-rich
scripted skills hit a sim-fidelity wall in PyBullet (cf. the `cmh` climb, Phase
F). See `docs/hardware/self-righting.md`.

## Re-run after the joint-limit fix (2026-09-24) — still 0/2, but a real change

Two fixes landed the same day, found reviewing community Bittle/Petoi projects
(`docs/research/community-projects.md`): `models/bittle_esp32.urdf`'s joint
limits were too narrow for `rc_ref.npy`'s real keyframe range (confirmed by
direct comparison — shoulders need −176°/+36°, hips need 30°/200°, the URDF
only allowed ±90°/114.6°), widened to match. Also found and removed a second,
independent bottleneck in this script itself: a hardcoded `BOUND = ±115°`
clamp was silently truncating every keyframe on top of the URDF's old limits.

**Result: still 0/2 recovered, but the `supine` case changed meaningfully.**
Old result: supine barely moved (start roll 3.14 → end roll 3.02). New
result: supine **fully rolls from on-its-back to belly-down flat** (end roll
0.00), visually confirmed via the contact sheet — a real physical roll-over
the sim previously couldn't even execute, not just a numeric wobble. `prone_flat`
looks essentially unchanged (still reaches a transient raised crouch, still
collapses flat again). Neither case ends standing (both end at low `z`), so
the headline verdict doesn't flip — but the failure mode changed from "can't
physically reach the pose" (range artifact) to "reaches real intermediate
poses, doesn't complete the transition to standing" (a different, more
credible kind of gap).

**Speculation on what's still missing (2026-09-24, not verified):**
1. **No active balance correction.** The real `rc`/`rl` runs with the
   firmware's gyro-balance layer (`gyroBalanceQ`) active throughout; this
   replay is fully open-loop. The transient poses reached (prone crouch,
   supine mid-roll) both look like genuinely unstable balancing acts — the
   balance loop is plausibly what holds them long enough to continue on
   real hardware.
2. **Removed IMU-triggered mid-sequence waits.** The real skill pauses until
   the IMU confirms a target orientation before advancing; this replay plays
   through at a fixed cadence regardless of actual state, which could start
   later phases from the wrong pose if timing drifts.
3. **This script still doesn't use `SERVO_RATE_LIMIT_DEG_S`** — it kept its
   own unconstrained `maxJointVelocity` (~1800°/s pre-existing value, not
   the 137°/s ceiling now in `opencat_gym_env.py`). The new supine result
   could be partly relying on unrealistically fast joint response; adding a
   realistic speed cap here is untested and could make the result worse,
   not better. Real open item, not yet checked.
4. Lower-confidence: the `FORCE = 0.40 N·m/joint` budget was tuned for a
   different context (Run 6's torque boost), not verified sufficient for
   recovery-specific exertion; ground friction/compliance vs. real
   carpet/floor; general contact-solver fidelity for fast multi-point
   contact events; this replay is still bare-robot, no payload.

Next concrete step if this gets picked back up: try a crude closed-loop
balance correction (same shape as `BalancedLearned`'s proportional tilt nudge
elsewhere in this codebase) before chasing torque or friction numbers --
that's the change most likely to address the failure mode actually observed.

## Follow-up testing session (2026-09-24) — six interventions tried, all negative; root cause pinned down

Exploratory edits to `verify_getup_reference.py` in the working tree only —
**nothing from this section was committed.**

| # | Intervention | Result |
|---|---|---|
| 1 | Balance correction (`--balance K`, same shape as `BalancedLearned`), swept k=0.3/0.6/1.0, plus a pitch-only variant | No improvement; higher k actively worse (broke `supine`'s previously-clean roll). A tilt correction nudges toward *level*, which lying flat already satisfies — no mechanism to push toward *height*. |
| 2 | Wait for joint convergence before advancing each keyframe (proxy for the dropped IMU-triggered waits) | Identical to baseline — the robot was already converging fine within the original timing; never lagging. |
| 3 | Torque budget, `FORCE`=0.4/0.6/0.9/1.2 N·m (up to 3x) | No change at all. |
| 4 | Ground friction, 1.0/2.0/4.0 | No meaningful change — max height reached is friction-insensitive. |
| 5 | `PLAY_CYCLES`=1/2/3, and holding the final pose 200 extra steps | No change — rules out "the loop drags it back down." |
| 6 | Slowdown (HumanUP-style 2x/4x/8x), same path played slower | No change — that technique fixes a *policy-discovered* trajectory that's unstable at speed; ours is a hand-decoded reference that doesn't trace a "stay standing" path regardless of speed. |

**Root cause, found via a frame-by-frame trace of `supine`** (`rl` = frames
0-99, `rc` = frames 100-199, chained): the reference *can* reach a genuinely
good near-standing pose — twice, independently — and loses it at two
specific points, not from any variable above:
- **The `rl`→`rc` handoff (frame ~90→120):** `rl` alone climbs `z` from 0.03
  to 0.088m with roll/pitch near zero by frame ~85. `rc`'s opening frames
  assume their own starting pose (a fresh fall) and drag the robot back
  down to `z≈0.022` by frame ~120 — the decode chains the two skills'
  frames without reconciling their assumed start/end states.
- **`rc`'s own tail:** independently climbs back to `z≈0.088` by frame
  ~180, then collapses by its own final frames (~185-195) — not a looping
  artifact (ruled out by #5), `rc`'s decoded sequence just doesn't end
  standing.

So no adjustment to open-loop replay can fix this — the reference
trajectory itself doesn't trace a path that stays standing, regardless of
speed or force. A materially stronger conclusion than the original "the
refs are approximate" caveat.

### External research (2026-09-24): what actually works elsewhere

Researched whether anyone has successfully simulated quadruped self-right/
get-up motion, and what let them succeed. Nothing Bittle/Petoi-specific
(expected, consistent with `docs/research/community-projects.md` -- even
BittleJuice/bittle-mujoco never covered get-up validation). Four findings,
ranked by relevance to the specific failure mode found here:

1. **Reference State Initialization (RSI)** — Yang et al., "Learning Complex
   Motor Skills for Legged Robot Fall Recovery," IEEE RA-L 2023 (UCL).
   Builds a graph of key postures along the recovery sequence and
   initializes *training* episodes starting from those intermediate
   postures, not only from the raw fall. Directly targets our exact
   symptom (losing progress at a handoff/tail) -- but it's a technique for
   training a policy, not for open-loop replay; doesn't apply until/unless
   this moves to option 3 or 4 below.
2. **HumanUP's 8x slowdown** — "Learning Getting-Up Policies for Real-World
   Humanoid Robots" (arXiv 2502.12152). Tested directly above (test 6);
   didn't transfer to our case, for the reason given there.
3. **DeepMimic-style motion imitation** — the standard technique for making
   a fragile reference execute robustly: train a policy with a reward
   tracking pose/velocity/root-pose error against the reference, instead of
   commanding it open-loop. `erwincoumans/motion_imitation` on GitHub is
   PyBullet-native (maintained by PyBullet's own creator) and built for
   arbitrary reference motions, not just mocap -- directly reusable with
   our existing `rc_ref.npy`/`rl_ref.npy`. Real lift: a genuine PPO training
   loop, not a script tweak.
4. **From-scratch fall-recovery RL** (no reference trajectory -- reward-
   shaped exploration from domain-randomized fallen starting poses; never
   terminate the episode on falling, corroborated across multiple 2024-2025
   papers). The field's most independently-corroborated *actually working*
   approach, but abandons the decoded keyframes entirely and is the biggest
   lift of the four.

**Where this leaves H9:** open-loop replay is now conclusively exhausted as
an approach -- six tested variables, zero improvement, root cause
identified and specific. Getting an actual sim validation of self-righting
would require real RL training (imitation-style or from-scratch), which is
a genuinely different scope of effort (its own training loop, reward
design, likely its own multi-hour run) and not something to start without
explicit direction, especially pre-hardware and with the current Phase B/C
gait campaign already occupying the only training slot. Until/unless that's
greenlit, the standing conclusion holds unchanged: **the sim cannot
validate the firmware get-up; treat `krc`/`krl` as unverified on arrival.**
