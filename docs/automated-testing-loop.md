# Automated Testing Loop — RL Gait Iteration

A runbook for unattended reward-function iteration on the walking policy. This is
a separate workflow from the normal collaborative one, where every replay is
watched and every run approved. Trigger phrases: "automated testing", "an
automated run", "iterate on your own".

Established for the level-ground gait work; extended through Runs 5–7 (domain
randomization, `wkF` imitation, fall recovery, target speed). Update it as the
process changes.

---

## Goal

The goal is set per loop at kickoff. Historically:

- **Loop 1:** an efficient, stable level-ground walk close to OpenCat's built-in
  `wkF` gait — straight line, real diagonal trot, no falling. Pure reward-shaping,
  measured by metrics.
- **Runs 5–7:** robustness to obstacles and disturbances, fall/stumble recovery,
  and a deliberate target walk speed.

---

## Branch discipline

- All automated-iteration work happens on **`auto-gait-iteration`**, branched from
  `development`.
- **At the start of every run, sync `development` first:**
  ```bash
  git checkout development
  git pull --ff-only origin development
  git checkout auto-gait-iteration          # create from development if needed
  git merge development
  ```
  If the merge conflicts, stop and hand back — do not resolve conflicts inside
  the loop.
- **One commit per round** on the branch — the reward/env change plus its
  `auto-iteration-log-run<N>.md` entry — so any round is individually
  recoverable.
- The loop never merges to `development` itself. After the results are reviewed,
  ask whether to merge `auto-gait-iteration` → `development`; merge only on an
  explicit yes, with `git merge --no-ff` and a message describing the changes.
  Do not `git push` unless asked.

---

## Interruptibility (hard requirement)

The loop must never be an unstoppable long process.

- **Longest uninterruptible unit = one training run** (~35–40 min for 2M steps).
- **Session interrupt** stops work between or during steps. A training run keeps
  writing checkpoints; `pkill -f train.py` ends it losing nothing past the last
  checkpoint.
- **`STOP` sentinel file** — before each round, check for
  `rl_training/opencat-gym/STOP`. If present, finish the current round (or stop
  immediately if between rounds), write the report, and hand back.
- **Hard caps** — stop at a wall-clock limit or a round count, whichever comes
  first. Confirm the caps at kickoff.
- Stop early if targets are met. If the cap is hit without meeting them, stop
  anyway — keep the best checkpoint and report what's blocking plus recommended
  next moves.

---

## Per-round procedure

1. Check `STOP` and the caps. If either says stop, go to **Wrap-up**.
2. **Evaluate the current best policy** headlessly (see Evaluation). Round 0 is
   whatever checkpoint exists at kickoff.
3. **Diagnose** the single biggest gap between current behavior and the goal.
4. **Make one change** — a reward constant or a reward-term formula in
   `opencat_gym_env.py`. One variable per round so cause and effect stay legible.
   Structural changes (observation/action space, PPO hyperparameters, a new
   reward mechanism) are bigger bets — describe the plan and get a go-ahead
   before spending a round on one, rather than deciding unilaterally inside the
   loop.
5. **Smoke test**: `../../.venv/bin/python smoke_train.py` — reward in the
   expected range for the current reward config, no NaN.
6. **Train**: `./start_run.sh <tag> --steps 2000000`. Tag scheme:
   `<loop>_r<N>` (e.g. `walk_r1`). Every run needs a unique tag.
7. **Re-evaluate** the new checkpoint against the current best.
8. **Score** with the loop's composite metric. Promote the round if it beats the
   best by a margin; on two non-improving rounds in a row, revert to the
   last-good config and change levers.
9. **Log** to `docs/auto-iteration-log-run<N>.md`: what changed, why,
   before/after metrics, diagnosis, keep/revert decision.
10. **Commit** to `auto-gait-iteration`.
11. **Post an update** — this round's result vs. the previous, the diagnosis, and
    the next change — then launch the next run immediately. Don't wait for a
    reply.

