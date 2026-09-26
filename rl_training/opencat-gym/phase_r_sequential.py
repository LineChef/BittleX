"""Sequential single-skill continuation chain (2026-09-25), per explicit user
instruction: train flat ground first, then each of the 5 combined mechanics
one at a time in increasing difficulty order, each stage CONTINUING from the
previous stage's checkpoint (not a fresh run), each stage keeping every prior
mechanic active (cumulative, "adding on top of each one"). Hypothesis: does
giving the policy focused, undiluted exposure to one mechanic at a time avoid
the interference pattern seen in the parallel-combined run (ledges regressing
5%->30%->30% over training while everything else held flat)?

Difficulty order is evidence-based, not assumed: ledges are unambiguously the
hardest mechanic in every measurement we have (62.5% skill-fell in isolated
3M screening; the only mechanic with 30-40% fell and a rising-fall-rate
pattern in the final Deployment_CandidateV1 benchmark), so ledges go last.
The other four (transitions, transition+step, carpet, snag) were statistically
tied at 0% fell everywhere we measured them -- ordered here by mechanical
complexity instead (pure surface-property changes before discrete-geometry
ones), not by any fall-rate signal, since none exists to break the tie.

Each stage's gate re-scores EVERY mechanic introduced so far, not just the
newest one -- that's the actual test of the hypothesis (are earlier skills
holding up as later ones get added), not just "did the new one learn".

Continuation uses train.py's existing --from + --finetune-lr 3e-5 +
--finetune-target-kl 0.05 path (already used historically for Phase 4
stance-recovery continuation onto a converged 20M policy -- see
docs/rl/refinement-regimen.md). That LR was tuned for gently nudging an
ALREADY-CONVERGED policy; here every source checkpoint is itself only 3M
deep, not fully converged, so if a stage's new-skill signal looks weak (not
just "still improving"), the one permitted retry uses a higher LR (1e-4)
before falling back to whatever that stage's best checkpoint was -- per the
user's explicit "iterate a reasonable number of times, then use the best
state we could produce" instruction (interpreted as up to 2 follow-ups).

    python phase_r_sequential.py
    python phase_r_sequential.py --from-stage 3   # resume after a manual stop
"""
import argparse
import glob
import json
import os
import subprocess
import time

import run_pipeline as RP  # reuse launch/wait_for_finish/_score_checkpoint/log/etc.

LOG = "trained/phase_r_sequential.log"
STEPS = "3e6"
FINAL_20M_TAG = "r3_seq_20m"   # continuation of stage 5's winning checkpoint, not fresh
INTERIM_NAME = "r3_seq_candidate"   # 2026-09-25 per user instruction: only promote to
    # Release_CandidateV2 if this beats Deployment_CandidateV1 -- NOT an automatic rename on a
    # clean 20M finish the way Phase C's DEPLOYMENT_CANDIDATE_NAME was. run_gated_20m() still
    # renames unconditionally on clean finish (that's its contract, shared with Phase C), just
    # to this neutral interim name -- the win/lose comparison against V1 happens after, and
    # ONLY a win renames it again, to RELEASE_NAME.
RELEASE_NAME = "Release_CandidateV2"
V1_REPORT = "trained/phase_c_report.json"   # Deployment_CandidateV1's saved benchmark, already on disk
V2_REPORT = "trained/phase_r_sequential_report.json"
RETRY_LR = "1e-4"   # the one permitted retry's higher LR -- see module docstring
NEW_SKILL_LEARNABLE_MAX = 0.85   # same generous partial-credit bar as Phase B
PRIOR_SKILL_COLLAPSE_MAX = 0.50  # a prior mechanic exceeding this = real regression,
                                  # not just drift -- triggers the retry, not just a log note
CARPET_SPEED_REGRESSION_MAX = 0.05   # 2026-09-25 per user instruction: if carpet costs more
    # than this fraction of pre-carpet flat speed, DROP it entirely (not just accept
    # best-observed like every other stage). Tighter than the naive "same as what 50%
    # exposure cost" (8-10%, R0 in robustness-backlog.md) -- at 5x lighter exposure the
    # proportional expectation is closer to ~1.5-2%, and R0's own verdict blamed the
    # fine-tune-with-nothing-to-gain mechanism as much as raw exposure frequency, so the
    # risk isn't purely frequency-proportional. User settled on 5% (between the original
    # 8% ask and this script's first 3% recommendation).
