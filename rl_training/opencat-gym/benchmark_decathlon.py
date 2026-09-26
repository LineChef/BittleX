"""The Decathlon -- a graded learned-vs-scripted comparison that ramps from
easy to brutal across every skill G2 has been trained on.

21 cells in 11 categories, rebuilt 2026-09-23 for the payload-bug-fixed fresh-
start training campaign (see docs/rl/hw1-log.md): every cell payload-on, no
bare-robot variants (removed per user decision -- a 30% time cost per run,
not worth paying every iteration), categories map onto the redesigned staged
training course one-to-one so a cell result reads directly as "did this stage
train". Both gaits run every cell on matched per-episode seeds. Replaces the
24-cell/8-tier version (see git history for that LADDER) -- old cell IDs
(T5.1b, T6.2b-T6.5b, T9.1-T9.4, etc.) referenced in older docs/scripts are
historical and no longer exist here.
Writes a JSON that build_decathlon_report.py turns into an HTML report.

    python benchmark_decathlon.py --learned trained/<tag>_ppo --episodes 20 \
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
from benchmark_gaits import ScriptedGait, BalancedLearned, _load_learned, _bench, _render

D = math.radians

# knob keys we reset before every cell so each cell tests only what it declares
_ZERO = ("RANDOM_FRICTION", "RANDOM_MASS", "RANDOM_GYRO", "RANDOM_PUSH", "RANDOM_TERRAIN",
         "IMPULSE_PUSH", "SLOPE_MAX_DEG", "START_POSE_JITTER", "STUCK_FOOT_PROB",
         "SUSTAINED_FORCE", "DEFORM_GROUND", "SLIP_PATCH",
         "TORQUE_CUTBACK", "LEDGE_HEIGHT", "LEDGE_PROB", "LEDGE_DIR", "RUBBLE", "RUBBLE_PROB",
         "CARPET", "CARPET_SWELL", "CARPET_SOFT",
         # new course mechanics (2026-09-23) -- same leak risk as everything else here
         "SURFACE_TRANSITION_PROB", "SURFACE_TRANSITION_STEP_M", "RUG_SLIDE_PROB", "SNAG_OBSTACLE_PROB")

# (id, tier, skill, human label, {env knob overrides})
# 11 categories / 21 cells, one-to-one with the redesigned staged training
# course (docs/rl/hw1-log.md, 2026-09-23 rebuild). Payload on throughout --
# bare-robot variants removed per user decision (30% of run time for a
# diagnostic that rarely changed a call). "modest" slope/cross-slope severity
# per user direction: G2 won't see steep grades often in real use, so this
# ladder isn't chasing a severity ceiling the way the old T6 tier did.
LADDER = [
    ("T1.1", 1, "flat walk",      "Flat, calm",                 {}),
    ("T1.2", 1, "straight line",  "Flat + gentle nudges",       {"RANDOM_PUSH": 0.12, "RANDOM_PUSH_PROB": 0.02}),

    ("T2.1", 2, "slopes",         "Downhill  (8 deg)",          {"SLOPE_FIXED_RP": (0.0, D(8))}),
    ("T2.2", 2, "slopes",         "Uphill  (12 deg)",           {"SLOPE_FIXED_RP": (0.0, D(-12))}),

    ("T3.1", 3, "slopes",         "Cross-slope  (5 deg roll)",  {"SLOPE_FIXED_RP": (D(5), 0.0)}),
    ("T3.2", 3, "slopes",         "Cross-slope  (10 deg roll)", {"SLOPE_FIXED_RP": (D(10), 0.0)}),

    # Transitions (B17 in behavior-ideas.md): material change alone, then the
    # same transition with a small step at the same point -- real doorway
    # thresholds usually carry both at once (2026-09-23 user clarification).
    ("T4.1", 4, "transition",     "Carpet-to-hard transition  (material only)",
        {"SURFACE_TRANSITION_PROB": 1.0, "SURFACE_TRANSITION_STEP_M": 0.0, "ROUGH_TERRAIN": 0.0}),
    ("T4.2", 4, "transition",     "Carpet-to-hard transition + small step  (12 mm)",
        {"SURFACE_TRANSITION_PROB": 1.0, "SURFACE_TRANSITION_STEP_M": 0.012, "ROUGH_TERRAIN": 0.0}),

    # Ledge / step, direction-random each episode -- a realistic disturbance
    # (door sills, rug edges, low curbs) the payload's inertia does not paper
    # over. Three heights spanning realistic sill (15mm) to past-comfortable
    # stress (40mm) for a blind low-clearance trot.
    ("T5.1", 5, "ledge",          "Ledge  (15 mm, random up/down)",
        {"LEDGE_HEIGHT": 0.015, "LEDGE_PROB": 1.0, "LEDGE_DIR": 0}),
    ("T5.2", 5, "ledge",          "Ledge  (25 mm, random up/down)",
        {"LEDGE_HEIGHT": 0.025, "LEDGE_PROB": 1.0, "LEDGE_DIR": 0}),
    ("T5.3", 5, "ledge",          "Ledge  (40 mm, random up/down)  -- past-comfortable stress",
        {"LEDGE_HEIGHT": 0.040, "LEDGE_PROB": 1.0, "LEDGE_DIR": 0}),

    ("T6.1", 6, "terrain",        "Rubble  (moderate)",
        {"RUBBLE": 0.016, "RUBBLE_N": 400, "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.015}),
    ("T6.2", 6, "terrain",        "Rubble  (dense, deeper than training)",
        {"RUBBLE": 0.024, "RUBBLE_N": 680, "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.026, "_episodes": 40}),

    ("T7.1", 7, "obstacles",      "Box obstacles  (25 mm)",     {"RANDOM_TERRAIN": 0.025}),
    ("T7.2", 7, "obstacles",      "Snag obstacles  (thin, lane-spanning -- cable/cord analog)",
        {"SNAG_OBSTACLE_PROB": 1.0}),

    ("T8.1", 8, "stumble-catch",  "Brutal shoves  (1.00 @ 0.018)",
        {"IMPULSE_PUSH": 1.00, "IMPULSE_PUSH_PROB": 0.018, "RANDOM_PUSH": 0.25}),

    ("T9.1", 9, "weak servos",    "Overheated servos (60% cutback) + 12 deg uphill",
        {"TORQUE_CUTBACK": 0.60, "SLOPE_FIXED_RP": (0.0, D(-12))}),

    # Rug: bumpy/soft fitted carpet (high-grip) vs a loose slick rug
    # (low-grip) -- opposite failure modes, deliberately both kept.
    ("T10.1", 10, "carpet",       "House carpet  (flat, mild compliance)",
        {"CARPET": 0.0, "CARPET_PROB": 1.0, "CARPET_SOFT": 0.3}),
    ("T10.2", 10, "carpet",       "Slick tile / low-friction hard floor  (reduced grip)",
        {"RUG_SLIDE_PROB": 1.0, "ROUGH_TERRAIN": 0.0, "SURFACE_TRANSITION_PROB": 0.0}),

    # Combined gauntlet stress -- the two hardest cells in the ladder, episode
    # count bumped for confidence per the same reasoning as the old bare-robot
    # cells: once results start moving, 20 samples isn't enough to trust.
    ("T11.1", 11, "everything",   "The gauntlet: 9 deg downhill + 4 deg side-hill + rubble + repeated shoves",
        {"SLOPE_FIXED_RP": (D(4), D(9)), "RUBBLE": 0.016, "RUBBLE_N": 400,
         "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.015,
         "IMPULSE_PUSH": 0.60, "IMPULSE_PUSH_PROB": 0.012, "RANDOM_PUSH": 0.25, "_episodes": 40}),
    ("T11.2", 11, "everything",   "Brutal gauntlet: 20 deg downhill + 8 deg side-hill + dense rubble + brutal shoves",
        {"SLOPE_FIXED_RP": (D(8), D(20)), "RUBBLE": 0.020, "RUBBLE_N": 560,
         "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.020,
         "IMPULSE_PUSH": 1.00, "IMPULSE_PUSH_PROB": 0.018, "RANDOM_PUSH": 0.45, "_episodes": 40}),
]

GIF_CELLS = {                      # one representative cell per report category
    "T1.1": "baseline",
    "T2.2": "progression",         # steepest single-slope cell
    "T6.2": "surface",             # dense rubble, deeper than training
    "T5.2": "hazard",              # mid-height ledge -- a known near-limit realistic case
    "T11.2": "compound",           # brutal gauntlet -- the headline hardest test
}
_METRICS = ["fell_fraction", "forward_speed_mps_mean", "forward_distance_m_mean",
            "diagonal_trot_corr_mean", "yaw_rate_rms_deg_mean", "lat_offset_max_m_mean",
            "recovery_events", "recovery_time_steps_mean", "big_stumble_recovery_rate",
            # command-following + tail (2026-09-05): cheap post-hoc adds
            "speed_track_err_mean", "heading_drift_deg_mean",
            "worst_ep_fwd_dist_m", "p10_ep_fwd_dist_m", "n_episodes", "fell_episodes"]


# sim2real DR that is NOT part of any cell's declared difficulty. "full" leaves
# the env module defaults (payload 90%, rough patch 35%, torque cutback 40%);
# "clean" removes all three so a cell tests exactly its label; "payload" removes
# rough + cutback but forces the Pi/camera payload on every episode so its cost
# can be read directly against the "clean" run.
_EXTRA_DR = "full"


# Sign convention (verified 2026-09-23 by walking forward on the tilted plane):
# SLOPE_FIXED_RP pitch > 0 is DOWNHILL for forward walking, < 0 uphill; roll is
# side-hill. Until 2026-09-23 every up/down label here was inverted.
#
# BENCH_VERSION 2 (2026-09-23): slope cells no longer get rough-terrain episodes
# -- a rough episode resets the grade to 0 in the env, so ~35 % of every slope
# cell's episodes were flat rough ground. Results from version 1 aren't
# comparable on slope cells; --scripted-from refuses to mix versions.
# BENCH_VERSION 3 (2026-09-23): the welded payload no longer locks the body's
# rotation (opencat_gym_env PAYLOAD_INERTIA); every payload-on result before it
# was on a tilt-locked robot.
BENCH_VERSION = 3

# Module default of every knob any cell sets, captured at import. _apply
# restores these before each cell: until 2026-09-22 knobs outside _ZERO leaked
# from one cell into every later one -- most importantly the bare-robot cells'
# PAYLOAD_PROB=0, which silently ran every cell after T6.5b (T7.x-T9.x) with no
# Pi/battery payload (learned-gait T9.1 falls: 8/20 bare vs 0/20 with payload).
_CELL_DEFAULTS = {k: getattr(opencat_gym_env, k)
                  for c in LADDER for k in c[4]
                  if not k.startswith("_") and hasattr(opencat_gym_env, k)}
# ROUGH_TERRAIN isn't a cell knob but _apply zeroes it for slope cells -- restore it too
_CELL_DEFAULTS["ROUGH_TERRAIN"] = opencat_gym_env.ROUGH_TERRAIN


def _apply(cell_knobs):
    for k, v in _CELL_DEFAULTS.items():
        setattr(opencat_gym_env, k, v)
    for k in _ZERO:
        if hasattr(opencat_gym_env, k):
            setattr(opencat_gym_env, k, 0.0)
    opencat_gym_env.SLOPE_FIXED_RP = None
    opencat_gym_env.SLIP_PATCH = 0.0
    opencat_gym_env.SUSTAINED_FORCE = 0.0
    opencat_gym_env.RANDOM_PUSH_PROB = 0.03
    opencat_gym_env.IMPULSE_PUSH_PROB = 0.0
    # RANDOM_TERRAIN_PROB/RUBBLE_PROB default to training-only values (obstacles
    # now occasional, not every episode) -- eval cells want them deterministic, so
    # force back to 1.0.
    #
    # RANDOM_TERRAIN_X_RANGE / RUBBLE_X_RANGE are NOT reset here (2026-09-04):
    # eval episodes use the same EPISODE_LENGTH as training and travel the same
    # ~0.2-0.3m (confirmed against real decathlon output, every cell), so the old
    # wide placement range (out to 1.3m / 3.4m) wasted compute simulating bodies
    # eval would never reach either, same as training. The tightened module
    # default applies everywhere now.
    #
    # RANDOM_TERRAIN_MAX_H stays eval-exempt, deliberately: T4.4/T6.2 etc are a
    # severity progression meant to probe PAST guaranteed-passable, not stay
    # under a training-safety cap.
    opencat_gym_env.RANDOM_TERRAIN_PROB = 1.0
    opencat_gym_env.RANDOM_TERRAIN_MAX_H = 999.0
    opencat_gym_env.DR_EVAL_FULL = True
    if cell_knobs.get("SLOPE_FIXED_RP") is not None:
        opencat_gym_env.ROUGH_TERRAIN = 0.0    # a rough episode would reset the grade to 0
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
    ap.add_argument("--learned-balance", type=float, default=0.0,
                    help="2026-09-04: apply the SAME proportional tilt correction as "
                         "--scripted-balance to the learned policy's output, post-hoc -- no "
                         "retraining. Probed at 0.6: closed most/all of the bare-robot gap "
                         "vs scripted (T6.2b 17%%->0%% fell, T6.3b 80%%->40%%). Off (0.0) by "
                         "default so existing reports stay comparable; opt in explicitly.")
    ap.add_argument("--episodes", type=int, default=28)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--gif-dir", default=None)
    ap.add_argument("--extra-dr", choices=("full", "clean", "payload"), default="full",
                    help="non-cell DR: full=env defaults, clean=no payload/rough/cutback, "
                         "payload=payload forced on, rough+cutback off")
    ap.add_argument("--hw", choices=("i", "m", "ifast"), default=None,
                    help="score the LEARNED gait through G2's real control path: stock 5 Hz "
                         "IMU with no rate (IMU_HOLD_STEPS=16, IMU_RATE_ZERO) and this joint "
                         "command through firmware_model (CMD_PATH). The scripted walk runs "
                         "natively either way -- the firmware plays kwkF from its own memory.")
    ap.add_argument("--scripted-from", default=None,
                    help="reuse the scripted walk's per-cell results from an earlier decathlon JSON "
                         "instead of re-simulating them (~half the runtime). Only valid when that run "
                         "used the same --episodes/--seed/--extra-dr/--scripted-balance and env "
                         "defaults: the scripted walk is deterministic under those (identical across "
                         "every 2026-09-22 run). Checked below; mismatches abort.")
    args = ap.parse_args()

    global _EXTRA_DR
    _EXTRA_DR = args.extra_dr

    opencat_gym_env.ADAPTIVE_PUSH = False        # training-time curriculum state -- off for eval
    env = OpenCatGymEnv()
    if hasattr(env, 'set_command'):        # gait-refinement: measure on a fixed cruise-forward command
        env.set_command(fwd=0.10, yaw=0.0)
    learned = _load_learned(args.learned)
    if args.learned_balance:
        learned = BalancedLearned(learned, env, k=args.learned_balance)
    scripted = ScriptedGait(env, balance_k=args.scripted_balance)

    def _hw(on):
        opencat_gym_env.IMU_HOLD_STEPS = 16 if on else 0
        opencat_gym_env.IMU_RATE_ZERO = bool(on)
        opencat_gym_env.CMD_PATH = args.hw if on else ""

    prior_sc = None
    if args.scripted_from:
        import json as _json
        prior = _json.load(open(args.scripted_from))
        for k, v in (("episodes", args.episodes), ("extra_dr", args.extra_dr),
                     ("scripted_balance", args.scripted_balance), ("bench_version", BENCH_VERSION)):
            if prior.get(k) != v:
                raise SystemExit(f"--scripted-from {args.scripted_from}: {k}={prior.get(k)!r}, this run {v!r}")
        prior_sc = {c["id"]: c for c in prior["cells"]}

    out = {"learned_path": args.learned, "episodes": args.episodes, "hw": args.hw,
           "bench_version": BENCH_VERSION,
           "scripted_from": args.scripted_from,
           "extra_dr": args.extra_dr, "scripted_balance": args.scripted_balance, "cells": []}
    for cid, tier, skill, label, knobs in LADDER:
        # a cell can carry a reserved "_episodes" key to override the global
        # --episodes count -- used for the fall-focused cells (bare-robot,
        # gauntlets) where a real (nonzero) fall rate needs more samples to be
        # a trustworthy number, not just for a 0%-forever cell.
        cell_episodes = knobs.get("_episodes", args.episodes)
        real_knobs = {k: v for k, v in knobs.items() if k != "_episodes"}
        _apply(real_knobs)
        print(f"\n=== {cid}  T{tier}  {label}  ({cell_episodes} eps) ===", flush=True)
        _hw(args.hw)
        rl, rl_eps = _bench(env, learned, cell_episodes, args.seed, reflex=False)
        _hw(None)
        if prior_sc is not None:
            pc = prior_sc[cid]
            if pc["episodes"] != cell_episodes or pc["knobs"] != {k: (list(v) if isinstance(v, tuple) else v) for k, v in real_knobs.items()}:
                raise SystemExit(f"--scripted-from: cell {cid} differs from the saved run")
            sc = pc["scripted"]
            sc_fall = list(range(pc["scripted_fall_episodes"]))   # count only; per-episode ids not saved
        else:
            sc, sc_eps = _bench(env, scripted, cell_episodes, args.seed, reflex=False)
            sc_fall = [i for i, d in enumerate(sc_eps) if d["fell"]]
        cond_surv = (sum(1 for i in sc_fall if not rl_eps[i]["fell"]) / len(sc_fall)
                     if sc_fall and prior_sc is None else None)   # needs per-episode scripted falls
        print(f"  learned fell {rl['fell_fraction']:.0%}  |  scripted fell {sc['fell_fraction']:.0%}"
              f"  |  learned {rl['forward_speed_mps_mean']:.3f} m/s vs {sc['forward_speed_mps_mean']:.3f}"
              + (f"  |  cond.surv {cond_surv:.0%} of {len(sc_fall)}" if cond_surv is not None else ""),
              flush=True)
        rec = {"id": cid, "tier": tier, "skill": skill, "label": label, "episodes": cell_episodes,
               "knobs": {k: (list(v) if isinstance(v, tuple) else v) for k, v in real_knobs.items()},
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
