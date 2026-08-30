# Automated Testing Loop — RL Gait Iteration

How Claude runs unattended reward-function iteration on the walking policy. This is
a **separate workflow** from the normal collaborative one (where the user watches
every replay and approves each run). When the user asks for "automated testing" /
"an automated run" / "iterate on your own", follow this document.

Established 2026-08-30. Update it as the process is refined.

---

## Goal

Produce a policy that walks **efficiently and stably on level ground**, as close as
possible to OpenCat's built-in `wkF` walk gait — straight line, real diagonal-trot
leg pattern, no falling. This is **approach (a): functional equivalence** — pure
reward-shaping, measured by metrics. Not literal `wkF` keyframe imitation (that was
considered and deferred).

This level-ground gait is the prerequisite. Uneven-terrain training is a later
phase and is out of scope for this loop.

---

## Branch discipline

- All automated-iteration work happens on the branch **`auto-gait-iteration`**
  (branched from `development`).
- **Before making any changes at the start of a run — always — sync
  `development` first, then fast-forward it into `auto-gait-iteration`.** This is
  mandatory every run, so the loop branch never drifts and the eventual merge back
  is conflict-free:
  ```bash
  git checkout development
  git pull --ff-only origin development     # pick up anything pushed since last time
  git checkout auto-gait-iteration          # (create from development if it doesn't exist)
  git merge development
  ```
  If `git merge development` reports conflicts, stop and hand back to the user —
  do not resolve them inside the loop.
- **One commit per iteration** on that branch — the reward change plus the
  `auto-iteration-log.md` entry — so any iteration is individually recoverable.
- The loop never merges to `development` itself. After the user reviews the
  results, **Claude asks whether to merge `auto-gait-iteration` into
  `development`**, and only merges on an explicit yes (`git merge --no-ff` with a
  message describing the changes and the progress made). Do not `git push` unless
  the user asks.

---

## Interruptibility (hard requirement)

The loop must never be an unstoppable long process.

- **Longest uninterruptible atom = one training run (~20 min).** Never longer.
- **Session interrupt (Esc)** stops Claude between or during steps. A training run
  in progress keeps writing checkpoints; `pkill -f train.py` ends it with nothing
  lost past the last checkpoint.
- **`STOP` sentinel file** — before starting each iteration the loop checks for
  `rl_training/opencat-gym/STOP`. If present, it finishes the current iteration (or
  stops immediately if between iterations), writes the report, and hands back.
- **Hard caps** — the loop stops at a wall-clock limit **or** an iteration count,
  whichever comes first. Defaults: **3 hours or 6 iterations.** Confirm/adjust with
  the user at kickoff.
- If targets are met before the cap, stop early.
- If the cap is hit without meeting targets, stop anyway — keep the best
  checkpoint, report what's blocking and recommended next moves.

---

## Per-iteration procedure

1. Check for `STOP` and check the caps. If either says stop, go to **Wrap-up**.
2. **Evaluate the current best policy** headlessly (see Evaluation below). Iteration
   0 is the run that exists at kickoff (e.g. `full_run_v6_ppo`).
3. **Diagnose** the single biggest gap between current behavior and the goal.
4. **Make one change** — a reward constant or a reward-term formula in
   `opencat_gym_env.py`. One variable per iteration so cause/effect stays legible.
   Structural changes (observation/action space, PPO hyperparameters, adding an
   imitation term) are **out of scope** — flag them for the user instead.
5. **Smoke test**: `../../.venv/bin/python smoke_train.py` — reward ~40–55, no NaN.
6. **Train**: `./start_run.sh <tag> --steps 1000000` (~20 min). Tag scheme:
   `auto_iter<N>` (e.g. `auto_iter1`).
7. **Re-evaluate** the new checkpoint. Compare metrics to the previous iteration.
8. **Log** the iteration to `docs/auto-iteration-log.md`: what changed, why, metrics
   before/after, diagnosis, keep/revert decision.
9. **Commit** to `auto-gait-iteration`.
10. If the change made things worse, revert it in the next iteration's baseline
    (keep the better checkpoint as current best).

After the loop: one **confirming run at the full 2e6 steps** on the best reward
config before wrap-up.

## Decision-making during the loop