Optionally end the loop with one confirming run at full length on the best
config.

## Decision-making during the loop

At any choice point, take the route you would recommend rather than surfacing
options and waiting. Record the choice and its reasoning in the log.

---

## Evaluation (headless — no GUI during the loop)

`evaluate_policy.py` (headless, `p.DIRECT`) loads a checkpoint, runs a batch of
deterministic episodes, and emits JSON metrics. Core metrics and the failure mode
each targets:

| Metric | Failure mode |
|---|---|
| Forward distance, mean forward speed | progress / efficiency |
| Speed error vs. `TARGET_SPEED` | holding the walk set-point (Run 7+) |
| Yaw drift / heading deviation | curving off a straight line |
| Per-foot peak swing height, stride length | shuffling vs. real steps |
| Foot-slip distance while in contact | dragging feet |
| Diagonal-trot phase correlation | wrong / no gait pattern |
| Joint direction-reversal count | jitter |
| Fell fraction, time-to-fall | stability |
| Big-stumble recovery rate | catching a stumble before a fall (Run 7+) |
| Roll & pitch variance | body stability |

`--dr-*` flags (`--dr-terrain`, `--dr-push`, …) force full-strength domain
randomization for a held-out scenario the policy never trained on. Any flag
zeroes every DR knob first, then applies the ones passed.

The script can also render ~30 frames of an episode to PNGs for direct
inspection — the stand-in for watching a replay during an unattended loop.

State the metric set and target numbers at kickoff, then start immediately — no
waiting for pre-approval.

---

## Wrap-up (loop completes, interrupt, or STOP file)

1. Optionally run a full-length confirming run on the best config (skip on an
   immediate stop).
2. **Write the report** — `docs/auto-iteration-report-<date>.md`:
   - every change across all rounds, in order, with reasoning
   - a before/after metrics table per round
   - final policy metrics vs. targets
   - what improved, what's still short, recommended next moves
3. **Queue the review artifacts:**
   - TensorBoard running and open, showing the loop's `PPO_N` runs next to the
     earlier ones
   - `g2watch` on the best checkpoint ready to run (launch it or leave the exact
     command)
   - Render the candidate policies to GIFs (`render_gif.py`).
   - **Only when working from mobile (or when a page view is requested):** also
     publish an HTML review Artifact with each gait GIF + metrics + the
     recommendation. At a desk this is skipped — TensorBoard + `g2watch` are the
     review.
4. **Ask whether to merge** `auto-gait-iteration` → `development`. Merge only on
   an explicit yes.

---

## Machine prerequisites (state these before starting)

- Laptop plugged in and set not to sleep — a sleep mid-run stalls it.
- Sustained multi-core load in ~40-min bursts for the whole window; the machine
  won't be free for other heavy work.

---

## Pre-run summary (post before every run)

A short block right before launching any training run:

- **ETA** — wall-clock, with basis. ~35–40 min per 2M steps on this machine. For
  a loop: `(rounds planned × ~50 min incl. eval) + current time`.
- **This run** — one line: what's changing and the hypothesis.
- **Scope** — steps per run; for a loop, rounds planned and the caps.
- **Stop** — `touch rl_training/opencat-gym/STOP` (clean stop after the current
  round) or interrupt.
- **On completion** — what's delivered: notification, and for a loop the report,
  TensorBoard, `g2watch` replay, and the merge question.

**Every status update** leads with **percent done** and an **estimated finish
time** (a clock time, plus a range if the round count may still flex), then the
current round's state.

## Kickoff checklist

- [ ] Sync `development` into `auto-gait-iteration` (stop if it conflicts).
- [ ] Confirm the caps and machine prerequisites.
- [ ] `evaluate_policy.py` exists and runs.
- [ ] Post the pre-run summary (ETA + details).
- [ ] State the metric set and target numbers.
- [ ] Evaluate the round-0 baseline, then begin the per-round procedure.
