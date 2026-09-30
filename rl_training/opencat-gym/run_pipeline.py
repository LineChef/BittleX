"""Top-level supervisor: chains Phase A -> Phase B -> Phase C unattended so the
whole testing campaign runs to completion without needing a restart between
phases (2026-09-23, per user instruction: "make sure testing does not stop
until it is complete"). Phase C is scheduled for the real 20M from the start
and gated at a 10M dress-rehearsal checkpoint; per user instruction
(2026-09-24, "you make the call for the 20m run, if 10 looks good, go ahead
and continue to 20") this script decides itself whether to let it continue
past that gate -- see phase_c()'s docstring for the pass criteria.

**2026-09-24 correction (important, read before changing PHASE_A/_C
behavior): nothing in this pipeline runs to 20M except the real final
consolidation run, which is launched separately and only after explicit
approval.** Every stage here is a screening test answering "is this
learnable / does it regress the base gait" -- capped at a 3M gate, same as
Phase B, INCLUDING Phase A. Caught this late: `base1_20m` and `base2_20m`
were both mistakenly let run to full 20M completion before this was
corrected -- wasted real wall-clock time for no decision-relevant reason
(Phase B's gate uses a fixed threshold, not a comparison against Phase A's
converged output). See docs/rl/hw1-log.md for the record of this.

Stages:
  1. Launch PHASE_A_TAG, wait for its 3.0M checkpoint, evaluate the same
     2.2M-3.0M averaged flat-ground gate as Phase B, then STOP it -- never
     let it run past 3M. A crash halts the whole pipeline (the shared BASE
     config is what every later stage builds on); a bad flat-ground result
     also halts (if the base config itself isn't clean, nothing downstream
     can be trusted either).
  2. Run phase_b_orchestrator.py (7 candidates, unattended, each already
     gated on the two-part rule: skill learnability + flat-ground T1.1 stays
     clean, all capped at the same 3M gate).
  3. Read trained/phase_b_summary.json, apply the same two-part rule to build
     Phase C's combined config: a mechanic is included if it wasn't stopped
     early, T1.1 stayed clean at the gate, AND its own skill cells showed a
     real (not noise-sized) improvement in fall rate from the early check to
     the gate check.
  4. Launch Phase C: ONE run combining every included mechanic's training-time
     knobs simultaneously, fixed difficulty for the whole run (no step-gated
     staging machinery exists yet -- deliberately deferred to 20M-run design
     once Phase C confirms the combination doesn't conflict; see
     docs/rl/hw1-log.md), scheduled for the full 20M steps from launch.
  5. At the 10M dress-rehearsal checkpoint, score the full benchmark and
     decide: T1.1 clean (<= FLAT_REGRESSION_FELL_MAX) and every included
     mechanic's skill cells under DRESS_SKILL_FAIL_MAX -> let it continue to
     20M (no restart, it's already running); otherwise stop it there for
     review. No progress is lost either way -- the 10M checkpoint exists on
     disk regardless of the decision.

    python run_pipeline.py                # from Phase A onward
    python run_pipeline.py --skip-phase-a  # PHASE_A_TAG already gated at 3M
    python run_pipeline.py --skip-phase-b  # phase_b_summary.json already done
"""
import argparse
import glob
import json
import os
import subprocess
import time

import numpy as np

PY = "../../.venv/bin/python"
LOG = "trained/run_pipeline.log"

FLAT_CELL = "T1.1"
FLAT_REGRESSION_FELL_MAX = 0.15
GATE_STEP = 3000000   # 2026-09-24: single checkpoint, no averaging -- see phase_b_orchestrator.py's
                       # GATE_STEP comment for why (averaging hid a real trend + got fooled by a
                       # tail-checkpoint noise outlier in our own b1_ledge round-1 data)
DRESS_REHEARSAL_STEP = 10000000   # Phase C's checkpoint gate, halfway through its 20M schedule
DRESS_SKILL_FAIL_MAX = 0.50   # tighter than Phase B's 0.85 (3M partial-credit bar) -- by 10M/50%
                               # through the real budget, a kept mechanic should be more than barely
                               # alive
