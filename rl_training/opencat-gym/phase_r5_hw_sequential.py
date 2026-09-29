"""Real-hardware-IMU retrain of Release_CandidateV2.1's recipe (2026-09-28).

Identical staged campaign to phase_r_sequential.py (flat -> transition ->
carpet -> step -> snag -> ledge, each stage continuing cumulatively from the
last), but with run_pipeline.BASE's G2E_IMU_HOLD_STEPS corrected from 16 (models
a 5 Hz IMU refresh) to 1 (models the ~93-249 Hz this session actually measured
against the real BiBoard -- see docs/hardware/petoi-firmware-reference.md).
That's the one deliberate difference from the original recipe; every other
knob, stage, gate, and mechanic is unchanged.

Tagged r5_hw_* throughout so nothing here can collide with or overwrite
Release_CandidateV2 / V2.1's existing checkpoints and reports on disk.

Compares its own final benchmark against Release_CandidateV2.1's historic
report (trained/phase_yaw_tuning_report.json) -- per explicit user
instruction, NOT against Deployment_CandidateV1 (this script does not
reproduce phase_r_sequential.py's V1-comparison/auto-promote step at all).

Adds one thing phase_r_sequential.py didn't have: an informational-only 5M
checkpoint score during the final 20M run (alongside the existing 3M sanity
check and 10M dress-rehearsal gate), purely for regression visibility --
doesn't stop or redirect the run either way.

    python phase_r5_hw_sequential.py
    python phase_r5_hw_sequential.py --from-stage 3   # resume after a manual stop
"""
import argparse
import glob
import json
import os
import subprocess
import time

import run_pipeline as RP  # BASE already carries G2E_IMU_HOLD_STEPS=1 as of 2026-09-28

LOG = "trained/phase_r5_hw_sequential.log"
STEPS = "3e6"
FINAL_20M_TAG = "r5_hw_20m"
INTERIM_NAME = "r5_hw_candidate"
V21_REPORT = "trained/phase_yaw_r3_report.json"   # Release_CandidateV2.1's own historic benchmark --
    # this is the actual file on disk; phase_yaw_tuning.py's own subprocess call names a different
    # path (trained/phase_yaw_tuning_report.json) that was never actually produced, caught 2026-09-28
    # before this script's first real run reached its comparison step
OUT_REPORT = "trained/phase_r5_hw_sequential_report.json"
RETRY_LR = "1e-4"
NEW_SKILL_LEARNABLE_MAX = 0.85
PRIOR_SKILL_COLLAPSE_MAX = 0.50
CARPET_SPEED_REGRESSION_MAX = 0.05
CARPET_KEYS = {"CARPET", "CARPET_PROB", "CARPET_SOFT"}
CARPET_STAGE_IDX = 2
MID_CHECK_STEP = 5000000   # informational only, doesn't gate anything

# Identical to phase_r_sequential.py's STAGES -- same recipe, same cells.
STAGES = [
    ("r5_hw_s0_flat", "flat ground baseline, no mechanics",
        {}, ["T1.1"]),
    ("r5_hw_s1_transition", "+ surface transition (material only)",
        {"SURFACE_TRANSITION_PROB": "0.25"}, ["T1.1", "T4.1"]),
    ("r5_hw_s2_carpet", "+ carpet (light exposure)",
        {"SURFACE_TRANSITION_PROB": "0.25", "CARPET": "0.013", "CARPET_PROB": "0.10",
         "CARPET_SOFT": "0.2"}, ["T1.1", "T4.1", "T10.1"]),
    ("r5_hw_s3_step", "+ transition step (12mm)",
        {"SURFACE_TRANSITION_PROB": "0.25", "SURFACE_TRANSITION_STEP_M": "0.012",
         "CARPET": "0.013", "CARPET_PROB": "0.10", "CARPET_SOFT": "0.2"},
        ["T1.1", "T4.1", "T4.2", "T10.1"]),
    ("r5_hw_s4_snag", "+ snag obstacles",
        {"SURFACE_TRANSITION_PROB": "0.25", "SURFACE_TRANSITION_STEP_M": "0.012",
         "CARPET": "0.013", "CARPET_PROB": "0.10", "CARPET_SOFT": "0.2",
         "SNAG_OBSTACLE_PROB": "0.20"},
        ["T1.1", "T4.1", "T4.2", "T10.1", "T7.2"]),
    ("r5_hw_s5_ledge", "+ ledges (hardest, trained last on purpose)",
        {"SURFACE_TRANSITION_PROB": "0.25", "SURFACE_TRANSITION_STEP_M": "0.012",
         "CARPET": "0.013", "CARPET_PROB": "0.10", "CARPET_SOFT": "0.2",
         "SNAG_OBSTACLE_PROB": "0.20",
         "LEDGE_HEIGHT": "0.035", "LEDGE_PROB": "0.20", "LEDGE_RANDOMIZE": "1"},
        ["T1.1", "T4.1", "T4.2", "T10.1", "T7.2", "T5.1", "T5.2", "T5.3"]),
]


