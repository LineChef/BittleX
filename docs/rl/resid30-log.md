# resid30 campaign log

Testing whether widening `RESIDUAL_SCALE_DEG` 22 -> 30 (a fresh run, not a
continuation of `run20m_ppo`) produces a policy that beats the frozen
baseline on the standard benchmark. Plan:
`/Users/markjohnson/.claude/plans/effervescent-kindling-clover.md`. Branch:
`auto-gait-iteration`.

## Round 1 — resid30_r1

- **Started:** 2026-09-18 02:06 EDT, 3M steps, PID 41481.
- **Config:** `RESIDUAL_SCALE_DEG=30`, `FAC_IMITATION=16.0` (starting
  hypothesis, up from the current 11.0 -- matching G1's historically-validated
  pairing strength for this exact crawl-regression risk), `FAC_RESIDUAL_COST=2.8`,
  `FAC_RESID_SMOOTH=8.2` (both scaled proportionally to RESIDUAL_SCALE_DEG,
  since they act on the normalized action not raw degrees). All other reward
  terms unchanged from `run20m_ppo`'s recipe.
- **Smoke test:** passed clean (20k steps, `ep_rew_mean` ~700, no NaN/crash).
- **Purpose:** rule out the known crawl-regression failure mode (r1's 18-degree
  attempt with a too-weak imitation anchor) before committing more compute --
  not a head-to-head vs run20m_ppo yet.
- **Result:** pending.

### Issue hit + fixed: TensorBoard logging crashed every run at startup

- **Symptom:** `train.py` crashed immediately (before any training steps) with
  `ImportError: Trying to log data to tensorboard but tensorboard is not
  installed.` -- reproduced twice, not transient.
- **Root cause:** not actually a missing package (`import tensorboard` alone
  works fine) -- the real failure is inside `torch.utils.tensorboard`'s own
  import chain: `tensorboard.compat.proto.event_pb2` needs a newer
  `google.protobuf` (specifically `runtime_version`) than what's installed in
  this venv. SB3 catches the failed `SummaryWriter` import and raises the
  generic "not installed" error, which is why it looked like a missing
  package.
- **Decision:** per the user's call ("we don't ever need to pop the
  tensorboard for me anymore"), disabled TensorBoard logging entirely rather
  than chasing the protobuf pin (which risked its own ripple effects on other
  packages) -- `train.py`'s two `tensorboard_log=` args set to `None`, and
  `start_run.sh`'s TensorBoard auto-start/browser-open step removed. Verified
  fix with a clean smoke test (20k steps, no errors).
- **Consequence for this plan:** the Stage 1 verification step ("watch
  `r_imitation`/`r_joint_limit` trends in TensorBoard") needs a different
  mechanism now, since there's no live scalar dashboard. Will write a small
  standalone script to pull the per-term reward breakdown from the env's
  info dict directly on a checkpoint, since `evaluate_policy.py` doesn't
  expose it either. Not yet built -- next thing to do once resid30_r1
  finishes.

### Note: final deliverable

User explicitly asked for the Stage 3 benchmark comparison to be ready for
review as a proper report, not raw JSON -- will publish an HTML Artifact at
wrap-up (matching the project's established results-report pattern) with
the benchmark_decathlon.py diff, benchmark_recovery.py head-to-head,
benchmark_gaits.py vs-scripted results, and the final keep/revert verdict
against run20m_ppo.

### Issue hit + fixed: RESIDUAL_SCALE_DEG had no per-checkpoint override

- **Symptom:** while building an action-magnitude visualization for the user,
  a run20m_ppo trace showed implausible values (action magnitude reading up
  to 27.9 degrees against what should be a 22-degree ceiling for that
  checkpoint).
- **Root cause:** `RESIDUAL_SCALE_DEG` is a plain module constant, unlike
  most other reward/config constants in this file which go through the
  `_g2e()` env-var override helper. Since the module now defaults to 30
  (for this campaign), evaluating run20m_ppo (trained at 22) applied its
  actions at the wrong physical scale -- silently invalid, not just
  cosmetically wrong, since it changes what joint angles actually get
  commanded. This tainted the earlier `run20m_ppo_baseline_eval.json` too.
- **Fix:** added the same `_g2e()` override pattern already used for
  `FAC_IMITATION` etc. `G2E_RESIDUAL_SCALE_DEG=22` now correctly evaluates
  old checkpoints regardless of the module's current default. Regenerated
  the baseline eval and action traces with the fix in place.
- **Consequence for Stage 3:** every future evaluation/benchmark of
  `run20m_ppo` needs `G2E_RESIDUAL_SCALE_DEG=22` set explicitly (evaluating
  the new resid30 checkpoint needs no override, since 30 is now the
  module default). Noting this here so it isn't missed during the Stage 3
  benchmark suite.

### Report requirement: action-deviation charts are a standard section, not a separate page

User clarified 2026-09-18: the action-magnitude/tilt comparison (currently
at https://claude.ai/artifact/AxqHBWqBga8XDG8YsQ2Dhv, built as a side
artifact for the "when does it deviate" question) must be folded into the
Stage 3 benchmark report itself as a standard section -- generated for both
checkpoints (run20m_ppo and the resid30 candidate) using the same
action_trace.py methodology, not left as a separate linked page. Leg-tinted
replay GIFs (leg_tint.py, wired into render_gif.py etc.) are also a
standard section of that same report. Apply this same standard to any
future benchmark report from this project, not just this campaign.

### Round 1 result: clean, no retuning needed

- **Finished:** 2026-09-18 03:17 EDT, 3,014,656 total steps, `ep_rew_mean`
  climbed 700 -> ~2700, `approx_kl` settled near zero (converged, not
  diverged). Checkpoint: `trained/resid30_r1_ppo.zip`.
- **evaluate_policy.py (12 episodes)** vs the corrected `run20m_ppo`
  baseline (`G2E_RESIDUAL_SCALE_DEG=22`):
  - `fell_fraction`: 0.0 both.
  - `r_imitation` raw match ratio: 0.955 (resid30) vs 0.915 (base) -- no
    crawl-regression signature, if anything a tighter match to `wkF`.
  - `diagonal_trot_corr_mean`: -0.557 (resid30) vs -0.523 (base) -- slightly
    crisper anti-phase trot.
  - `r_joint_limit`: 0.0 both -- the soft-barrier concern flagged in the
    plan (30deg reaching into the penalty zone at saturation) doesn't
    manifest in practice; the policy isn't spending anywhere near full
    saturation on average.
  - `r_residual_cost`: -0.11 (resid30) vs -0.38 (base) -- lower, as
    expected: the FAC_RESIDUAL_COST scaling preserves real-degree cost, so
    the same real correction costs a smaller fraction of the wider budget.
  - `startup_speed_ratio_mean` initially looked concerning (1.84 -> -1.43),
    but this was command-sampling noise between two independently-sampled
    12-episode evals (eval doesn't pin cmd_fwd per episode, and the
    curriculum includes a backward-command band). Re-measured with a
    pinned, matched 0.10 m/s command, 8 seeds each: 0.85 (base) vs 0.83
    (resid30) -- statistically identical, both show the same occasional
    per-seed startup stutter. Not a regression.
- **Decision: clean pass, no Round 2 needed.** Moving directly to Stage 2
  (10M validation run w/ bailout gates), per the plan's decision gate.