When choosing between options at any step, **take the route Claude would have
recommended to the user** — do not surface options and wait. Record the choice and
its reasoning in the iteration log.

---

## Evaluation (headless — no GUI during the loop)

Build `evaluate_policy.py` (headless, `p.DIRECT`) that loads a checkpoint, runs a
batch of deterministic episodes, and emits JSON metrics:

| Metric | Targets the failure mode |
|---|---|
| Forward distance (fixed step budget), mean forward speed | overall progress / efficiency |
| Yaw drift / heading deviation | curving off a straight line |
| Per-foot peak swing height, stride length | shuffling vs. real steps |
| Foot-slip distance while in contact | dragging feet |
| Diagonal-trot phase correlation | wrong / no gait pattern |
| Joint direction-reversal count | jitter |
| Time-to-fall / fell? | stability |
| Roll & pitch variance | body stability |

Also render ~30 frames of one episode to PNGs (`p.getCameraImage`) for Claude to
inspect directly — this is the stand-in for the user watching the replay.

At kickoff Claude states the metric set **and target numbers** (derived from the
`wkF` gait characteristics and good quadruped-walking norms), then starts
immediately — no waiting for pre-approval. The user can interrupt if a target looks
wrong.

---

## Wrap-up (loop completes, or user interrupts, or STOP file)

1. Run the full 2e6-step confirming run on the best config (skip if interrupted
   mid-loop and the user wants an immediate stop).
2. **Write the report** — `docs/auto-iteration-report-<date>.md`:
   - every reward change across all iterations, in order, with reasoning
   - metrics before/after per iteration (table)
   - final policy metrics vs. targets
   - what improved, what's still short, recommended next moves
3. **Queue the review artifacts for the user:**
   - TensorBoard running, browser opened, filtered to the loop's `PPO_N` runs
     alongside the earlier ones for comparison
   - `g2watch` on the best/final checkpoint (visual replay) ready to run — launch
     it or leave the exact command so the user just hits enter
   - **Always also publish an HTML review page (Artifact)** — the desktop replay
     window and local files don't reach a phone. Render the candidate policies to
     GIFs (`render_gif.py`) and build a page with each gait animation + its key
     metrics + the recommendation, like `g2_gait_replays.html`. This is the
     primary deliverable when the user is on mobile; do it every wrap-up
     regardless, since it's the shareable record.
4. **Ask the user** whether to merge `auto-gait-iteration` into `development`.
   Merge only on an explicit yes.

---

## Machine prerequisites (tell the user before starting)

- Laptop **plugged in and set not to sleep** — a sleep mid-run stalls it.
- The machine will be under sustained multi-core load in ~20-min bursts for the
  whole window; the user shouldn't need it for other heavy work.

---

## Pre-run summary (post before every run — loop or single training run)

Right before launching any training run, post a short summary-level block. Always
include an **ETA** with how it's derived. Keep it terse:

- **ETA** — wall-clock estimate. Basis: ~19–20 min per 1M steps on this machine
  (~40 min per 2M). For a loop: `(iterations planned × ~25 min incl. eval) +
  ~40 min confirming run`, plus current clock time → expected finish time.
- **This run** — one line: what's changing and the hypothesis (or "baseline, no
  change").
- **Scope** — steps per run; for a loop, iterations planned and the caps
  (default 3h / 6 iterations).
- **Stop** — `touch rl_training/opencat-gym/STOP` (clean stop after current
  iteration) or interrupt the session.
- **On completion** — what the user gets: notification + (for a loop) report,
  TensorBoard, `g2watch` replay, and the merge question.

**Every status update** (loop or run) leads with **percent done** and **estimated
time to finish** (a clock time, plus a range if iteration count may still flex),
then the current iteration's state.

## Kickoff checklist

- [ ] `git checkout development && git pull --ff-only`, then `git checkout auto-gait-iteration && git merge development` (stop and hand back if it conflicts)
- [ ] Confirm caps (default 3h / 6 iterations) and machine prereqs with the user
- [ ] `evaluate_policy.py` exists and runs
- [ ] Post the **pre-run summary** (above) — ETA + details
- [ ] State metric set + target numbers
- [ ] Evaluate iteration-0 baseline, then begin the per-iteration procedure
