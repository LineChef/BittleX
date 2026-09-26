"""Yaw-wobble / heading-drift tuning round (2026-09-26), continuing from
Release_CandidateV2. Three light (3M) candidates test which reward-weight
lever actually reduces steady-state yaw wobble without regressing anything
V2 already does well, then the winner gets a 10M continuation (run_gated_10m,
NOT the 20M-scheduled run_gated_20m) -- this is a narrow fine-tune on an
ALREADY-consolidated gait, not a from-scratch or mechanic-combining run, and
20M is very likely overkill for it: this project's own precedent
(docs/rl/refinement-regimen.md's Phase 4 stance-recovery continuation was
3-5M) and this campaign's own evidence (the sequential chain's final 20M
continuation barely changed from its 3M checkpoint onward) both say so.
First drafted this scheduled for 20M with a plateau-check safety net meant to
cut it short at 10M -- caught and corrected (2026-09-26): don't schedule for
more than you expect to need and lean on a safety net, just schedule for what
the evidence says you need.

T5.3 (40mm ledge) is deliberately excluded from every check here. Traced its
large heading-drift numbers directly (replay analysis, 2026-09-26): every
falling episode shows the robot losing ALL FOUR feet off the ledge and
tumbling freely (roll/pitch/yaw all climbing together once airborne) -- a
ledge-height capability limit, not a yaw-control issue. Reward tuning aimed
at steady-state wobble has no reason to touch it, so it's not part of this
round's success criteria.

    python phase_yaw_tuning.py
"""
import argparse
import glob
import json
import os
import subprocess
import time

import run_pipeline as RP

LOG = "trained/phase_yaw_tuning.log"
STEPS = "3e6"
BASE_CKPT = "trained/Release_CandidateV2_ppo"
ALL_CELLS = ["T4.1", "T4.2", "T10.1", "T7.2", "T5.1", "T5.2"]   # T5.3 excluded, see docstring
SKILL_COLLAPSE_MAX = 0.50   # any cell regressing past this vs V2's own clean numbers disqualifies

# Release_CandidateV2's own measured flat-ground numbers (trained/phase_r_sequential_report.json),
# the baseline every candidate here is measured against.
BASELINE_YAW_RMS = 5.240293962083539
SCRIPTED_YAW_RMS = 3.358133344033354

# (tag, desc, reward-weight overrides)
CANDIDATES = [
    ("r4_yaw_r1", "FAC_YAW_TRACK 9.0 -> 12.0 alone",
        {"FAC_YAW_TRACK": "12.0"}),
    ("r4_yaw_r2", "FAC_YAW_TRACK 9.0 -> 11.0 + FAC_RESID_SMOOTH 8.2 -> 10.0 (paired)",
        {"FAC_YAW_TRACK": "11.0", "FAC_RESID_SMOOTH": "10.0"}),
    ("r4_yaw_r3", "FAC_RESID_SMOOTH 8.2 -> 10.5 alone",
        {"FAC_RESID_SMOOTH": "10.5"}),
]

FINAL_10M_TAG = "r4_yaw_10m"
INTERIM_NAME = "r4_yaw_candidate"
RELEASE_NAME = "Release_CandidateV3"