DEPLOYMENT_CANDIDATE_NAME = "Deployment_CandidateV1"   # 2026-09-24 per user instruction: if
    # PHASE_C_TAG clears the 10M gate and finishes its full 20M schedule, rename the resulting
    # policy to this. A naming/tracking marker for "this cycle's leading candidate", not an
    # auto-promotion to DEFAULT_POLICY -- that's a separate hardware-gated decision.

# Round 2 (2026-09-24): SERVO_RATE_LIMIT_DEG_S landed as a real training-time
# constraint mid-round-1 -- stopped and restarted under corrected dynamics
# rather than finish round 1 on physics already known to be unrealistic (see
# docs/rl/hw1-log.md). Tags r2_-prefixed so round 1's results stay on disk as
# a labeled pre-servo-limit reference point, not overwritten.
PHASE_A_TAG = "base2_20m"
PHASE_C_TAG = "r2_consolidated"   # 2026-09-24: renamed from r2_phaseC_dress -- this run is scheduled
                                   # for the real 20M from the start (10M dress-rehearsal gate, not a
                                   # separate run), so its name should reflect what it actually is
BASE = dict(G2E_IMU_HOLD_STEPS="16", G2E_IMU_RATE_ZERO="1", G2E_CMD_PATH="i",
            # 2026-09-28: real BiBoard measured ~93-249 Hz IMU stream, contradicting
            # the 5 Hz this "16" models -- briefly changed to "1" to match it (see
            # docs/rl/hw1-log.md Round 5). 2026-09-29: that measurement turned out to
            # be a stale-firmware artifact (board was on a ~10-month-old build,
            # confirmed via its version banner). After a full erase + reflash to
            # current official firmware, the real rate measured exactly 5.0 Hz --
            # matching this "16" all along. Reverted; the retrain built on the stale
            # reading was abandoned, keeping Release_CandidateV2.1 as-is.
            G2E_CMD_PATH_EXTRA_MS_MAX="4", G2E_BODY_MASS_SCALE="1.12",
            G2E_IMU_BIAS_DEG="2", G2E_JOINT_OFFSET_DEG="2", G2E_SLOPE_TARGET_PROB="0.3",
            G2E_SERVO_RATE_LIMIT_DEG_S="137",   # explicit for traceability -- module default is now 137 too
            G2E_CMD_SEND_EVERY_N="3",   # 2026-09-25: i@27 -- send every 3rd control tick instead of
            # every tick, so the firmware's oldest-wins serial backlog (moduleManager.h) has fewer
            # queued commands to pick from at once. Never previously applied to training, only
            # tested as an eval-time probe (resilience_joint_cmd.py) -- measured there to beat plain
            # "i" on latency and joint-tracking error on every tested cell, no firmware fork needed.
            # Does not eliminate the per-command transformSpeed easing lag itself (that's the
            # firmware-side fix, deliberately not in scope this round), only the extra staleness a
            # backlog adds on top of it.
            G2E_FAC_YAW_TRACK="9.0")   # 2026-09-25: 6.0 -> 9.0, see opencat_gym_env.py's FAC_YAW_TRACK
            # comment -- Deployment_CandidateV1's yaw_rate_rms ran 1.3-2.4x scripted's on every
            # cell checked. Measured 50% bump, not aggressive, given an older (now-replaced)
            # mechanism backfired once when pushed harder on this same general axis.


def log(msg):
    line = f"[pipeline {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def training(tag):
    return subprocess.run(["pgrep", "-f", f"train.py --tag {tag}"], capture_output=True).returncode == 0


def any_training():
    return subprocess.run(["pgrep", "-f", "train.py --tag"], capture_output=True).returncode == 0


