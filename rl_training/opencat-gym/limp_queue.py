"""Limp-fix candidate queue (2026-09-23): one training at a time, early stop, averaged gate.

Every candidate is the best run's config (hw2: real control path + targeted slopes +
leg balance + ramp cap) plus a limp fix. For each, in order:

  1. launch (unless it's already training), as a 20M-schedule run
  2. at 2.0M: limp-only check on the 1.6/1.8/2.0M checkpoints vs hw2 at the same
     steps; stop it there if it's better on NEITHER least-used paw (< hw2 + 0.05) NOR
     stance hover (> 70 % of hw2's)
  3. otherwise stop at 3.0M and run the full 5-checkpoint gate (multi_ckpt_eval.py)
  4. PASS = least-used paw >= 0.35 and hw2's gains kept (uphill 16 >= 0.05 m/s,
     side-hill 12 >= 0.024, bare gauntlet falls <= 0.5, flat >= 0.085); the queue
     stops at the first pass -- a 20M run is only launched after review with the user

    python limp_queue.py                  # run the whole queue
    python limp_queue.py --adopt hw5_20m  # hw5_20m is already training: start with it
"""
import argparse
import json
import os
import subprocess
import time

import numpy as np

PY = "../../.venv/bin/python"
BASE = dict(G2E_IMU_HOLD_STEPS="16", G2E_IMU_RATE_ZERO="1", G2E_CMD_PATH="i", G2E_CMD_PATH_EXTRA_MS_MAX="4",
            G2E_BODY_MASS_SCALE="1.12", G2E_IMU_BIAS_DEG="2", G2E_JOINT_OFFSET_DEG="2",
            G2E_SLOPE_TARGET_PROB="0.3", G2E_FAC_LEG_BALANCE="1.5")
CANDIDATES = [
    ("hw5_20m", "stance hover 3", dict(G2E_FAC_STANCE_HOVER="3")),
    ("hw6_20m", "stance hover 6", dict(G2E_FAC_STANCE_HOVER="6")),
    ("hw7_20m", "stance hover 3 + average-correction penalty 30", dict(G2E_FAC_STANCE_HOVER="3", G2E_FAC_RESID_BIAS="30")),
    ("hw8_20m", "stance hover 3 + footfall imitation 3", dict(G2E_FAC_STANCE_HOVER="3", G2E_FAC_CONTACT_IMITATION="3")),
]
EARLY = "1600000,1800000,2000000"
PASS = dict(least_paw=(">=", 0.35), **{"up 16": (">=", 0.05), "side 12": (">=", 0.024)},
            **{"T5.1b": ("<=", 0.5), "T1.1": (">=", 0.085)})


def log(msg):
    print(f"[queue {time.strftime('%I:%M %p')}] {msg}", flush=True)


def training(tag):
    return subprocess.run(["pgrep", "-f", f"train.py --tag {tag}"], capture_output=True).returncode == 0


def any_training():
    return subprocess.run(["pgrep", "-f", "train.py --tag"], capture_output=True).returncode == 0


def ckpt(tag, step):
    return f"trained/checkpoints/{tag}_{step}_steps.zip"


def stop(tag):
    subprocess.run(["pkill", "-f", f"train.py --tag {tag}"])
    while training(tag):
        time.sleep(2)


def wait_for(tag, step):
    while not os.path.exists(ckpt(tag, step)):
        if not training(tag):
            return False
        time.sleep(20)
    time.sleep(15)          # let the checkpoint finish writing
    return True


def launch(tag, extra):
    if any_training():
        raise SystemExit("another training is running -- not starting a second one")
    env = dict(os.environ, **BASE, **extra)
    r = subprocess.run(f"echo y | ./start_run.sh {tag} --steps 20e6", shell=True, env=env,
                       capture_output=True, text=True)
    log(f"launched {tag}: {r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr.strip()[-200:]}")


def evaluate(tag, steps, limp_only, out):
    cmd = [PY, "multi_ckpt_eval.py", "--run", tag, "--steps", steps, "--out", out] + (["--limp-only"] if limp_only else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"eval FAILED for {tag}: {r.stderr[-400:]}")
        return None
    return json.load(open(out))


def mean(rows, k):
    return float(np.mean([r[k] for r in rows]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt", default=None)
    args = ap.parse_args()
    base_early = json.load(open("trained/mce_limp_hw2_20m_early.json"))
    b_paw, b_hov = mean(base_early, "least_paw"), mean(base_early, "stance_hover_mm")
    log(f"hw2 early baseline: least-used paw {b_paw:.3f}, stance hover {b_hov:.1f} mm")
    start = [c[0] for c in CANDIDATES].index(args.adopt) if args.adopt else 0
    for tag, desc, extra in CANDIDATES[start:]:
        log(f"--- {tag}: {desc}")
        if not training(tag):
            launch(tag, extra)
        if not wait_for(tag, 2000000):
            log(f"{tag} stopped before 2.0M -- skipping")
            continue
        early = evaluate(tag, EARLY, True, f"trained/mce_limp_{tag}_early.json")
        if early is None:
            stop(tag)
            continue
        c_paw, c_hov = mean(early, "least_paw"), mean(early, "stance_hover_mm")
        log(f"{tag} early (1.6-2.0M): least-used paw {c_paw:.3f} (hw2 {b_paw:.3f}), hover {c_hov:.1f} mm (hw2 {b_hov:.1f})")
        if c_paw < b_paw + 0.05 and c_hov > 0.7 * b_hov:
            stop(tag)
            log(f"{tag} EARLY STOP: better on neither limp metric")
            continue
        if not wait_for(tag, 3000000):
            log(f"{tag} stopped before 3.0M -- skipping")
            continue
        stop(tag)
        log(f"{tag} stopped at 3.0M; running the full averaged gate")
        rows = evaluate(tag, "2200000,2400000,2600000,2800000,3000000", False, f"trained/mce_{tag}.json")
        if rows is None:
            continue
        subprocess.run([PY, "multi_ckpt_eval.py", "--summarize", "trained/mce_hw1_20m.json",
                        "trained/mce_hw2_20m.json", f"trained/mce_{tag}.json"])
        verdict = {k: (mean(rows, k), op, lim) for k, (op, lim) in PASS.items()}
        ok = all((v >= lim) if op == ">=" else (v <= lim) for v, op, lim in verdict.values())
        log(f"{tag} gate: " + ", ".join(f"{k} {v:.3f} ({op} {lim})" for k, (v, op, lim) in verdict.items())
            + f" -> {'PASS' if ok else 'fail'}")
        if ok:
            log(f"{tag} PASSES -- queue stopped. Review with the user before any 20M run.")
            return
    log("queue finished, no candidate passed -- nothing training. Review with the user.")


if __name__ == "__main__":
    main()