CARPET_KEYS = {"CARPET", "CARPET_PROB", "CARPET_SOFT"}
CARPET_STAGE_IDX = 2   # STAGES[2] -- used to strip carpet from every later stage if dropped

# (tag, desc, cumulative_extra_env, cumulative_cells)
STAGES = [
    ("r3_seq_s0_flat", "flat ground baseline, no mechanics",
        {}, ["T1.1"]),
    ("r3_seq_s1_transition", "+ surface transition (material only)",
        {"SURFACE_TRANSITION_PROB": "0.25"}, ["T1.1", "T4.1"]),
    ("r3_seq_s2_carpet", "+ carpet (light exposure -- R0 in robustness-backlog.md already "
        "showed 50% carpet costs 8-10% flat-ground speed for zero capability gain, base gait "
        "handles carpet at 0% falls untrained; 10% keeps light exposure open to a future "
        "fine-tune without repeating that cost)",
        {"SURFACE_TRANSITION_PROB": "0.25", "CARPET": "0.013", "CARPET_PROB": "0.10",
         "CARPET_SOFT": "0.2"}, ["T1.1", "T4.1", "T10.1"]),
    ("r3_seq_s3_step", "+ transition step (12mm)",
        {"SURFACE_TRANSITION_PROB": "0.25", "SURFACE_TRANSITION_STEP_M": "0.012",
         "CARPET": "0.013", "CARPET_PROB": "0.10", "CARPET_SOFT": "0.2"},
        ["T1.1", "T4.1", "T4.2", "T10.1"]),
    ("r3_seq_s4_snag", "+ snag obstacles",
        {"SURFACE_TRANSITION_PROB": "0.25", "SURFACE_TRANSITION_STEP_M": "0.012",
         "CARPET": "0.013", "CARPET_PROB": "0.10", "CARPET_SOFT": "0.2",
         "SNAG_OBSTACLE_PROB": "0.20"},
        ["T1.1", "T4.1", "T4.2", "T10.1", "T7.2"]),
    ("r3_seq_s5_ledge", "+ ledges (hardest, trained last on purpose; height ceiling raised "
        "30mm->35mm per user instruction -- harder than the prior campaign but still well "
        "under the 40mm 'past-comfortable stress' cell where both learned and scripted "
        "already survive 60% of the time, so it stays passable, not just harder)",
        {"SURFACE_TRANSITION_PROB": "0.25", "SURFACE_TRANSITION_STEP_M": "0.012",
         "CARPET": "0.013", "CARPET_PROB": "0.10", "CARPET_SOFT": "0.2",
         "SNAG_OBSTACLE_PROB": "0.20",
         "LEDGE_HEIGHT": "0.035", "LEDGE_PROB": "0.20", "LEDGE_RANDOMIZE": "1"},
        ["T1.1", "T4.1", "T4.2", "T10.1", "T7.2", "T5.1", "T5.2", "T5.3"]),
]


def log(msg):
    line = f"[seq {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _run_one(tag, extra, from_ckpt, cells, retry_kind=None):
    env = {f"G2E_{k}": v for k, v in extra.items()}
    kwargs = {}
    if retry_kind == "lr":
        kwargs = dict(finetune_lr=RETRY_LR, finetune_target_kl="0.08")
    elif retry_kind == "reward":
        # ledges-specific hypothesis (r3 reward analysis): FAC_RESIDUAL_COST /
        # FAC_RESID_SMOOTH may be over-constraining the large corrective action a
        # ledge crossing needs. Loosen both, keep the gentle finetune LR.
        env = dict(env, G2E_FAC_RESIDUAL_COST="1.8", G2E_FAC_RESID_SMOOTH="5.5")
    log(f"--- {tag}: launching{f' (retry: {retry_kind})' if retry_kind else ''}"
        f"{f', continuing from {from_ckpt}' if from_ckpt else ' (fresh)'}")
    RP.launch(tag, env, steps=STEPS, from_ckpt=from_ckpt, **kwargs)
    ok, reason = RP.wait_for_finish(tag)
    if not ok:
        log(f"{tag} HALT: {reason}")
        raise SystemExit(1)
    # score against every cumulative cell using the run's own final checkpoint step count.
    # _score_checkpoint always benchmarks T1.1 first regardless of what's in the cell list,
    # so one call gives both flat-ground and every other cell -- no need for a second call.
    ckpts = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"))
    final_step = max(int(p.rsplit("_", 2)[-2]) for p in ckpts) if ckpts else int(float(STEPS))
    flat_fell, flat_speed, skills = RP._score_checkpoint(tag, final_step, [c for c in cells if c != "T1.1"])
    log(f"{tag} scored @ {final_step}: T1.1 fell {flat_fell:.3f} speed {flat_speed:.4f}; "
        f"per-cell: {skills}")
    return dict(tag=tag, final_step=final_step, flat_fell=flat_fell, flat_speed=flat_speed,
                skills=skills)