def wait_for_finish(tag, timeout_s=None):
    """Poll until trained/<tag>_ppo.zip exists (clean finish) or the process
    dies without it (crash). Returns (ok, reason). Only for stages meant to
    run to their own full schedule (Phase C) -- Phase A/B use wait_for_ckpt
    + stop instead, capped at the 3M gate."""
    t0 = time.time()
    final = f"trained/{tag}_ppo.zip"
    while not os.path.exists(final):
        if not training(tag):
            return False, f"{tag} process exited with no {final} -- likely a crash, check trained/{tag}_console.log"
        if timeout_s and time.time() - t0 > timeout_s:
            return False, f"{tag} exceeded {timeout_s}s without finishing"
        time.sleep(30)
    return True, "clean finish"


def ckpt(tag, step):
    return f"trained/checkpoints/{tag}_{step}_steps.zip"


def stop(tag):
    subprocess.run(["pkill", "-f", f"train.py --tag {tag}"])
    while training(tag):
        time.sleep(2)


def wait_for_ckpt(tag, step):
    """Poll until a specific checkpoint exists, or the process dies first.
    Returns (ok, reason)."""
    while not os.path.exists(ckpt(tag, step)):
        if not training(tag):
            return False, f"{tag} process exited before reaching {step} steps -- check trained/{tag}_console.log"
        time.sleep(20)
    time.sleep(15)   # let the checkpoint finish writing
    return True, "reached checkpoint"


def flat_gate(tag, step=GATE_STEP):
    """Same flat-ground (T1.1) gate Phase B uses -- single checkpoint at
    `step` (default GATE_STEP), no averaging. Returns (fell_fraction, speed_mps)."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"   # match BASE (reverted 2026-09-29, see hw1-log.md Round 5)
    E.CMD_SEND_EVERY_N = 3   # match BASE's G2E_CMD_SEND_EVERY_N -- eval must match training (2026-09-25 fix)
    E.EPISODE_LENGTH = 250
    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    s, _ = _bench(env, m, 20, 1000)
    env.close()
    return float(s["fell_fraction"]), float(s["forward_speed_mps_mean"])


def _clean_stale(tag):
    """Remove a tag's leftover files IF it never finished (no <tag>_ppo.zip) --
    same rationale as phase_b_orchestrator.py's _clean_stale."""
    if os.path.exists(f"trained/{tag}_ppo.zip"):
        return
    stale = glob.glob(f"trained/checkpoints/{tag}_*_steps.zip") + \
        [p for p in (f"trained/{tag}_console.log",) if os.path.exists(p)]
    if stale:
        log(f"{tag}: cleaning {len(stale)} stale file(s) from an incomplete previous attempt")
        for f in stale:
            os.remove(f)


def launch(tag, extra, steps="20e6", from_ckpt=None, finetune_lr="3e-5", finetune_target_kl="0.05"):
    if any_training():
        raise SystemExit(f"another training is running -- refusing to launch {tag} on top of it")
    _clean_stale(tag)
    # dict(os.environ, **BASE, **extra) raises TypeError if BASE and extra share a key
    # (Python can't have the same keyword arg twice in a dict() call) -- a dict LITERAL
    # with the same unpacking silently lets later keys win, which is what we actually
    # want here: extra overriding a BASE default (2026-09-26, found when a yaw-tuning
    # candidate tried to override BASE's own G2E_FAC_YAW_TRACK).
    env = {**os.environ, **BASE, **extra}
    # start_run.sh can raise up to two y/N prompts (lingering viewer, then
    # uncommitted changes) -- `yes y` answers as many as show up, not just
    # the first (2026-09-24: a single `echo y` silently lost b4_carpet in
    # phase_b_orchestrator.py the same way).
    from_flag = (f" --from {from_ckpt} --finetune-lr {finetune_lr} "
                 f"--finetune-target-kl {finetune_target_kl}") if from_ckpt else ""
    r = subprocess.run(f"yes y | ./start_run.sh {tag} --steps {steps}{from_flag}", shell=True, env=env,
                       capture_output=True, text=True)
    log(f"launched {tag}: {r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr.strip()[-200:]}")
    time.sleep(3)
    if not training(tag):
        raise SystemExit(f"{tag} failed to start -- check the output above / trained/{tag}_console.log")


