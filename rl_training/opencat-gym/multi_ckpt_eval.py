"""Multi-checkpoint gate: average several checkpoints instead of trusting one.

A single 3M snapshot swings ~2x on some cells within 400K steps (hw1_20m @2.6M /
3.0M / 3.4M: 20 mm sill 0.048 / 0.100 / 0.040 m/s), so comparing one run's 3M
checkpoint against another's can manufacture regressions (2026-09-23). This scores
each given checkpoint on a fixed probe set and writes one JSON row per checkpoint;
--summarize prints each run's mean and spread across its checkpoints.

Probe set (payload on, BODY_MASS_SCALE 1.12, +/-2 deg calibration error, learned
gait through the real control path; scripted isn't needed -- runs are compared
with each other):
  - flat: per-paw ground contact, footfall mismatch vs the scripted schedule, speed
  - slopes (pure, no rough episodes): uphill 8/16, side-hill 8/12 and -8
  - benchmark cells: T1.1 T2.4 T3.2 T7.2 T8.2 T9.3 (speed), T5.1b T6.3b (falls)

    python multi_ckpt_eval.py --run hw1_20m --steps 2200000,2400000,2600000,2800000,3000000
    python multi_ckpt_eval.py --summarize trained/mce_hw1_20m.json trained/mce_hw4_20m.json
"""
import argparse
import json
import math

import numpy as np

import opencat_gym_env as E
E.GUI_MODE = False
import benchmark_decathlon as B
from benchmark_gaits import _load_learned, _bench
from opencat_gym_env import OpenCatGymEnv

D = math.radians
CELLS_SPEED = ("T1.1", "T2.4", "T3.2", "T7.2", "T8.2", "T9.3")
CELLS_FALLS = ("T5.1b", "T6.3b")
SLOPES = (("up 8", 0.0, -D(8)), ("up 16", 0.0, -D(16)),
          ("side 8", D(8), 0.0), ("side 12", D(12), 0.0), ("side -8", -D(8), 0.0))


def realistic(hw=True):
    E.BODY_MASS_SCALE, E.IMU_BIAS_DEG, E.JOINT_OFFSET_DEG = 1.12, 2.0, 2.0
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = (16, True, "i") if hw else (0, False, "")


def flat_contacts(env, m, episodes=4, steps=320):
    ref = np.load("reference_gait/wkf_contact_ref.npy")
    B._apply({})
    E.ROUGH_TERRAIN, E.TORQUE_CUTBACK = 0.0, 0.0
    realistic()
    E.EPISODE_LENGTH = steps + 5
    hits, mis, hov, n = np.zeros(4), [], [], 0
    import pybullet as p
    for s in range(episodes):
        np.random.seed(3000 + s)
        obs, _ = env.reset()
        env.set_command(fwd=0.10, yaw=0.0)
        for t in range(steps):
            obs, _, _, _, info = env.step(m.predict(obs, deterministic=True)[0])
            if t < 80:
                continue
            c = np.asarray(info["paw_contact"], float)
            b = int((info["phase_step0"] % 100) / 100 * len(ref)) % len(ref)
            hits += c
            mis.append(np.abs(c - ref[b]).mean())
            due = [i for i in range(4) if ref[b][i] > 0.9]
            if due:
                pos = [p.getLinkState(env.robot_id, (3, 6, 9, 12)[i])[0] for i in due]
                hs = p.rayTestBatch(pos, [(x, y, z - 0.06) for x, y, z in pos])
                hov += [max(0.0, h[2] * 60.0 - 6.5) for h in hs if h[0] >= 0 and h[0] != env.robot_id]
            n += 1
    return dict(paw=(hits / n).round(3).tolist(), least_paw=float((hits / n).min()),
                footfall_mismatch=float(np.mean(mis)), stance_hover_mm=float(np.mean(hov)) if hov else 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("--steps", default="2200000,2400000,2600000,2800000,3000000")
    ap.add_argument("--episodes", type=int, default=16)
    ap.add_argument("--summarize", nargs="*")
    ap.add_argument("--limp-only", action="store_true",
                    help="flat-ground limp metrics only (least-used paw, footfall mismatch, stance hover) -- "
                         "the fast early check")
    ap.add_argument("--out", default=None, help="default trained/mce_<run>.json (limp-only: mce_limp_<run>_<steps>.json)")
    args = ap.parse_args()
    if args.summarize:
        return summarize(args.summarize)

    cells = {c[0]: c for c in B.LADDER}
    E.ADAPTIVE_PUSH = False
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    rows = []
    for st in args.steps.split(","):
        ck = f"trained/checkpoints/{args.run}_{st}_steps"
        m = _load_learned(ck)
        row = dict(run=args.run, step=int(st))
        row.update(flat_contacts(env, m))
        if args.limp_only:
            rows.append(row)
            print(json.dumps(row), flush=True)
            continue
        for name, roll, pitch in SLOPES:
            B._apply({})
            E.ROUGH_TERRAIN, E.TORQUE_CUTBACK = 0.0, 0.0
            realistic()
            E.SLOPE_FIXED_RP = (roll, pitch)
            E.EPISODE_LENGTH = 400
            s, _ = _bench(env, m, args.episodes // 2, 3000)
            row[name] = round(s["forward_speed_mps_mean"], 4)
        E.SLOPE_FIXED_RP = None
        for cid in CELLS_SPEED + CELLS_FALLS:
            B._apply({k: v for k, v in cells[cid][4].items() if not k.startswith("_")})
            E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
            E.EPISODE_LENGTH = 250
            s, _ = _bench(env, m, args.episodes if cid in CELLS_SPEED else 2 * args.episodes, 1000)
            row[cid] = round(s["fell_fraction"] if cid in CELLS_FALLS else s["forward_speed_mps_mean"], 4)
        E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 0, False, ""
        rows.append(row)
        print(json.dumps(row), flush=True)
    out = args.out or (f"trained/mce_limp_{args.run}.json" if args.limp_only else f"trained/mce_{args.run}.json")
    with open(out, "w") as f:
        json.dump(rows, f, indent=1)


def summarize(paths):
    keys = (["least_paw", "footfall_mismatch", "stance_hover_mm"] + [n for n, _, _ in SLOPES]
            + list(CELLS_SPEED) + list(CELLS_FALLS))
    data = {p: json.load(open(p)) for p in paths}
    print(f"{'metric':>18} " + " ".join(f"{d[0]['run']:>17}" for d in data.values()))
    for k in keys:
        cols = []
        for rows in data.values():
            v = np.array([r.get(k, np.nan) for r in rows], float)
            cols.append(f"{np.nanmean(v):7.3f} ±{np.nanstd(v):5.3f}  " if np.isfinite(v).any() else f"{'-':>15}  ")
        print(f"{k:>18} " + " ".join(f"{c:>17}" for c in cols))


if __name__ == "__main__":
    main()
