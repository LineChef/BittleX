"""The Decathlon -- a graded learned-vs-scripted comparison that ramps from
easy to brutal across every skill G2 has been trained on.

15 cells in 5 tiers; both gaits run every cell on matched per-episode seeds.
Writes a JSON that build_decathlon_report.py turns into an HTML report.

    python benchmark_decathlon.py --learned trained/<tag>_ppo --episodes 28 \
        --json-out /path/decathlon.json --gif-dir /path/gifs
"""
import argparse
import json
import math
import os

import numpy as np
import pybullet as p

import opencat_gym_env
from opencat_gym_env import OpenCatGymEnv
from benchmark_gaits import ScriptedGait, _load_learned, _bench, _render

D = math.radians

# knob keys we reset before every cell so each cell tests only what it declares
_ZERO = ("RANDOM_FRICTION", "RANDOM_MASS", "RANDOM_GYRO", "RANDOM_PUSH", "RANDOM_TERRAIN",
         "IMPULSE_PUSH", "SLOPE_MAX_DEG", "START_POSE_JITTER", "STUCK_FOOT_PROB",
         "SUSTAINED_FORCE", "DEFORM_GROUND", "SLIP_PATCH",
         "TORQUE_CUTBACK", "LEDGE_HEIGHT", "LEDGE_PROB", "LEDGE_DIR", "RUBBLE", "RUBBLE_PROB", "CARPET")