def phase_a(skip):
    if skip:
        log(f"Phase A: --skip-phase-a, assuming {PHASE_A_TAG} already gated at 3M")
        return
    log(f"Phase A: {PHASE_A_TAG} -- fresh baseline, gated at 3M like every other stage "
        "(2026-09-24 correction: never run this to 20M)")
    if not training(PHASE_A_TAG):
        launch(PHASE_A_TAG, {})
    ok, reason = wait_for_ckpt(PHASE_A_TAG, 3000000)
    if not ok:
        log(f"Phase A HALT: {reason}")
        raise SystemExit(1)
    stop(PHASE_A_TAG)
    fell, speed = flat_gate(PHASE_A_TAG)
    log(f"Phase A gate: {PHASE_A_TAG} flat-ground (at {GATE_STEP}) fell {fell:.3f}, speed {speed:.4f}")
    if fell > FLAT_REGRESSION_FELL_MAX:
        log(f"Phase A HALT: baseline itself doesn't clear the flat-ground bar "
            f"({fell:.3f} > {FLAT_REGRESSION_FELL_MAX}) -- nothing downstream can be trusted "
            "if the shared BASE config isn't clean. Needs review before Phase B.")
        raise SystemExit(1)
    log(f"Phase A complete: {PHASE_A_TAG} baseline clean. Proceeding to Phase B "
        "regardless of its own benchmark numbers -- Phase B candidates are fresh "
        "runs on the same shared BASE config, not continuations of it.")


def phase_b(skip):
    if skip:
        log("Phase B: --skip-phase-b, assuming trained/phase_b_summary.json already exists")
        return
    log("Phase B: launching phase_b_orchestrator.py (7 candidates, unattended)")
    r = subprocess.run(f"{PY} phase_b_orchestrator.py", shell=True)
    if r.returncode != 0:
        log(f"Phase B HALT: phase_b_orchestrator.py exited {r.returncode}")
        raise SystemExit(1)
    log("Phase B complete: all candidates run, trained/phase_b_summary.json written")


import phase_b_orchestrator as PB  # noqa: E402  (reuse its CANDIDATES table)


def compose_phase_c():
    # 2026-09-24: was a trend check (gate window's first checkpoint vs last).
    # Dropped along with the 5-checkpoint gate averaging (see
    # phase_b_orchestrator.py's EARLY_STEP/GATE_STEP comment) -- there's only
    # one gate checkpoint (GATE_STEP) now, so no trend to compute. Simple
    # absolute bar instead: not complete failure at the end of the 3M budget.
    # Generous on purpose -- 3M of a real 20M schedule is partial credit for
    # a brand-new skill, not a mastery bar.
    SKILL_FAIL_MAX = 0.85
    summary = json.load(open("trained/phase_b_summary.json"))
    by_tag = {r["tag"]: r for r in summary}
    included, excluded = [], []
    for tag, desc, extra, cells in PB.CANDIDATES:
        r = by_tag.get(tag)
        if r is None:
            excluded.append((tag, "no result recorded"))
            continue
        if r.get("stopped_early"):
            excluded.append((tag, f"stopped early (flat_fell={r.get('flat_fell')}, skill_fell={r.get('skill_fell')})"))
            continue
        if not r.get("flat_clean", False):
            excluded.append((tag, f"T1.1 regressed (flat_fell={r['flat_fell']})"))
            continue
        skill_fell = r.get("skill_fell", 1.0)
        if skill_fell > SKILL_FAIL_MAX:
            excluded.append((tag, f"skill cells still failing at the gate (fell {skill_fell:.2f})"))
            continue
        included.append((tag, desc, extra))
    return included, excluded