def run_stage(i, from_tag, stages, prev_flat_speed=None):
    """`stages` is the (possibly carpet-stripped) working copy main() maintains --
    never reads the module-level STAGES directly, so a mid-chain drop-carpet
    decision actually changes what later stages train on."""
    family_tag, desc, extra, cells = stages[i]
    new_cells = cells if i == 0 else [c for c in cells if c not in stages[i - 1][3]]
    from_ckpt = f"trained/{from_tag}_ppo" if from_tag else None
    is_ledge_stage = family_tag == "r3_seq_s5_ledge"
    is_carpet_stage = i == CARPET_STAGE_IDX

    # Each attempt gets its OWN concrete tag (not the family tag) -- retries
    # otherwise overwrite the previous attempt's checkpoint files on disk
    # before "best of attempts" can compare them, silently breaking the
    # fallback-to-best-observed guarantee.
    def _attempt_tag(n):
        return f"{family_tag}_try{n}"

    def _gate_ok(r):
        if r["flat_fell"] > RP.FLAT_REGRESSION_FELL_MAX:
            return False, f"T1.1 regressed (fell {r['flat_fell']:.3f})"
        for c in new_cells:
            if c == "T1.1":
                continue
            v = r["skills"].get(c, 1.0)
            if v > NEW_SKILL_LEARNABLE_MAX:
                return False, f"new cell {c} shows no learning signal (fell {v:.3f})"
        prior_cells = [c for c in cells if c not in new_cells and c != "T1.1"]
        for c in prior_cells:
            v = r["skills"].get(c, 1.0)
            if v > PRIOR_SKILL_COLLAPSE_MAX:
                return False, f"prior cell {c} collapsed (fell {v:.3f}, was clean before this stage)"
        if is_carpet_stage and prev_flat_speed:
            drop = (prev_flat_speed - r["flat_speed"]) / prev_flat_speed
            if drop > CARPET_SPEED_REGRESSION_MAX:
                return False, (f"carpet cost {drop:.1%} flat-ground speed "
                                f"(> {CARPET_SPEED_REGRESSION_MAX:.0%} bar)")
        return True, "clean"

    result = _run_one(_attempt_tag(0), extra, from_ckpt, cells)
    attempts = [result]
    ok, reason = _gate_ok(result)
    retries = 0
    # retry 1 = gentler LR (same hypothesis: the standard finetune LR was too
    # timid to actually learn the new mechanic in 3M). retry 2, ledges only =
    # a genuinely different hypothesis (the reward analysis's residual-budget
    # finding) rather than repeating the same knob a second time for no reason.
    retry_kinds = ["lr", "reward" if is_ledge_stage else "lr"]
    while not ok and retries < 2:
        kind = retry_kinds[retries]
        retries += 1
        log(f"{family_tag} gate FAILED ({reason}) -- retry {retries}/2 ({kind})")
        result = _run_one(_attempt_tag(retries), extra, from_ckpt, cells, retry_kind=kind)
        attempts.append(result)
        ok, reason = _gate_ok(result)

    best = min(attempts, key=lambda r: r["flat_fell"] + sum(
        r["skills"].get(c, 1.0) for c in new_cells if c != "T1.1"))
    # Carpet is the one stage where "use the best state produced" is NOT the
    # fallback -- per explicit user instruction, a speed regression this size
    # means dropping carpet entirely, not accepting whatever attempt lost the
    # least. speed_dropped checks the reason on the LAST attempt specifically
    # (a fall-rate failure that also happens to have bad speed shouldn't be
    # misread as a "drop carpet" case).
    speed_dropped = (is_carpet_stage and not ok and prev_flat_speed and reason.startswith("carpet cost"))
    if speed_dropped:
        log(f"{family_tag}: DROPPING CARPET -- {reason} even after {retries} retries. "
            f"Per user instruction, this isn't a best-observed-and-move-on case -- carpet is "
            f"removed from this and every later stage's config, T10.1 dropped from tracked cells. "
            f"Chain continues from {from_tag} (stage 1's checkpoint) as if carpet were never tried.")
    elif not ok:
        log(f"{family_tag}: no attempt cleared the gate after {retries} retries -- "
            f"using best-observed ({best['tag']}, attempt {attempts.index(best) + 1}/"
            f"{len(attempts)}) per standing instruction to use the best state produced "
            f"rather than block the chain")
    else:
        log(f"{family_tag}: gate passed via {best['tag']} "
            f"({'first try' if retries == 0 else f'retry {retries}'})")
    return dict(family_tag=family_tag, desc=desc, cells=cells, gate_passed=ok, retries=retries,
                attempts=len(attempts), speed_dropped=speed_dropped,
                **{k: best[k] for k in ("tag", "final_step", "flat_fell", "flat_speed", "skills")})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-stage", type=int, default=0, help="resume from this stage index (0-5)")
    args = ap.parse_args()
    log("=== sequential chain started ===")
    summary = []
    from_tag = None
    prev_flat_speed = None
    # Mutable working copy -- a mid-chain drop-carpet decision strips CARPET_KEYS
    # and T10.1 from every stage AFTER the carpet stage, so later stages actually
    # train without it instead of just cosmetically skipping stage 2.
    stages = [(tag, desc, dict(extra), list(cells)) for tag, desc, extra, cells in STAGES]
    if args.from_stage > 0:
        # reload prior stages' results if resuming, so the final summary/report is complete
        # AND so from_tag is the winning attempt's real tag (e.g. "..._try1"), not the
        # family tag, which never has its own checkpoint files.
        if not os.path.exists("trained/phase_r_sequential_summary.json"):
            raise SystemExit("--from-stage > 0 needs trained/phase_r_sequential_summary.json "
                              "to recover the previous stage's winning checkpoint tag")
        summary = json.load(open("trained/phase_r_sequential_summary.json"))[:args.from_stage]
        from_tag = summary[-1]["tag"]
        prev_flat_speed = summary[-1]["flat_speed"]
        if any(s.get("speed_dropped") for s in summary):
            log("Resuming with carpet already dropped in a prior run -- stripping it from stages "
                f"{args.from_stage}+ too")
            for j in range(CARPET_STAGE_IDX + 1, len(stages)):
                tag, desc, extra, cells = stages[j]
                stages[j] = (tag, desc, {k: v for k, v in extra.items() if k not in CARPET_KEYS},
                             [c for c in cells if c != "T10.1"])
    for i in range(args.from_stage, len(stages)):
        res = run_stage(i, from_tag, stages, prev_flat_speed=prev_flat_speed)
        summary.append(res)
        with open("trained/phase_r_sequential_summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        if res.get("speed_dropped"):
            # from_tag deliberately NOT updated -- carry forward the checkpoint from
            # BEFORE carpet, as if this stage never happened. Strip carpet from every
            # later stage so they actually train without it, not just skip stage 2.
            for j in range(i + 1, len(stages)):
                tag, desc, extra, cells = stages[j]
                stages[j] = (tag, desc, {k: v for k, v in extra.items() if k not in CARPET_KEYS},
                             [c for c in cells if c != "T10.1"])
        else:
            from_tag = res["tag"]
            prev_flat_speed = res["flat_speed"]
    log(f"=== sequential chain complete -- final checkpoint: {from_tag} ===")

    # Per explicit user instruction: the 20M run IS the last step of this plan
    # (continuing stage 5's checkpoint, not a separate fresh "qualify" run),
    # gated at 3M/10M via the same machinery run_pipeline.py's Phase C uses --
    # and the benchmark report runs only AFTER that finishes, against the
    # fully-trained policy, not the raw stage-5 checkpoint.
    all_cells = [c for c in stages[-1][3] if c != "T1.1"]   # working copy -- reflects a dropped carpet
    from_ckpt = f"trained/{from_tag}_ppo"
    passed = RP.run_gated_20m(FINAL_20M_TAG, {}, all_cells, INTERIM_NAME,
                              from_ckpt=from_ckpt, label="Sequential-chain 20M")
    if not passed:
        log("Sequential-chain 20M did not clear its gate -- stopping here. "
            f"{FINAL_20M_TAG}'s dress-rehearsal checkpoint is kept on disk for review; "
            "no benchmark report will be generated against an unfinished/failed run.")
        return

    carpet_dropped = any(s.get("speed_dropped") for s in summary)
    skip_flag = " --skip-sections carpet" if carpet_dropped else ""
    if carpet_dropped:
        log("Carpet was dropped during training -- excluding it from the benchmark report too, "
            "per user instruction. Benchmarking a mechanic that was never actually trained on "
            "this candidate would misrepresent what it can do.")
    log(f"Running the full benchmark report against {INTERIM_NAME} (learned vs. scripted, "
        "per category, with GIFs) -- same treatment as Deployment_CandidateV1")
    r = subprocess.run(
        f"{RP.PY} phase_c_report.py --tag {INTERIM_NAME} --out {V2_REPORT}{skip_flag}", shell=True)
    if r.returncode != 0:
        log(f"Benchmark report FAILED (exit {r.returncode}) -- {INTERIM_NAME} is still on "
            "disk and complete, the report can be re-run manually")
        raise SystemExit(1)

    _compare_and_maybe_promote()
    log(f"=== all done -- see {V2_REPORT} and trained/report_gifs_{INTERIM_NAME}/ ===")


def _compare_and_maybe_promote():
    """Per explicit user instruction: only promote to RELEASE_NAME if this run beats
    Deployment_CandidateV1, not just because it finished a clean 20M. 'Beats' mirrors
    the project's own established 'scripted+' bar (beat on every cell, not just net
    average) applied to V1 instead of scripted: no category may regress by more than
    a noise-sized margin, and at least one category must be a clear win -- otherwise
    this is a lateral move (or a loss), not an improvement, regardless of what it
    finished at 20M."""
    if not os.path.exists(V1_REPORT):
        log(f"No promotion comparison possible -- {V1_REPORT} not found. "
            f"{INTERIM_NAME} stays under its interim name for manual review.")
        return
    v1 = {s["slug"]: s for s in json.load(open(V1_REPORT))["sections"]}
    v2 = {s["slug"]: s for s in json.load(open(V2_REPORT))["sections"]}
    NOISE = 0.05   # +/-5 percentage points on fell-rate is within run-to-run noise at 20 episodes
    verdicts = {}
    for slug in v1:
        if slug not in v2:
            continue
        d = v2[slug]["learned_fell"] - v1[slug]["learned_fell"]   # negative = V2 fell less = better
        if d < -NOISE:
            verdicts[slug] = "win"
        elif d > NOISE:
            verdicts[slug] = "loss"
        else:
            verdicts[slug] = "tie"
    wins = [s for s, v in verdicts.items() if v == "win"]
    losses = [s for s, v in verdicts.items() if v == "loss"]
    log(f"V2 vs V1 per category: {verdicts}")
    if losses:
        log(f"NOT promoting -- {INTERIM_NAME} regresses {losses} vs Deployment_CandidateV1 "
            f"by more than noise ({NOISE:.0%}), even though it won on {wins or 'none'}. "
            f"Staying under the interim name for review; this is a tradeoff, not a clean win.")
    elif not wins:
        log(f"NOT promoting -- {INTERIM_NAME} ties Deployment_CandidateV1 on every category "
            f"({list(verdicts)}), no clear win anywhere. A lateral move isn't grounds for "
            f"promotion. Staying under the interim name.")
    else:
        src = f"trained/{INTERIM_NAME}_ppo.zip"
        dst = f"trained/{RELEASE_NAME}_ppo.zip"
        os.rename(src, dst)
        log(f"PROMOTED: {INTERIM_NAME} beats Deployment_CandidateV1 on {wins}, regresses nowhere "
            f"-- renamed {src} -> {dst}. Still not auto-promoted to DEFAULT_POLICY (hardware-gated, "
            f"separate decision, same convention as V1).")


if __name__ == "__main__":
    main()
