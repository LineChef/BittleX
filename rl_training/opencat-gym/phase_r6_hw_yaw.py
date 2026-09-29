"""Conditional yaw/drift tuning round for r5_hw (2026-09-28), same shape as
phase_yaw_tuning.py's V2->V2.1 round: three light (3M) candidates test which
reward-weight lever reduces yaw wobble, the winner gets a 10M continuation
(run_pipeline.run_gated_10m). Only invoked by phase_hw_pipeline.py when r5_hw
beats-or-ties Release_CandidateV2.1 on fall-rate AND still shows elevated yaw
RMS vs V2.1's own number (trained/phase_r5_hw_gate_decision.json's
yaw_needs_work flag) -- this script itself doesn't make that call, its caller
does.

Baseline numbers are read from r5_hw's own report/gate-decision files rather
than hardcoded, since this is a fresh base run, not a copy of V2's constants.

    python phase_r6_hw_yaw.py
"""
import json
import os
import time

import run_pipeline as RP

LOG = "trained/phase_r6_hw_yaw.log"
STEPS = "3e6"
BASE_CKPT = "trained/r5_hw_candidate_ppo"
ALL_CELLS = ["T4.1", "T4.2", "T10.1", "T7.2", "T5.1", "T5.2"]   # T5.3 excluded, same reasoning
                                                                  # as phase_yaw_tuning.py: ledge-height
                                                                  # capability limit, not a yaw issue
SKILL_COLLAPSE_MAX = 0.50
MID_CHECK_STEP = 5000000   # informational only, per user request for a 5M check

BASE_REPORT = "trained/phase_r5_hw_sequential_report.json"
GATE_DECISION = "trained/phase_r5_hw_gate_decision.json"
FINAL_10M_TAG = "r6_hw_yaw_10m"
INTERIM_NAME = "r6_hw_yaw_candidate"
OUT_REPORT = "trained/phase_r6_hw_yaw_report.json"

# Same three levers phase_yaw_tuning.py screened for V2 -> V2.1 -- reused
# as-is per user instruction ("the same 13m tuning run").
CANDIDATES = [
    ("r6_hw_yaw_r1", "FAC_YAW_TRACK 9.0 -> 12.0 alone",
        {"FAC_YAW_TRACK": "12.0"}),
    ("r6_hw_yaw_r2", "FAC_YAW_TRACK 9.0 -> 11.0 + FAC_RESID_SMOOTH 8.2 -> 10.0 (paired)",
        {"FAC_YAW_TRACK": "11.0", "FAC_RESID_SMOOTH": "10.0"}),
    ("r6_hw_yaw_r3", "FAC_RESID_SMOOTH 8.2 -> 10.5 alone",
        {"FAC_RESID_SMOOTH": "10.5"}),
]


def log(msg):
    line = f"[r6hw {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _baseline_yaw_rms():
    gate = json.load(open(GATE_DECISION))
    return gate["yaw_rms"]


def _score_yaw(tag, step):
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
    return float(s["yaw_rate_rms_deg_mean"])


def run_candidate(tag, desc, extra, baseline_yaw_rms):
    env = {f"G2E_{k}": v for k, v in extra.items()}
    log(f"--- {tag}: launching, continuing from {BASE_CKPT} ({desc})")
    RP.launch(tag, env, steps=STEPS, from_ckpt=BASE_CKPT)
    ok, reason = RP.wait_for_finish(tag)
    if not ok:
        log(f"{tag} HALT: {reason}")
        return None
    import glob
    ckpts = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"))
    final_step = max(int(p.rsplit("_", 2)[-2]) for p in ckpts) if ckpts else int(float(STEPS))
    flat_fell, flat_speed, skills = RP._score_checkpoint(tag, final_step, ALL_CELLS)
    yaw_rms = _score_yaw(tag, final_step)
    worst_cell, worst_fell = max(skills.items(), key=lambda kv: kv[1]) if skills else (None, 0.0)
    regressed = flat_fell > RP.FLAT_REGRESSION_FELL_MAX or worst_fell > SKILL_COLLAPSE_MAX
    log(f"{tag} scored @ {final_step}: T1.1 fell {flat_fell:.3f} speed {flat_speed:.4f} "
        f"yaw_rms {yaw_rms:.2f} (r5_hw baseline {baseline_yaw_rms:.2f}); "
        f"worst cell {worst_cell} fell {worst_fell:.3f}{' -- REGRESSED, disqualified' if regressed else ''}")
    return dict(tag=tag, desc=desc, final_step=final_step, flat_fell=flat_fell, flat_speed=flat_speed,
                skills=skills, yaw_rms=yaw_rms, regressed=regressed)


