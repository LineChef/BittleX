"""The Decathlon -- a graded learned-vs-scripted comparison that ramps from
easy to brutal across every skill G2 has been trained on.

24 cells in 8 tiers (19 payload-on + 5 bare-robot fall-rate variants); both gaits
run every cell on matched per-episode seeds. Trimmed 2026-09-04 from an earlier
32-cell version -- see the LADDER comments for what was cut and why.
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
from benchmark_gaits import ScriptedGait, BalancedLearned, _load_learned, _bench, _render

D = math.radians

# knob keys we reset before every cell so each cell tests only what it declares
_ZERO = ("RANDOM_FRICTION", "RANDOM_MASS", "RANDOM_GYRO", "RANDOM_PUSH", "RANDOM_TERRAIN",
         "IMPULSE_PUSH", "SLOPE_MAX_DEG", "START_POSE_JITTER", "STUCK_FOOT_PROB",
         "SUSTAINED_FORCE", "DEFORM_GROUND", "SLIP_PATCH",
         "TORQUE_CUTBACK", "LEDGE_HEIGHT", "LEDGE_PROB", "LEDGE_DIR", "RUBBLE", "RUBBLE_PROB", "CARPET", "CARPET_SWELL", "CARPET_SOFT")

# (id, tier, skill, human label, {env knob overrides})
LADDER = [
    ("T1.1", 1, "flat walk",      "Flat, calm",                 {}),
    ("T1.2", 1, "straight line",  "Flat + gentle nudges",       {"RANDOM_PUSH": 0.12, "RANDOM_PUSH_PROB": 0.02}),

    # 2026-09-04: trimmed the pure severity-progression rungs that added no
    # signal beyond their endpoints (0% falls, ~1% speed delta -- see
    # docs/rl-runs/ for the full before/after). Gentle-up/gentle-down (T2.1/
    # T2.2) cut; steep up/down (T3.1/T3.2) and extreme down (T6.1, a real
    # discriminator) bracket the same range with the interesting result kept.
    # Cross-slope (T2.3) stays -- a different axis, not a severity step.
    ("T2.3", 2, "slopes",         "Cross-slope  (5 deg roll)",  {"SLOPE_FIXED_RP": (D(5), 0.0)}),
    ("T2.4", 2, "obstacles",      "Small obstacles  (20 mm)",   {"RANDOM_TERRAIN": 0.020}),

    ("T3.1", 3, "slopes",         "Steep up  (12 deg)",         {"SLOPE_FIXED_RP": (0.0, D(12))}),
    ("T3.2", 3, "slopes",         "Steep down  (-12 deg)",      {"SLOPE_FIXED_RP": (0.0, D(-12))}),
    # Medium/big obstacles (T3.3/T4.4) and the two-factor combos (T3.4
    # slope+obstacle, T4.3 obstacles+shoves) cut -- middle interpolation
    # points on a smooth trend, and the fuller Compound Stress category below
    # now covers combination effects more thoroughly than these narrower
    # two-factor cells did.

    ("T4.1", 4, "stumble-catch",  "One hard shove",
        {"IMPULSE_PUSH": 0.65, "IMPULSE_PUSH_PROB": 0.004}),
    ("T4.2", 4, "stumble-catch",  "Repeated shoves",
        {"IMPULSE_PUSH": 0.55, "IMPULSE_PUSH_PROB": 0.012}),

    ("T5.1", 5, "everything",     "The gauntlet: slope + rubble + repeated shoves",
        {"SLOPE_FIXED_RP": (D(4), D(9)), "RUBBLE": 0.016, "RUBBLE_N": 400,
         "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.015,
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
    ("T6.4", 6, "everything",     "Brutal gauntlet: 20 deg slope + dense rubble + brutal shoves",
        {"SLOPE_FIXED_RP": (D(8), D(20)), "RUBBLE": 0.020, "RUBBLE_N": 560,
         "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.020,
         "IMPULSE_PUSH": 1.00, "IMPULSE_PUSH_PROB": 0.018, "RANDOM_PUSH": 0.45}),
    ("T6.5", 6, "weak servos",    "Overheated servos (60% cutback) + 12 deg descent",
        {"TORQUE_CUTBACK": 0.60, "SLOPE_FIXED_RP": (0.0, D(-12))}),

    # Bare-robot variants (2026-09-04): every T5/T6 cell above reads 0% falls for
    # BOTH gaits with the payload on -- its own comment already says why (the
    # payload's inertia stabilizes hard enough to absorb any single stressor we
    # throw at it). These five re-run the hardest cells with PAYLOAD_PROB=0 --
    # no deployment mass to lean on -- as the actual fall-rate-focused diagnostic.
    # Added alongside the payload-on cells, not replacing them, so the rest of
    # the ladder's story (payload-on throughout) stays comparable end to end.
    # Episode count bumped (see _episodes) -- once a fall rate is genuinely
    # nonzero, 20 samples isn't enough to trust the number run over run.
    ("T5.1b", 5, "everything",     "The gauntlet -- bare robot",
        {"SLOPE_FIXED_RP": (D(4), D(9)), "RUBBLE": 0.016, "RUBBLE_N": 400,
         "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.015,
         "IMPULSE_PUSH": 0.60, "IMPULSE_PUSH_PROB": 0.012, "RANDOM_PUSH": 0.25,
         "PAYLOAD_PROB": 0.0, "_episodes": 60}),
    ("T6.2b", 6, "obstacles",      "Huge obstacles (85 mm) + push -- bare robot",
        {"RANDOM_TERRAIN": 0.085, "RANDOM_PUSH": 0.35,
         "PAYLOAD_PROB": 0.0, "_episodes": 60}),
    # T6.3b/T6.4b severity 2026-09-04: the T6.3/T6.4 payload-on knob values,
    # reused as-is for bare robot, landed at 95-97% fall rate -- basically
    # "always fails", as uninformative as the old 0% was, just at the other
    # extreme. Probed a few candidates (see docs/rl-runs/) and picked settings
    # that land in a real hard-but-passable band instead.
    ("T6.3b", 6, "stumble-catch",  "Brutal shoves (0.70 @ 0.012) -- bare robot",
        {"IMPULSE_PUSH": 0.70, "IMPULSE_PUSH_PROB": 0.012, "RANDOM_PUSH": 0.20,
         "PAYLOAD_PROB": 0.0, "_episodes": 60}),
    ("T6.4b", 6, "everything",     "Brutal gauntlet: 14 deg slope + dense rubble + brutal shoves -- bare robot",
        {"SLOPE_FIXED_RP": (D(6), D(14)), "RUBBLE": 0.020, "RUBBLE_N": 560,
         "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.020,
         "IMPULSE_PUSH": 0.70, "IMPULSE_PUSH_PROB": 0.012, "RANDOM_PUSH": 0.30,
         "PAYLOAD_PROB": 0.0, "_episodes": 60}),
    ("T6.5b", 6, "weak servos",    "Overheated servos (60% cutback) + 12 deg descent -- bare robot",
        {"TORQUE_CUTBACK": 0.60, "SLOPE_FIXED_RP": (0.0, D(-12)),
         "PAYLOAD_PROB": 0.0, "_episodes": 60}),

    # T7: ledge / step. A realistic disturbance (door sills, rug edges, low curbs)
    # the payload's inertia does NOT paper over -- a bad foot plant on an edge
    # still starts a topple. Score on fall rate AND recovery events / time-to-settle.
    # 2026-09-05: 30 mm reads as a near-limit stress for a blind low-clearance
    # trot (belly clearance ~40-60 mm, swing height much less) -- realistic sills
    # are 10-20 mm. Primary cells now 15/20 mm; 30 mm kept as an explicit
    # past-comfortable stress rung. Step-down (T7.4) restored at the realistic
    # height so both directions are visible even if "down" reads easy.
    ("T7.1", 7, "ledge",          "Threshold up  (15 mm)",
        {"LEDGE_HEIGHT": 0.015, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}),
    ("T7.2", 7, "ledge",          "Step up  (20 mm sill)",
        {"LEDGE_HEIGHT": 0.020, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}),
    ("T7.3", 7, "ledge",          "Step up  (30 mm) -- past-comfortable stress",
        {"LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}),
    ("T7.4", 7, "ledge",          "Step down  (20 mm sill)",
        {"LEDGE_HEIGHT": 0.020, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}),
    ("T7.5", 7, "ledge",          "Big ledge  (45 mm, random up/down)",
        {"LEDGE_HEIGHT": 0.045, "LEDGE_PROB": 1.0, "LEDGE_DIR": 0}),

    # T8: carpet / soft ground. Kept as a PERMANENT benchmark cell regardless of
    # whether any given checkpoint was trained on it (2026-09-04 decision) --
    # the point is tracking learned-vs-scripted on real soft/uneven ground over
    # time, not just when there happens to be a carpet-specific run to grade.
    # T8.1 is the user's actual carpet (~1/4in / 6.4mm pile, compliance
    # calibrated mild for G2's light paw-loading -- see opencat_gym_env.py
    # CARPET_SOFT comment). T8.2 is rough, uneven ground: fine dense bumps
    # (CARPET) PLUS a broad rolling-hill swell (CARPET_SWELL) in the same cell
    # -- deliberately combined, not two separate courses (2026-09-04: this
    # combination, not a standalone rolling-hills tier, is what "very uneven
    # terrain" meant in practice; ROUGH_TERRAIN, the separate rolling-hill-only
    # heightfield, stays unused -- CARPET_SWELL already covers that ground).
    ("T8.1", 8, "carpet",         "House carpet  (flat, mild compliance)",
        {"CARPET": 0.0, "CARPET_PROB": 1.0, "CARPET_SOFT": 0.3}),
    ("T8.2", 8, "carpet",         "Rough, uneven ground: dense bumps + rolling swell  (19 mm bumps + 35 mm swell)",
        {"CARPET": 0.019, "CARPET_SWELL": 0.035, "CARPET_PROB": 1.0}),

    # T9: HELD-OUT generalization tier (2026-09-05). Conditions deliberately
    # OUTSIDE the training distribution -- the policy never trains on these
    # regimes. A policy that learned a robust gait holds up; one that overfit
    # the training course degrades sharply. All fast (250-step) cells, kept to
    # four so the tier stays cheap (~3 min/gait).
    ("T9.1", 9, "held-out",       "Slope 18 deg up (beyond training's 14 deg ceiling)",
        {"SLOPE_FIXED_RP": (0.0, D(18)), "_episodes": 40}),
    ("T9.2", 9, "held-out",       "Slope 20 deg down (beyond training; descent is harder)",
        {"SLOPE_FIXED_RP": (0.0, D(-20)), "_episodes": 40}),
    ("T9.3", 9, "held-out",       "Rubble denser + taller than anything in training",
        {"RUBBLE": 0.024, "RUBBLE_N": 680, "RUBBLE_PROB": 1.0, "RUBBLE_MAX_H": 0.026,
         "_episodes": 40}),
    ("T9.4", 9, "held-out",       "Slippery incline: 6 deg + heavy friction randomization (wet-ramp analog)",
        {"SLOPE_FIXED_RP": (0.0, D(6)), "RANDOM_FRICTION": 0.6, "_episodes": 40}),
]

GIF_CELLS = {                      # one representative cell per report category
    "T1.1": "baseline",
    "T6.1": "progression",         # slope progression's extreme end -- one of T6's real discriminators
    "T8.2": "surface",             # rough ground: dense bumps + rolling swell
    "T7.3": "hazard",              # step-up sill -- a known near-limit realistic case
    "T6.4b": "compound",           # brutal gauntlet, bare robot -- the headline hardest test
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


def _apply(cell_knobs):
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

    out = {"learned_path": args.learned, "episodes": args.episodes,
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
        rl, rl_eps = _bench(env, learned, cell_episodes, args.seed, reflex=False)
        sc, sc_eps = _bench(env, scripted, cell_episodes, args.seed, reflex=False)
        sc_fall = [i for i, d in enumerate(sc_eps) if d["fell"]]
        cond_surv = (sum(1 for i in sc_fall if not rl_eps[i]["fell"]) / len(sc_fall)
                     if sc_fall else None)
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
