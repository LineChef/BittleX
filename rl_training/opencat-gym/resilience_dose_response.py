"""Resiliency campaign -- dose-response sweep for the already-built-but-
under-characterized stressor mechanisms, plus the genuinely-new ones:
RUBBLE (past the existing gauntlet's max severity), LEDGE_DIR=-1
(step-down only -- retired/inert by default, real history: Phase 4a made
ledge handling worse when trained on carelessly, still fine for held-out
eval), STUCK_FOOT_PROB, static JOINT_OFFSET_DEG, and a combined "gnarly
course" stacking several at once (compounding effects, not just individual
axes -- the prior R-series campaign tested axes individually).

Deliberately payload OFF throughout (--extra-dr clean, matching
recovery_probe.py and this session's own T5.1b/T6.*b finding): payload mass
masks real stance weakness, so an honest fall-rate read needs it off, not
the decathlon's default payload-on convention.

Reuses benchmark_decathlon.py's cell/knob-override infrastructure directly
rather than reinventing it.

    python resilience_dose_response.py --learned trained/run20m_resid30_ppo --episodes 20 --json-out out.json
"""
import argparse
import json
import math

import opencat_gym_env
from opencat_gym_env import OpenCatGymEnv
from benchmark_gaits import ScriptedGait, _load_learned, _bench
from benchmark_decathlon import _apply, _ZERO, _METRICS

D = math.radians

_LOCAL_ZERO = ("JOINT_OFFSET_DEG", "IMU_BIAS_DEG")

CELLS = [
    ("D-rubble-1", "rubble",  "Rubble: denser than any existing gauntlet cell",
        {"RUBBLE": 0.025, "RUBBLE_N": 700, "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.025}),
    ("D-rubble-2", "rubble",  "Rubble: past that again",
        {"RUBBLE": 0.030, "RUBBLE_N": 900, "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.030}),

    ("D-ledge-1", "ledge",    "Step-down only, 20mm",
        {"LEDGE_HEIGHT": 0.020, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}),
    ("D-ledge-2", "ledge",    "Step-down only, 24mm",
        {"LEDGE_HEIGHT": 0.024, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}),
    ("D-ledge-3", "ledge",    "Step-down only, 27mm",
        {"LEDGE_HEIGHT": 0.027, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}),
    ("D-ledge-4", "ledge",    "Step-down only, 30mm -- user's visual read says 'almost recovers, maybe the max'",
        {"LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}),
    ("D-ledge-5", "ledge",    "Step-down only, 33mm",
        {"LEDGE_HEIGHT": 0.033, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}),

    ("D-stuck-1", "stuck-foot", "Stuck foot, low prob",
        {"STUCK_FOOT_PROB": 0.02}),
    ("D-stuck-2", "stuck-foot", "Stuck foot, higher prob",
        {"STUCK_FOOT_PROB": 0.05}),

    ("D-jointoff-1", "joint-offset", "Static per-episode joint miscalibration, 3deg",
        {"JOINT_OFFSET_DEG": 3.0}),
    ("D-jointoff-2", "joint-offset", "Static per-episode joint miscalibration, 6deg",
        {"JOINT_OFFSET_DEG": 6.0}),

    ("D-gnarly", "everything", "Combined: dense rubble + step-down ledge + stuck foot + joint offset",
        {"RUBBLE": 0.020, "RUBBLE_N": 560, "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.020,
         "LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 0.5, "LEDGE_DIR": -1,
         "STUCK_FOOT_PROB": 0.03, "JOINT_OFFSET_DEG": 4.0}),
]


def _apply_cell(knobs):
    _apply(knobs)          # shared decathlon reset + apply
    for k in _LOCAL_ZERO:  # this script's own extra knobs, zeroed unless the cell sets them
        setattr(opencat_gym_env, k, 0.0)
    for k, v in knobs.items():
        setattr(opencat_gym_env, k, v)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned", required=True)
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--seed", type=int, default=2000)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--family", default=None, help="only run cells in this family (e.g. ledge)")
    args = ap.parse_args()

    import benchmark_decathlon as _bd
    _bd._EXTRA_DR = "clean"   # payload off for the whole sweep

    opencat_gym_env.ADAPTIVE_PUSH = False
    env = OpenCatGymEnv()
    if hasattr(env, "set_command"):
        env.set_command(fwd=0.10, yaw=0.0)
    learned = _load_learned(args.learned)
    scripted = ScriptedGait(env)

    cells = [c for c in CELLS if args.family is None or c[1] == args.family]
    out = {"learned_path": args.learned, "episodes": args.episodes, "cells": []}
    for cid, family, label, knobs in cells:
        _apply_cell(knobs)
        print(f"\n=== {cid}  {family}  {label} ===", flush=True)
        rl, rl_eps = _bench(env, learned, args.episodes, args.seed, reflex=False)
        sc, sc_eps = _bench(env, scripted, args.episodes, args.seed, reflex=False)
        print(f"  learned fell {rl['fell_fraction']:.0%}  |  scripted fell {sc['fell_fraction']:.0%}"
              f"  |  learned {rl['forward_speed_mps_mean']:.3f} m/s vs {sc['forward_speed_mps_mean']:.3f}",
              flush=True)
        out["cells"].append({
            "id": cid, "family": family, "label": label, "knobs": knobs,
            "learned": {m: rl.get(m) for m in _METRICS},
            "scripted": {m: sc.get(m) for m in _METRICS},
        })
    env.close()
    if args.json_out:
        json.dump(out, open(args.json_out, "w"), indent=2)
        print(f"\nwrote {args.json_out}")