def log(msg):
    line = f"[yaw {time.strftime('%I:%M %p')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _score_yaw(tag, step):
    """Bench T1.1 only, return yaw_rate_rms_deg_mean -- run_pipeline._score_checkpoint
    doesn't expose yaw metrics, so this is a separate, narrower helper."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
    E.CMD_SEND_EVERY_N = 3
    E.EPISODE_LENGTH = 250
    s, _ = _bench(env, m, 20, 1000)
    env.close()
    return float(s["yaw_rate_rms_deg_mean"])


def run_candidate(tag, desc, extra):
    env = {f"G2E_{k}": v for k, v in extra.items()}
    log(f"--- {tag}: launching, continuing from {BASE_CKPT} ({desc})")
    RP.launch(tag, env, steps=STEPS, from_ckpt=BASE_CKPT)
    ok, reason = RP.wait_for_finish(tag)
    if not ok:
        log(f"{tag} HALT: {reason}")
        return None
    ckpts = sorted(glob.glob(f"trained/checkpoints/{tag}_*_steps.zip"))
    final_step = max(int(p.rsplit("_", 2)[-2]) for p in ckpts) if ckpts else int(float(STEPS))
    flat_fell, flat_speed, skills = RP._score_checkpoint(tag, final_step, ALL_CELLS)
    yaw_rms = _score_yaw(tag, final_step)
    worst_cell, worst_fell = max(skills.items(), key=lambda kv: kv[1]) if skills else (None, 0.0)
    regressed = flat_fell > RP.FLAT_REGRESSION_FELL_MAX or worst_fell > SKILL_COLLAPSE_MAX
    log(f"{tag} scored @ {final_step}: T1.1 fell {flat_fell:.3f} speed {flat_speed:.4f} "
        f"yaw_rms {yaw_rms:.2f} (baseline {BASELINE_YAW_RMS:.2f}, scripted {SCRIPTED_YAW_RMS:.2f}); "
        f"worst cell {worst_cell} fell {worst_fell:.3f}{' -- REGRESSED, disqualified' if regressed else ''}")
    return dict(tag=tag, desc=desc, final_step=final_step, flat_fell=flat_fell, flat_speed=flat_speed,
                skills=skills, yaw_rms=yaw_rms, regressed=regressed)


def main():
    log("=== yaw-tuning light round started ===")
    results = []
    for tag, desc, extra in CANDIDATES:
        r = run_candidate(tag, desc, extra)
        if r:
            results.append(r)
        with open("trained/phase_yaw_tuning_summary.json", "w") as f:
            json.dump(results, f, indent=2)

    valid = [r for r in results if not r["regressed"]]
    if not valid:
        log("=== all candidates regressed or failed to launch -- no winner, needs manual review ===")
        return

    winner = min(valid, key=lambda r: r["yaw_rms"])
    log(f"=== light-round winner: {winner['tag']} ({winner['desc']}) -- "
        f"yaw_rms {winner['yaw_rms']:.2f} (V2 baseline {BASELINE_YAW_RMS:.2f}, "
        f"scripted {SCRIPTED_YAW_RMS:.2f}) ===")

    winner_extra = dict(next(e for t, d, e in CANDIDATES if t == winner["tag"]))
    winner_env = {f"G2E_{k}": v for k, v in winner_extra.items()}
    from_ckpt = f"trained/checkpoints/{winner['tag']}_{winner['final_step']}_steps"
    passed = RP.run_gated_10m(FINAL_10M_TAG, winner_env, ALL_CELLS, INTERIM_NAME,
                              from_ckpt=from_ckpt, label="Yaw-tuning 10M")
    if not passed:
        log("Yaw-tuning 10M regressed -- stopping here.")
        return

    r = subprocess.run(f"{RP.PY} phase_c_report.py --tag {INTERIM_NAME} "
                       f"--out trained/phase_yaw_tuning_report.json", shell=True)
    if r.returncode != 0:
        log(f"Benchmark report FAILED (exit {r.returncode}) -- {INTERIM_NAME} is still on disk "
            "and complete, the report can be re-run manually")
        return

    v2 = {s["slug"]: s for s in json.load(open("trained/phase_r_sequential_report.json"))["sections"]}
    v3 = {s["slug"]: s for s in json.load(open("trained/phase_yaw_tuning_report.json"))["sections"]}
    NOISE = 0.05
    losses = []
    for slug in v2:
        if slug not in v3:
            continue
        d = v3[slug]["learned_fell"] - v2[slug]["learned_fell"]
        if d > NOISE:
            losses.append(slug)
    yaw_improved = v3.get("flat_ground", {}).get("learned_yaw_rate_rms_deg", 99) < BASELINE_YAW_RMS - 0.15
    log(f"V3 vs V2: fall-rate losses={losses or 'none'}, "
        f"flat yaw_rms V3={v3.get('flat_ground', {}).get('learned_yaw_rate_rms_deg', '?')} "
        f"vs V2={BASELINE_YAW_RMS:.2f}")
    if losses or not yaw_improved:
        log(f"NOT promoting -- {'regresses ' + str(losses) if losses else ''}"
            f"{' and ' if losses and not yaw_improved else ''}"
            f"{'no real yaw improvement over V2' if not yaw_improved else ''}. "
            f"Staying under the interim name for review.")
        return
    src, dst = f"trained/{INTERIM_NAME}_ppo.zip", f"trained/{RELEASE_NAME}_ppo.zip"
    os.rename(src, dst)
    log(f"PROMOTED: {INTERIM_NAME} improves yaw wobble over Release_CandidateV2 with no fall-rate "
        f"regression -- renamed {src} -> {dst}. Still not auto-promoted to DEFAULT_POLICY.")
    log("=== all done ===")


if __name__ == "__main__":
    main()
