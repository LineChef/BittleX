"""Consolidate the IMU_HOLD_STEPS=4 win (2026-09-29). phase_r7_holdsteps_probe.py's
3M diagnostic confirmed yaw RMS and heading drift both improve substantially at
HOLD_STEPS=4 vs r5_hw_candidate's HOLD_STEPS=1 (drift 9.67 -> 4.25, more than
halved). Ledges did NOT improve (separate problem, handled independently later --
per explicit user instruction, NOT combined into this run).

Continues r7_holdsteps4_probe for up to 10M more of its own steps (3M already
done + up to 10M more = 13M cumulative from r5_hw_candidate, matching the same
budget shape as the V2 -> V2.1 yaw-tuning round), gated at 3M/5M/10M of this
run's own steps -- same pattern as phase_r6_hw_yaw.py's run_gated_10m_with_midcheck.
On a clean finish, runs the full benchmark report and compares against
Release_CandidateV2.1, same as phase_r5_hw_sequential.py did.

    python phase_r8_holdsteps4_consolidate.py
"""
import glob
import json
import os
import subprocess
import time

import run_pipeline as RP

LOG = "trained/phase_r8_holdsteps4_consolidate.log"
TAG = "r8_holdsteps4_10m"
FROM_CKPT = "trained/r7_holdsteps4_probe_ppo"
EXTRA_ENV = {"G2E_IMU_HOLD_STEPS": "4"}
ALL_CELLS = ["T4.1", "T4.2", "T10.1", "T7.2", "T5.1", "T5.2", "T5.3"]
MID_CHECK_STEP = 5000000
INTERIM_NAME = "r8_holdsteps4_candidate"
V21_REPORT = "trained/phase_yaw_r3_report.json"
OUT_REPORT = "trained/phase_r8_holdsteps4_report.json"