def run_gated_10m_with_midcheck(tag, extra, all_cells, deployment_name, from_ckpt, label="Yaw-tuning 10M"):
    """Same as run_pipeline.run_gated_10m plus one informational-only 5M check,
    matching phase_r5_hw_sequential.py's addition."""
    log(f"{label}: launching {tag} -- 10M-step schedule, continuing from {from_ckpt}")
    RP.launch(tag, extra, steps="10e6", from_ckpt=from_ckpt)

    ok, reason = RP.wait_for_ckpt(tag, RP.GATE_STEP)
    if not ok:
        log(f"{label} HALT: {reason}")
        raise SystemExit(1)
    early_fell, early_speed, early_skills = RP._score_checkpoint(tag, RP.GATE_STEP, all_cells)
    early_worst_cell, early_worst_fell = max(early_skills.items(), key=lambda kv: kv[1]) if early_skills else (None, 0.0)
    log(f"{label} 3M sanity check: T1.1 fell {early_fell:.3f}, speed {early_speed:.4f}; "
        f"per-cell skill fell: {early_skills}")
    if early_fell > RP.FLAT_REGRESSION_FELL_MAX and early_worst_fell > 0.9:
        log(f"{label} EARLY STOP: flat-ground regressed AND no learning signal -- halting at 3M.")
        RP.stop(tag)
        raise SystemExit(1)

    ok, reason = RP.wait_for_ckpt(tag, MID_CHECK_STEP)
    if ok:
        mid_fell, mid_speed, mid_skills = RP._score_checkpoint(tag, MID_CHECK_STEP, all_cells)
        log(f"{label} 5M informational check (not a gate): T1.1 fell {mid_fell:.3f}, "
            f"speed {mid_speed:.4f}; per-cell skill fell: {mid_skills}")
    else:
        log(f"{label} 5M informational check skipped ({reason})")

    ok, reason = RP.wait_for_finish(tag)
    if not ok:
        log(f"{label} HALT: {reason}")
        raise SystemExit(1)
    fell, speed, skill_results = RP._score_checkpoint(tag, 10000000, all_cells)
    log(f"{label} 10M final report: T1.1 fell {fell:.3f}, speed {speed:.4f}; "
        f"per-cell skill fell: {skill_results}")
    flat_ok = fell <= RP.FLAT_REGRESSION_FELL_MAX
    worst_cell, worst_fell = max(skill_results.items(), key=lambda kv: kv[1]) if skill_results else (None, 0.0)
    skills_ok = worst_fell <= RP.DRESS_SKILL_FAIL_MAX
    if flat_ok and skills_ok:
        os.rename(f"trained/{tag}_ppo.zip", f"trained/{deployment_name}_ppo.zip")
        log(f"{label} complete: renamed trained/{tag}_ppo.zip -> trained/{deployment_name}_ppo.zip")
        return True
    why = []
    if not flat_ok:
        why.append(f"T1.1 fell {fell:.3f} > {RP.FLAT_REGRESSION_FELL_MAX}")
    if not skills_ok:
        why.append(f"{worst_cell} fell {worst_fell:.3f} > {RP.DRESS_SKILL_FAIL_MAX}")
    log(f"{label} DECISION: regressed -- {', '.join(why)}. {tag}'s checkpoint kept for review.")
    return False


def main():
    log("=== r6_hw yaw-tuning round started ===")
    baseline_yaw_rms = _baseline_yaw_rms()
    results = []
    for tag, desc, extra in CANDIDATES:
        r = run_candidate(tag, desc, extra, baseline_yaw_rms)
        if r:
            results.append(r)
        with open("trained/phase_r6_hw_yaw_summary.json", "w") as f:
            json.dump(results, f, indent=2)

    valid = [r for r in results if not r["regressed"]]
    if not valid:
        log("=== all candidates regressed or failed to launch -- no winner, needs manual review ===")
        return

    winner = min(valid, key=lambda r: r["yaw_rms"])
    log(f"=== light-round winner: {winner['tag']} ({winner['desc']}) -- "
        f"yaw_rms {winner['yaw_rms']:.2f} (r5_hw baseline {baseline_yaw_rms:.2f}) ===")

    winner_extra = dict(next(e for t, d, e in CANDIDATES if t == winner["tag"]))
    winner_env = {f"G2E_{k}": v for k, v in winner_extra.items()}
    from_ckpt = f"trained/checkpoints/{winner['tag']}_{winner['final_step']}_steps"
    passed = run_gated_10m_with_midcheck(FINAL_10M_TAG, winner_env, ALL_CELLS, INTERIM_NAME,
                                        from_ckpt=from_ckpt, label="r6_hw yaw-tuning 10M")
    if not passed:
        log("r6_hw yaw-tuning 10M regressed -- stopping here.")
        return

    r = __import__("subprocess").run(
        f"{RP.PY} phase_c_report.py --tag {INTERIM_NAME} --out {OUT_REPORT}", shell=True)
    if r.returncode != 0:
        log(f"Benchmark report FAILED (exit {r.returncode}) -- {INTERIM_NAME} still on disk")
        return

    base = {s["slug"]: s for s in json.load(open(BASE_REPORT))["sections"]}
    tuned = {s["slug"]: s for s in json.load(open(OUT_REPORT))["sections"]}
    NOISE = 0.05
    losses = [slug for slug in base if slug in tuned
             and tuned[slug]["learned_fell"] - base[slug]["learned_fell"] > NOISE]
    tuned_yaw = tuned.get("flat_ground", {}).get("learned_yaw_rate_rms_deg", 99)
    yaw_improved = tuned_yaw < baseline_yaw_rms - 0.15
    log(f"r6_hw tuned vs r5_hw base: fall-rate losses={losses or 'none'}, "
        f"flat yaw_rms tuned={tuned_yaw} vs base={baseline_yaw_rms:.2f}")
    with open("trained/phase_r6_hw_gate_decision.json", "w") as f:
        json.dump(dict(losses=losses, yaw_improved=yaw_improved,
                       tuned_yaw_rms=tuned_yaw, base_yaw_rms=baseline_yaw_rms), f, indent=2)
    log(f"=== r6_hw yaw-tuning done -- losses={losses or 'none'}, "
        f"yaw_improved={yaw_improved} -- see {OUT_REPORT} ===")


if __name__ == "__main__":
    main()