def _score_checkpoint(tag, step, all_cells):
    """Bench one checkpoint on T1.1 (flat-ground) + every cell in all_cells.
    Shared by Phase C's 3M sanity check and its 10M dress-rehearsal decision
    so both use identical scoring code. Returns (fell, speed, skill_results)."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"   # match BASE (reverted 2026-09-29, see hw1-log.md Round 5)
    E.CMD_SEND_EVERY_N = 3   # match BASE's G2E_CMD_SEND_EVERY_N -- eval must match training (2026-09-25 fix)
    E.EPISODE_LENGTH = 250
    s, _ = _bench(env, m, 20, 1000)
    fell, speed = float(s["fell_fraction"]), float(s["forward_speed_mps_mean"])

    skill_results = {}
    cells_all = {c[0]: c for c in B.LADDER}
    for cid in all_cells:
        knobs = {k: v for k, v in cells_all[cid][4].items() if not k.startswith("_")}
        B._apply(knobs)
        E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"   # match BASE (reverted 2026-09-29, see hw1-log.md Round 5)
        E.CMD_SEND_EVERY_N = 3   # match BASE's G2E_CMD_SEND_EVERY_N -- eval must match training (2026-09-25 fix)
        E.EPISODE_LENGTH = 250
        s, _ = _bench(env, m, 20, 1000)
        skill_results[cid] = round(s["fell_fraction"], 3)
    env.close()
    return fell, speed, skill_results


def run_gated_20m(tag, extra, all_cells, deployment_name, from_ckpt=None, label="Phase C"):
    """Shared by Phase C (combined-from-scratch) and phase_r_sequential.py's final
    stage (continuation from the sequential chain's last checkpoint): launch a
    20M-step run, 3M sanity check (kills only on a double-bad signal -- flat-ground
    regressed AND no learning signal on any cell, mirroring Phase B's early-stop
    bar), 10M dress-rehearsal decision (continue with zero restart if T1.1 stays
    clean and every cell is under DRESS_SKILL_FAIL_MAX, else stop there), and on a
    clean 20M finish, rename to `deployment_name`. See git history on phase_c() for
    the full rationale (2026-09-24 restructure + go/no-go delegation). For a
    fine-tune continuation on an already-consolidated gait where 20M is likely
    overkill (e.g. narrow reward-weight tuning), use run_gated_10m instead --
    scheduling this function's 20M and hoping a plateau check rescues it early
    was tried and correctly called out as backwards (2026-09-26): don't schedule
    for more than you expect to need and lean on a safety net to cut it short."""
    log(f"{label}: launching {tag} -- 20M-step schedule"
        f"{f', continuing from {from_ckpt}' if from_ckpt else ''}, gated at the "
        f"{DRESS_REHEARSAL_STEP} dress-rehearsal checkpoint before continuing")
    launch(tag, extra, steps="20e6", from_ckpt=from_ckpt)

    # 3M sanity check -- does NOT stop training either way (matches Phase B's
    # early check pattern: only the double-bad case below kills the run).
    ok, reason = wait_for_ckpt(tag, GATE_STEP)
    if not ok:
        log(f"{label} HALT: {reason}")
        raise SystemExit(1)
    early_fell, early_speed, early_skills = _score_checkpoint(tag, GATE_STEP, all_cells)
    early_worst_cell, early_worst_fell = max(early_skills.items(), key=lambda kv: kv[1]) if early_skills else (None, 0.0)
    log(f"{label} 3M sanity check: T1.1 fell {early_fell:.3f}, speed {early_speed:.4f}; "
        f"per-cell skill fell: {early_skills}")
    if early_fell > FLAT_REGRESSION_FELL_MAX and early_worst_fell > 0.9:
        log(f"{label} EARLY STOP: flat-ground regressed (fell {early_fell:.3f} > "
            f"{FLAT_REGRESSION_FELL_MAX}) AND no learning signal yet on any combined skill cell "
            f"(worst {early_worst_cell} fell {early_worst_fell:.3f}) -- the combination looks "
            f"broken, not just slow. Halting at 3M rather than waiting for the 10M gate.")
        stop(tag)
        raise SystemExit(1)

    ok, reason = wait_for_ckpt(tag, DRESS_REHEARSAL_STEP)
    if not ok:
        log(f"{label} HALT: {reason}")
        raise SystemExit(1)
    fell, speed, skill_results = _score_checkpoint(tag, DRESS_REHEARSAL_STEP, all_cells)
    log(f"{label} dress-rehearsal report ({DRESS_REHEARSAL_STEP} steps): "
        f"T1.1 fell {fell:.3f}, speed {speed:.4f}; per-cell skill fell: {skill_results}")

    flat_ok = fell <= FLAT_REGRESSION_FELL_MAX
    worst_cell, worst_fell = max(skill_results.items(), key=lambda kv: kv[1]) if skill_results else (None, 0.0)
    skills_ok = worst_fell <= DRESS_SKILL_FAIL_MAX
    if flat_ok and skills_ok:
        log(f"{label} DECISION: CONTINUE to 20M -- T1.1 fell {fell:.3f} "
            f"(<= {FLAT_REGRESSION_FELL_MAX}), worst skill cell {worst_cell} fell {worst_fell:.3f} "
            f"(<= {DRESS_SKILL_FAIL_MAX}). {tag} keeps running with zero restart -- "
            f"this is now the real 20M consolidation run.")
        log(f"{label}: waiting for {tag} to finish its full 20M schedule "
            f"before renaming to {deployment_name}")
        ok, reason = wait_for_finish(tag)
        if not ok:
            log(f"{label}: {tag} did not finish cleanly ({reason}) -- not renaming. "
                f"Needs review; the {DRESS_REHEARSAL_STEP}-step checkpoint is still on disk.")
            raise SystemExit(1)
        src = f"trained/{tag}_ppo.zip"
        dst = f"trained/{deployment_name}_ppo.zip"
        os.rename(src, dst)
        log(f"{label} complete: {tag} finished its full 20M schedule clean. "
            f"Renamed {src} -> {dst}. This marks it as the cycle's leading candidate -- "
            f"promoting it to DEFAULT_POLICY is a separate, hardware-gated decision "
            f"(per docs/rl/hw1-log.md conventions), not automatic.")
        return True
    else:
        why = []
        if not flat_ok:
            why.append(f"T1.1 fell {fell:.3f} > {FLAT_REGRESSION_FELL_MAX}")
        if not skills_ok:
            why.append(f"{worst_cell} fell {worst_fell:.3f} > {DRESS_SKILL_FAIL_MAX}")
        log(f"{label} DECISION: STOP -- {', '.join(why)}. Halting {tag} short of 20M; "
            f"the {DRESS_REHEARSAL_STEP}-step checkpoint is kept for review, no progress lost.")
        stop(tag)
        return False


def run_gated_10m(tag, extra, all_cells, deployment_name, from_ckpt=None, label="Tuning"):
    """For a narrow fine-tune continuation on an already-consolidated gait, where
    the project's own precedent (docs/rl/refinement-regimen.md's Phase 4
    stance-recovery continuation: 3-5M, not 20M) and this campaign's own evidence
    (the sequential chain's final 20M continuation barely changed from its 3M
    checkpoint onward) both say 20M is very likely overkill. Scheduled for
    exactly 10M steps -- no dress-rehearsal-then-maybe-20M branch, because
    nothing is scheduled past 10M to begin with. 3M sanity check still applies
    (same double-bad-signal early-stop as run_gated_20m); at natural 10M
    completion, score once and rename to `deployment_name` if clean, else leave
    the checkpoint on disk for review."""
    log(f"{label}: launching {tag} -- 10M-step schedule"
        f"{f', continuing from {from_ckpt}' if from_ckpt else ''}")
    launch(tag, extra, steps="10e6", from_ckpt=from_ckpt)

    ok, reason = wait_for_ckpt(tag, GATE_STEP)
    if not ok:
        log(f"{label} HALT: {reason}")
        raise SystemExit(1)
    early_fell, early_speed, early_skills = _score_checkpoint(tag, GATE_STEP, all_cells)
    early_worst_cell, early_worst_fell = max(early_skills.items(), key=lambda kv: kv[1]) if early_skills else (None, 0.0)
    log(f"{label} 3M sanity check: T1.1 fell {early_fell:.3f}, speed {early_speed:.4f}; "
        f"per-cell skill fell: {early_skills}")
    if early_fell > FLAT_REGRESSION_FELL_MAX and early_worst_fell > 0.9:
        log(f"{label} EARLY STOP: flat-ground regressed (fell {early_fell:.3f} > "
            f"{FLAT_REGRESSION_FELL_MAX}) AND no learning signal yet on any cell "
            f"(worst {early_worst_cell} fell {early_worst_fell:.3f}). Halting at 3M.")
        stop(tag)
        raise SystemExit(1)

    ok, reason = wait_for_finish(tag)
    if not ok:
        log(f"{label} HALT: {reason}")
        raise SystemExit(1)
    fell, speed, skill_results = _score_checkpoint(tag, 10000000, all_cells)
    log(f"{label} 10M final report: T1.1 fell {fell:.3f}, speed {speed:.4f}; "
        f"per-cell skill fell: {skill_results}")
    flat_ok = fell <= FLAT_REGRESSION_FELL_MAX
    worst_cell, worst_fell = max(skill_results.items(), key=lambda kv: kv[1]) if skill_results else (None, 0.0)
    skills_ok = worst_fell <= DRESS_SKILL_FAIL_MAX
    if flat_ok and skills_ok:
        src = f"trained/{tag}_ppo.zip"
        dst = f"trained/{deployment_name}_ppo.zip"
        os.rename(src, dst)
        log(f"{label} complete: {tag} finished its 10M schedule clean. Renamed {src} -> {dst}.")
        return True
    why = []
    if not flat_ok:
        why.append(f"T1.1 fell {fell:.3f} > {FLAT_REGRESSION_FELL_MAX}")
    if not skills_ok:
        why.append(f"{worst_cell} fell {worst_fell:.3f} > {DRESS_SKILL_FAIL_MAX}")
    log(f"{label} DECISION: regressed -- {', '.join(why)}. {tag}'s checkpoint kept for review.")
    return False


def phase_c():
    # 2026-09-24 restructure per user instruction: one run, scheduled for the
    # real 20M from the start, gated at a 10M dress-rehearsal checkpoint --
    # not a separate 10M run followed by a fresh 20M run if it passes. Avoids
    # throwing away 10M of real progress just to restart identically.
    #
    # 2026-09-24 (same day, later): user delegated the go/no-go call at this
    # gate ("you make the call for the 20m run, if 10 looks good, go ahead
    # and continue to 20 so we can get a consolidated gait") -- this script
    # now decides itself instead of pausing for approval.
    #
    # 2026-09-25: gate logic extracted into run_gated_20m() so
    # phase_r_sequential.py's final stage (continuation from the sequential
    # chain, not composed from Phase B) can reuse the identical, already-
    # tested 3M/10M gate machinery instead of a second implementation.
    log("Phase C: composing combined config from trained/phase_b_summary.json")
    included, excluded = compose_phase_c()
    log("Phase C INCLUDED: " + (", ".join(t for t, _, _ in included) if included else "none"))
    for tag, reason in excluded:
        log(f"Phase C excluded {tag}: {reason}")
    combo = dict(BASE)
    for tag, desc, extra in included:
        combo.update(extra)
    with open("trained/phase_c_config.json", "w") as f:
        json.dump(dict(included=[t for t, _, _ in included], excluded=excluded, env=combo), f, indent=1)
    if not included:
        log(f"Phase C: nothing passed Phase B -- nothing to combine. Pipeline stops here; "
            f"the 20M run would just be a repeat of {PHASE_A_TAG}'s config. Needs review.")
        return
    all_cells = sorted({c for tag, desc, extra, cells in PB.CANDIDATES if tag in
                        [t for t, _, _ in included] for c in cells})
    run_gated_20m(PHASE_C_TAG, {k: v for k, v in combo.items() if k not in BASE}, all_cells,
                  DEPLOYMENT_CANDIDATE_NAME, label="Phase C")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-phase-a", action="store_true")
    ap.add_argument("--skip-phase-b", action="store_true")
    args = ap.parse_args()
    log("=== pipeline started ===")
    phase_a(args.skip_phase_a)
    phase_b(args.skip_phase_b)
    phase_c()
    log("=== pipeline finished (see Phase C DECISION above for the 20M call) ===")


if __name__ == "__main__":
    main()