def log(msg):
    line = f"[r8 {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _score_checkpoint4(tag, step, all_cells):
    """Same as run_pipeline._score_checkpoint but with IMU_HOLD_STEPS=4."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 4, True, "i"
    E.CMD_SEND_EVERY_N = 3
    E.EPISODE_LENGTH = 250
    s, _ = _bench(env, m, 20, 1000)
    fell, speed = float(s["fell_fraction"]), float(s["forward_speed_mps_mean"])

    skill_results = {}
    cells_all = {c[0]: c for c in B.LADDER}
    for cid in all_cells:
        knobs = {k: v for k, v in cells_all[cid][4].items() if not k.startswith("_")}
        B._apply(knobs)
        E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 4, True, "i"
        E.CMD_SEND_EVERY_N = 3
        E.EPISODE_LENGTH = 250
        s, _ = _bench(env, m, 20, 1000)
        skill_results[cid] = round(s["fell_fraction"], 3)
    env.close()
    return fell, speed, skill_results


def _score_yaw4(tag, step):
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 4, True, "i"
    E.CMD_SEND_EVERY_N = 3
    E.EPISODE_LENGTH = 250
    s, _ = _bench(env, m, 20, 1000)
    env.close()
    return float(s["yaw_rate_rms_deg_mean"]), float(s["heading_drift_deg_mean"])


def run_gated_10m_with_midcheck():
    log(f"launching {TAG} -- 10M-step schedule (own steps; 13M cumulative from "
        f"r5_hw_candidate), gated at 3M/5M/10M, continuing from {FROM_CKPT}")
    RP.launch(TAG, EXTRA_ENV, steps="10e6", from_ckpt=FROM_CKPT)

    ok, reason = RP.wait_for_ckpt(TAG, RP.GATE_STEP)
    if not ok:
        log(f"HALT: {reason}")
        raise SystemExit(1)
    early_fell, early_speed, early_skills = _score_checkpoint4(TAG, RP.GATE_STEP, ALL_CELLS)
    early_worst_cell, early_worst_fell = max(early_skills.items(), key=lambda kv: kv[1]) if early_skills else (None, 0.0)
    log(f"3M sanity check: T1.1 fell {early_fell:.3f}, speed {early_speed:.4f}; "
        f"per-cell skill fell: {early_skills}")
    if early_fell > RP.FLAT_REGRESSION_FELL_MAX and early_worst_fell > 0.9:
        log(f"EARLY STOP: flat-ground regressed AND no learning signal -- halting at 3M.")
        RP.stop(TAG)
        raise SystemExit(1)

    ok, reason = RP.wait_for_ckpt(TAG, MID_CHECK_STEP)
    if ok:
        mid_fell, mid_speed, mid_skills = _score_checkpoint4(TAG, MID_CHECK_STEP, ALL_CELLS)
        mid_yaw, mid_drift = _score_yaw4(TAG, MID_CHECK_STEP)
        log(f"5M informational check (not a gate): T1.1 fell {mid_fell:.3f}, speed {mid_speed:.4f}; "
            f"yaw_rms {mid_yaw:.2f} drift {mid_drift:.2f}; per-cell: {mid_skills}")
    else:
        log(f"5M informational check skipped ({reason})")

    ok, reason = RP.wait_for_finish(TAG)
    if not ok:
        log(f"HALT: {reason}")
        raise SystemExit(1)
    ckpts = sorted(glob.glob(f"trained/checkpoints/{TAG}_*_steps.zip"))
    final_step = max(int(p.rsplit("_", 2)[-2]) for p in ckpts) if ckpts else 10000000
    fell, speed, skill_results = _score_checkpoint4(TAG, final_step, ALL_CELLS)
    yaw_rms, drift = _score_yaw4(TAG, final_step)
    log(f"10M final report ({final_step} steps): T1.1 fell {fell:.3f}, speed {speed:.4f}; "
        f"yaw_rms {yaw_rms:.2f} drift {drift:.2f}; per-cell: {skill_results}")

    flat_ok = fell <= RP.FLAT_REGRESSION_FELL_MAX
    worst_cell, worst_fell = max(skill_results.items(), key=lambda kv: kv[1]) if skill_results else (None, 0.0)
    skills_ok = worst_fell <= RP.DRESS_SKILL_FAIL_MAX
    if not (flat_ok and skills_ok):
        why = []
        if not flat_ok:
            why.append(f"T1.1 fell {fell:.3f} > {RP.FLAT_REGRESSION_FELL_MAX}")
        if not skills_ok:
            why.append(f"{worst_cell} fell {worst_fell:.3f} > {RP.DRESS_SKILL_FAIL_MAX}")
        log(f"DECISION: regressed -- {', '.join(why)}. {TAG}'s checkpoint kept for review.")
        return False
    os.rename(f"trained/{TAG}_ppo.zip", f"trained/{INTERIM_NAME}_ppo.zip")
    log(f"DECISION: clean -- renamed trained/{TAG}_ppo.zip -> trained/{INTERIM_NAME}_ppo.zip")
    return True


def _compare_vs_v21_and_scripted(new_report_path):
    new = {s["slug"]: s for s in json.load(open(new_report_path))["sections"]}
    v21 = {}
    if os.path.exists(V21_REPORT):
        v21 = {s["slug"]: s for s in json.load(open(V21_REPORT))["sections"]}
    NOISE = 0.05
    verdicts = {}
    for slug, sec in new.items():
        if slug in v21:
            d = sec["learned_fell"] - v21[slug]["learned_fell"]
            verdicts[slug] = "win" if d < -NOISE else ("loss" if d > NOISE else "tie")
    log(f"r8 vs Release_CandidateV2.1 per category: {verdicts}")
    return verdicts, v21.get("flat_ground", {}).get("learned_yaw_rate_rms_deg")


def main():
    log("=== r8 holdsteps4 consolidation started ===")
    passed = run_gated_10m_with_midcheck()
    if not passed:
        log("Did not clear its gate -- stopping here, no benchmark report.")
        return

    log(f"Running the full benchmark report against {INTERIM_NAME}")
    r = subprocess.run(
        f"{RP.PY} phase_c_report.py --tag {INTERIM_NAME} --out {OUT_REPORT}", shell=True)
    if r.returncode != 0:
        log(f"Benchmark report FAILED (exit {r.returncode}) -- {INTERIM_NAME} still on disk")
        raise SystemExit(1)

    ckpts = sorted(glob.glob(f"trained/checkpoints/{TAG}_*_steps.zip"))
    final_step = max(int(p.rsplit("_", 2)[-2]) for p in ckpts) if ckpts else 10000000
    yaw_rms, drift = _score_yaw4(TAG, final_step)
    verdicts, v21_yaw_rms = _compare_vs_v21_and_scripted(OUT_REPORT)
    losses = [s for s, v in verdicts.items() if v == "loss"]

    with open("trained/phase_r8_holdsteps4_gate_decision.json", "w") as f:
        json.dump(dict(verdicts=verdicts, losses=losses, yaw_rms=yaw_rms, heading_drift=drift,
                       v21_yaw_rms=v21_yaw_rms, final_step=final_step), f, indent=2)
    log(f"=== r8 consolidation done -- losses vs V2.1: {losses or 'none'}, "
        f"yaw_rms={yaw_rms:.2f} (V2.1 {v21_yaw_rms:.2f}) -- see {OUT_REPORT} ===")


if __name__ == "__main__":
    main()