# (id, tier, skill, human label, {env knob overrides})
LADDER = [
    ("T1.1", 1, "flat walk",      "Flat, calm",                 {}),
    ("T1.2", 1, "straight line",  "Flat + gentle nudges",       {"RANDOM_PUSH": 0.12, "RANDOM_PUSH_PROB": 0.02}),

    ("T2.1", 2, "slopes",         "Gentle up  (5 deg)",         {"SLOPE_FIXED_RP": (0.0, D(5))}),
    ("T2.2", 2, "slopes",         "Gentle down  (-5 deg)",      {"SLOPE_FIXED_RP": (0.0, D(-5))}),
    ("T2.3", 2, "slopes",         "Cross-slope  (5 deg roll)",  {"SLOPE_FIXED_RP": (D(5), 0.0)}),
    ("T2.4", 2, "obstacles",      "Small obstacles  (20 mm)",   {"RANDOM_TERRAIN": 0.020}),

    ("T3.1", 3, "slopes",         "Steep up  (12 deg)",         {"SLOPE_FIXED_RP": (0.0, D(12))}),
    ("T3.2", 3, "slopes",         "Steep down  (-12 deg)",      {"SLOPE_FIXED_RP": (0.0, D(-12))}),
    ("T3.3", 3, "obstacles",      "Medium obstacles  (35 mm)",  {"RANDOM_TERRAIN": 0.035}),
    ("T3.4", 3, "slope+obstacle", "Slope 9 deg + obstacles 30 mm",
        {"SLOPE_FIXED_RP": (0.0, D(9)), "RANDOM_TERRAIN": 0.030}),

    ("T4.1", 4, "stumble-catch",  "One hard shove",
        {"IMPULSE_PUSH": 0.65, "IMPULSE_PUSH_PROB": 0.004}),
    ("T4.2", 4, "stumble-catch",  "Repeated shoves",
        {"IMPULSE_PUSH": 0.55, "IMPULSE_PUSH_PROB": 0.012}),
    ("T4.3", 4, "stumble-catch",  "Obstacles + shoves",
        {"RANDOM_TERRAIN": 0.035, "IMPULSE_PUSH": 0.55, "IMPULSE_PUSH_PROB": 0.010, "RANDOM_PUSH": 0.20}),
    ("T4.4", 4, "obstacles",      "Big obstacles  (50 mm)",
        {"RANDOM_TERRAIN": 0.050, "RANDOM_PUSH": 0.30}),

    ("T5.1", 5, "everything",     "The gauntlet: slope + obstacles + repeated shoves",
        {"SLOPE_FIXED_RP": (D(4), D(9)), "RANDOM_TERRAIN": 0.040,
         "IMPULSE_PUSH": 0.60, "IMPULSE_PUSH_PROB": 0.012, "RANDOM_PUSH": 0.25}),

    # T6: the hardened tier. With the payload on, both gaits are essentially
    # unfallable on terrain/shove stress -- even -24 deg descents and a 20 deg
    # brutal gauntlet give 0% falls. So T6 is NOT scored on fall rate; it is
    # scored on COMMANDED PROGRESS + speed retention + heading drift under
    # extreme stress. T6.1 (steep descent: learned walks down, scripted slides
    # back) and T6.5 (weak servos: the one failure mode the payload's inertia
    # cannot mask) are the real discriminators.
    ("T6.1", 6, "slopes",         "Extreme down  (-24 deg)",
        {"SLOPE_FIXED_RP": (0.0, D(-24))}),
    ("T6.2", 6, "obstacles",      "Huge obstacles  (85 mm) + push",
        {"RANDOM_TERRAIN": 0.085, "RANDOM_PUSH": 0.35}),
    ("T6.3", 6, "stumble-catch",  "Brutal shoves  (1.00 @ 0.018)",
        {"IMPULSE_PUSH": 1.00, "IMPULSE_PUSH_PROB": 0.018, "RANDOM_PUSH": 0.25}),
    ("T6.4", 6, "everything",     "Brutal gauntlet: 20 deg slope + 70 mm + brutal shoves",
        {"SLOPE_FIXED_RP": (D(8), D(20)), "RANDOM_TERRAIN": 0.070,
         "IMPULSE_PUSH": 1.00, "IMPULSE_PUSH_PROB": 0.018, "RANDOM_PUSH": 0.45}),
    ("T6.5", 6, "weak servos",    "Overheated servos (60% cutback) + 12 deg descent",
        {"TORQUE_CUTBACK": 0.60, "SLOPE_FIXED_RP": (0.0, D(-12))}),

    # T7: ledge / step. A realistic disturbance (door sills, rug edges, low curbs)
    # the payload's inertia does NOT paper over -- a bad foot plant on an edge
    # still starts a topple. Score on fall rate AND recovery events / time-to-settle.
    ("T7.1", 7, "ledge",          "Threshold up  (15 mm)",
        {"LEDGE_HEIGHT": 0.015, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}),
    ("T7.2", 7, "ledge",          "Threshold down  (15 mm)",
        {"LEDGE_HEIGHT": 0.015, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}),
    ("T7.3", 7, "ledge",          "Step up  (30 mm sill)",
        {"LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}),
    ("T7.4", 7, "ledge",          "Step down  (30 mm drop)",
        {"LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}),
    ("T7.5", 7, "ledge",          "Big ledge  (45 mm, random up/down)",
        {"LEDGE_HEIGHT": 0.045, "LEDGE_PROB": 1.0, "LEDGE_DIR": 0}),
]

GIF_CELLS = {"T5.1": "gauntlet"}   # replays: only the everything-at-once course
_METRICS = ["fell_fraction", "forward_speed_mps_mean", "forward_distance_m_mean",
            "diagonal_trot_corr_mean", "yaw_rate_rms_deg_mean", "lat_offset_max_m_mean",
            "recovery_events", "recovery_time_steps_mean", "big_stumble_recovery_rate"]


# sim2real DR that is NOT part of any cell's declared difficulty. "full" leaves
# the env module defaults (payload 90%, rough patch 35%, torque cutback 40%);
# "clean" removes all three so a cell tests exactly its label; "payload" removes
# rough + cutback but forces the Pi/camera payload on every episode so its cost
# can be read directly against the "clean" run.
_EXTRA_DR = "full"


def _apply(cell_knobs):
    for k in _ZERO:
        if hasattr(opencat_gym_env, k):
            setattr(opencat_gym_env, k, 0.0)
    opencat_gym_env.SLOPE_FIXED_RP = None
    opencat_gym_env.SLIP_PATCH = 0.0
    opencat_gym_env.SUSTAINED_FORCE = 0.0
    opencat_gym_env.RANDOM_PUSH_PROB = 0.03
    opencat_gym_env.IMPULSE_PUSH_PROB = 0.0
    opencat_gym_env.DR_EVAL_FULL = True
    if _EXTRA_DR == "clean":
        opencat_gym_env.PAYLOAD_PROB = 0.0
        opencat_gym_env.ROUGH_TERRAIN = 0.0
        opencat_gym_env.TORQUE_CUTBACK = 0.0
    elif _EXTRA_DR == "payload":
        opencat_gym_env.PAYLOAD_PROB = 1.0
        opencat_gym_env.ROUGH_TERRAIN = 0.0
        opencat_gym_env.TORQUE_CUTBACK = 0.0
    for k, v in cell_knobs.items():
        setattr(opencat_gym_env, k, v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned", required=True)
    ap.add_argument("--scripted-balance", type=float, default=0.0)
    ap.add_argument("--episodes", type=int, default=28)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--gif-dir", default=None)
    ap.add_argument("--extra-dr", choices=("full", "clean", "payload"), default="full",
                    help="non-cell DR: full=env defaults, clean=no payload/rough/cutback, "
                         "payload=payload forced on, rough+cutback off")
    args = ap.parse_args()

    global _EXTRA_DR
    _EXTRA_DR = args.extra_dr

    opencat_gym_env.ADAPTIVE_PUSH = False        # training-time curriculum state -- off for eval
    env = OpenCatGymEnv()
    if hasattr(env, 'set_command'):        # gait-refinement: measure on a fixed cruise-forward command
        env.set_command(fwd=0.10, yaw=0.0)
    learned = _load_learned(args.learned)
    scripted = ScriptedGait(env, balance_k=args.scripted_balance)

    out = {"learned_path": args.learned, "episodes": args.episodes,
           "extra_dr": args.extra_dr, "scripted_balance": args.scripted_balance, "cells": []}
    for cid, tier, skill, label, knobs in LADDER:
        _apply(knobs)
        print(f"\n=== {cid}  T{tier}  {label} ===", flush=True)
        rl, rl_eps = _bench(env, learned, args.episodes, args.seed, reflex=False)
        sc, sc_eps = _bench(env, scripted, args.episodes, args.seed, reflex=False)
        sc_fall = [i for i, d in enumerate(sc_eps) if d["fell"]]
        cond_surv = (sum(1 for i in sc_fall if not rl_eps[i]["fell"]) / len(sc_fall)
                     if sc_fall else None)
        print(f"  learned fell {rl['fell_fraction']:.0%}  |  scripted fell {sc['fell_fraction']:.0%}"
              f"  |  learned {rl['forward_speed_mps_mean']:.3f} m/s vs {sc['forward_speed_mps_mean']:.3f}"
              + (f"  |  cond.surv {cond_surv:.0%} of {len(sc_fall)}" if cond_surv is not None else ""),
              flush=True)
        rec = {"id": cid, "tier": tier, "skill": skill, "label": label,
               "knobs": {k: (list(v) if isinstance(v, tuple) else v) for k, v in knobs.items()},
               "scripted_fall_episodes": len(sc_fall),
               "conditional_survival": cond_surv,
               "learned": {m: rl.get(m) for m in _METRICS},
               "scripted": {m: sc.get(m) for m in _METRICS}}
        out["cells"].append(rec)

        if args.gif_dir and cid in GIF_CELLS:
            os.makedirs(args.gif_dir, exist_ok=True)
            tag = GIF_CELLS[cid]
            _render(env, learned, os.path.join(args.gif_dir, f"{tag}_learned.gif"), seed=args.seed)
            _render(env, scripted, os.path.join(args.gif_dir, f"{tag}_scripted.gif"), seed=args.seed)

    env.close()
    with open(args.json_out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