def log(msg):
    line = f"[r5hw {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _score_yaw(tag, step):
    """Same narrow yaw-only helper as phase_yaw_tuning.py's _score_yaw --
    run_pipeline._score_checkpoint doesn't expose yaw metrics."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 1, True, "i"
    E.CMD_SEND_EVERY_N = 3
    E.EPISODE_LENGTH = 250
    s, _ = _bench(env, m, 20, 1000)
    env.close()
    return float(s["yaw_rate_rms_deg_mean"]), float(s.get("heading_drift_deg_mean", float("nan")))


def _run_one(tag, extra, from_ckpt, cells, retry_kind=None):
    env = {f"G2E_{k}": v for k, v in extra.items()}
    kwargs = {}
    if retry_kind == "lr":
        kwargs = dict(finetune_lr=RETRY_LR, finetune_target_kl="0.08")
    elif retry_kind == "reward":
        env = dict(env, G2E_FAC_RESIDUAL_COST="1.8", G2E_FAC_RESID_SMOOTH="5.5")
    log(f"--- {tag}: launching{f' (retry: {retry_kind})' if retry_kind else ''}"
        f"{f', continuing from {from_ckpt}' if from_ckpt else ' (fresh)'}")
    RP.launch(tag, env, steps=STEPS, from_ckpt=from_ckpt, **kwargs)
    ok, reason = RP.wait_for_finish(tag)
    if not ok:
        log(f"{tag} HALT: {reason}")
        raise SystemExit(1)
    ckpts = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"))
    final_step = max(int(p.rsplit("_", 2)[-2]) for p in ckpts) if ckpts else int(float(STEPS))
    flat_fell, flat_speed, skills = RP._score_checkpoint(tag, final_step, [c for c in cells if c != "T1.1"])
    log(f"{tag} scored @ {final_step}: T1.1 fell {flat_fell:.3f} speed {flat_speed:.4f}; "
        f"per-cell: {skills}")
    return dict(tag=tag, final_step=final_step, flat_fell=flat_fell, flat_speed=flat_speed,
                skills=skills)


def run_stage(i, from_tag, stages, prev_flat_speed=None):
    family_tag, desc, extra, cells = stages[i]
    new_cells = cells if i == 0 else [c for c in cells if c not in stages[i - 1][3]]
    from_ckpt = f"trained/{from_tag}_ppo" if from_tag else None
    is_ledge_stage = family_tag == "r5_hw_s5_ledge"
    is_carpet_stage = i == CARPET_STAGE_IDX

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
    speed_dropped = (is_carpet_stage and not ok and prev_flat_speed and reason.startswith("carpet cost"))
    if speed_dropped:
        log(f"{family_tag}: DROPPING CARPET -- {reason} even after {retries} retries. "
            f"Chain continues from {from_tag} as if carpet were never tried.")
    elif not ok:
        log(f"{family_tag}: no attempt cleared the gate after {retries} retries -- "
            f"using best-observed ({best['tag']}, attempt {attempts.index(best) + 1}/{len(attempts)})")
    else:
        log(f"{family_tag}: gate passed via {best['tag']} "
            f"({'first try' if retries == 0 else f'retry {retries}'})")
    return dict(family_tag=family_tag, desc=desc, cells=cells, gate_passed=ok, retries=retries,
                attempts=len(attempts), speed_dropped=speed_dropped,
                **{k: best[k] for k in ("tag", "final_step", "flat_fell", "flat_speed", "skills")})


def run_gated_20m_with_midcheck(tag, extra, all_cells, deployment_name, from_ckpt=None, label="Final 20M"):
    """Same contract as run_pipeline.run_gated_20m (3M sanity kill-switch, 10M
    dress-rehearsal continue/stop decision, rename to deployment_name on a
    clean 20M finish) plus one addition: an informational-only checkpoint
    score at MID_CHECK_STEP (5M), logged for regression visibility but never
    gating the run either way -- per explicit user request for a 3M/5M/10M
    check on this run specifically."""
    log(f"{label}: launching {tag} -- 20M-step schedule, gated at 3M/10M, "
        f"informational check at {MID_CHECK_STEP}"
        f"{f', continuing from {from_ckpt}' if from_ckpt else ''}")
    RP.launch(tag, extra, steps="20e6", from_ckpt=from_ckpt)

    ok, reason = RP.wait_for_ckpt(tag, RP.GATE_STEP)
    if not ok:
        log(f"{label} HALT: {reason}")
        raise SystemExit(1)
    early_fell, early_speed, early_skills = RP._score_checkpoint(tag, RP.GATE_STEP, all_cells)
    early_worst_cell, early_worst_fell = max(early_skills.items(), key=lambda kv: kv[1]) if early_skills else (None, 0.0)
    log(f"{label} 3M sanity check: T1.1 fell {early_fell:.3f}, speed {early_speed:.4f}; "
        f"per-cell skill fell: {early_skills}")
    if early_fell > RP.FLAT_REGRESSION_FELL_MAX and early_worst_fell > 0.9:
        log(f"{label} EARLY STOP: flat-ground regressed AND no learning signal on any cell "
            f"(worst {early_worst_cell} fell {early_worst_fell:.3f}) -- halting at 3M.")
        RP.stop(tag)
        raise SystemExit(1)

    ok, reason = RP.wait_for_ckpt(tag, MID_CHECK_STEP)
    if ok:
        mid_fell, mid_speed, mid_skills = RP._score_checkpoint(tag, MID_CHECK_STEP, all_cells)
        log(f"{label} 5M informational check (not a gate): T1.1 fell {mid_fell:.3f}, "
            f"speed {mid_speed:.4f}; per-cell skill fell: {mid_skills}")
    else:
        log(f"{label} 5M informational check skipped ({reason}) -- continuing regardless")

    ok, reason = RP.wait_for_ckpt(tag, RP.DRESS_REHEARSAL_STEP)
    if not ok:
        log(f"{label} HALT: {reason}")
        raise SystemExit(1)
    fell, speed, skill_results = RP._score_checkpoint(tag, RP.DRESS_REHEARSAL_STEP, all_cells)
    log(f"{label} dress-rehearsal report ({RP.DRESS_REHEARSAL_STEP} steps): "
        f"T1.1 fell {fell:.3f}, speed {speed:.4f}; per-cell skill fell: {skill_results}")

    flat_ok = fell <= RP.FLAT_REGRESSION_FELL_MAX
    worst_cell, worst_fell = max(skill_results.items(), key=lambda kv: kv[1]) if skill_results else (None, 0.0)
    skills_ok = worst_fell <= RP.DRESS_SKILL_FAIL_MAX
    if flat_ok and skills_ok:
        log(f"{label} DECISION: CONTINUE to 20M -- T1.1 fell {fell:.3f}, worst {worst_cell} "
            f"fell {worst_fell:.3f}. {tag} keeps running with zero restart.")
        ok, reason = RP.wait_for_finish(tag)
        if not ok:
            log(f"{label}: {tag} did not finish cleanly ({reason}) -- not renaming.")
            raise SystemExit(1)
        os.rename(f"trained/{tag}_ppo.zip", f"trained/{deployment_name}_ppo.zip")
        log(f"{label} complete: renamed trained/{tag}_ppo.zip -> trained/{deployment_name}_ppo.zip")
        return True
    why = []
    if not flat_ok:
        why.append(f"T1.1 fell {fell:.3f} > {RP.FLAT_REGRESSION_FELL_MAX}")
    if not skills_ok:
        why.append(f"{worst_cell} fell {worst_fell:.3f} > {RP.DRESS_SKILL_FAIL_MAX}")
    log(f"{label} DECISION: STOP -- {', '.join(why)}. Halting {tag} short of 20M.")
    RP.stop(tag)
    return False


def _compare_vs_v21_and_scripted(new_report_path):
    """Per explicit user instruction: compare against Release_CandidateV2.1's
    historic report (not V1 or hw1_20m) AND against the scripted gait -- so the
    final report shows both how the real-hardware-IMU retrain changed things
    relative to V2.1, and how it now stands against scripted. phase_c_report.py's
    sections already carry scripted_fell/scripted_speed/scripted_yaw_rate_rms_deg
    alongside the learned_* fields, pulled from the NEW report (measured under
    this run's own eval pass, not copied from V2.1's).
    Returns (per_category table, verdicts-vs-v21 dict, v21's flat yaw_rms)."""
    new = {s["slug"]: s for s in json.load(open(new_report_path))["sections"]}
    v21 = {}
    if os.path.exists(V21_REPORT):
        v21 = {s["slug"]: s for s in json.load(open(V21_REPORT))["sections"]}
    else:
        log(f"No V2.1 comparison possible -- {V21_REPORT} not found.")
    NOISE = 0.05
    table = []
    verdicts = {}
    for slug, sec in new.items():
        row = dict(slug=slug, name=sec.get("name", slug),
                   new_fell=sec.get("learned_fell"), new_speed=sec.get("learned_speed"),
                   scripted_fell=sec.get("scripted_fell"), scripted_speed=sec.get("scripted_speed"),
                   new_yaw_rms=sec.get("learned_yaw_rate_rms_deg"),
                   scripted_yaw_rms=sec.get("scripted_yaw_rate_rms_deg"))
        if slug in v21:
            row["v21_fell"] = v21[slug].get("learned_fell")
            row["v21_speed"] = v21[slug].get("learned_speed")
            row["v21_yaw_rms"] = v21[slug].get("learned_yaw_rate_rms_deg")
            d = row["new_fell"] - row["v21_fell"]
            row["verdict_vs_v21"] = "win" if d < -NOISE else ("loss" if d > NOISE else "tie")
            verdicts[slug] = row["verdict_vs_v21"]
        if row["new_fell"] is not None and row["scripted_fell"] is not None:
            d2 = row["new_fell"] - row["scripted_fell"]
            row["verdict_vs_scripted"] = "win" if d2 < -NOISE else ("loss" if d2 > NOISE else "tie")
        table.append(row)
    log(f"r5_hw vs Release_CandidateV2.1 per category: {verdicts}")
    log(f"r5_hw vs scripted per category: "
        f"{ {r['slug']: r.get('verdict_vs_scripted') for r in table} }")
    return table, verdicts, v21.get("flat_ground", {}).get("learned_yaw_rate_rms_deg")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-stage", type=int, default=0)
    args = ap.parse_args()
    log("=== r5_hw sequential chain started (real-hardware IMU rate) ===")
    summary = []
    from_tag = None
    prev_flat_speed = None
    stages = [(tag, desc, dict(extra), list(cells)) for tag, desc, extra, cells in STAGES]
    if args.from_stage > 0:
        if not os.path.exists("trained/phase_r5_hw_sequential_summary.json"):
            raise SystemExit("--from-stage > 0 needs trained/phase_r5_hw_sequential_summary.json")
        summary = json.load(open("trained/phase_r5_hw_sequential_summary.json"))[:args.from_stage]
        from_tag = summary[-1]["tag"]
        prev_flat_speed = summary[-1]["flat_speed"]
        if any(s.get("speed_dropped") for s in summary):
            for j in range(CARPET_STAGE_IDX + 1, len(stages)):
                tag, desc, extra, cells = stages[j]
                stages[j] = (tag, desc, {k: v for k, v in extra.items() if k not in CARPET_KEYS},
                             [c for c in cells if c != "T10.1"])
    for i in range(args.from_stage, len(stages)):
        res = run_stage(i, from_tag, stages, prev_flat_speed=prev_flat_speed)
        summary.append(res)
        with open("trained/phase_r5_hw_sequential_summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        if res.get("speed_dropped"):
            for j in range(i + 1, len(stages)):
                tag, desc, extra, cells = stages[j]
                stages[j] = (tag, desc, {k: v for k, v in extra.items() if k not in CARPET_KEYS},
                             [c for c in cells if c != "T10.1"])
        else:
            from_tag = res["tag"]
            prev_flat_speed = res["flat_speed"]
    log(f"=== sequential chain complete -- final checkpoint: {from_tag} ===")

    all_cells = [c for c in stages[-1][3] if c != "T1.1"]
    from_ckpt = f"trained/{from_tag}_ppo"
    passed = run_gated_20m_with_midcheck(FINAL_20M_TAG, {}, all_cells, INTERIM_NAME,
                                        from_ckpt=from_ckpt, label="r5_hw final 20M")
    if not passed:
        log("r5_hw final 20M did not clear its gate -- stopping here, no benchmark report.")
        return

    carpet_dropped = any(s.get("speed_dropped") for s in summary)
    skip_flag = " --skip-sections carpet" if carpet_dropped else ""
    log(f"Running the full benchmark report against {INTERIM_NAME}")
    r = subprocess.run(
        f"{RP.PY} phase_c_report.py --tag {INTERIM_NAME} --out {OUT_REPORT}{skip_flag}", shell=True)
    if r.returncode != 0:
        log(f"Benchmark report FAILED (exit {r.returncode}) -- {INTERIM_NAME} still on disk, "
            "report can be re-run manually")
        raise SystemExit(1)

    ckpts = sorted(glob.glob(f"trained/checkpoints/{FINAL_20M_TAG}_*_steps.zip"))
    final_step = max(int(p.rsplit("_", 2)[-2]) for p in ckpts) if ckpts else RP.DRESS_REHEARSAL_STEP
    yaw_rms, drift = _score_yaw(FINAL_20M_TAG, final_step) if ckpts else (None, None)
    log(f"r5_hw final yaw_rms={yaw_rms}, heading_drift={drift}")

    table, verdicts, v21_yaw_rms = _compare_vs_v21_and_scripted(OUT_REPORT)
    losses = [s for s, v in verdicts.items() if v == "loss"]
    beats_or_ties = not losses if verdicts else None   # None = no V2.1 comparison was possible at all
    yaw_needs_work = (yaw_rms is not None and v21_yaw_rms is not None and yaw_rms >= v21_yaw_rms - 0.15)

    with open("trained/phase_r5_hw_gate_decision.json", "w") as f:
        json.dump(dict(comparison_table=table, verdicts=verdicts, beats_or_ties_v21=beats_or_ties,
                       yaw_rms=yaw_rms, heading_drift=drift, v21_yaw_rms=v21_yaw_rms,
                       yaw_needs_work=yaw_needs_work, final_step=final_step), f, indent=2)

    log(f"=== r5_hw base run done -- beats_or_ties_v21={beats_or_ties}, "
        f"yaw_needs_work={yaw_needs_work} -- see {OUT_REPORT} and "
        "trained/phase_r5_hw_gate_decision.json ===")


if __name__ == "__main__":
    main()
