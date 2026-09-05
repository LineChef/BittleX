#!/usr/bin/env python3
"""Graceful-degradation sweeps -- OPT-IN, not part of the standard eval.

The decathlon tests fixed difficulty points (T6.5 = exactly 60% torque
cutback). This instead varies one sim-to-real stressor across a range and
records the whole curve, so you can see the SHAPE of how a policy falls apart
-- two policies can both pass "60%, 0 falls" while one cliffs at 65% and the
other holds to 80%. The gentler curve = more real-world margin.

Axes (all existing env knobs, no env changes):
  torque  -- TORQUE_CUTBACK 0..0.70   (weak / overheated servos)
  imu     -- RANDOM_GYRO    0..0.10   (IMU noise tolerance; trained at 0.02)
  payload -- PAYLOAD_MASS_NOM 0.04..0.14 kg, fixed (trained ~0.043-0.079)

Run it when choosing a policy for hardware, or to check whether a training
change traded deployment margin for nominal performance -- NOT every eval
(it's ~900-1300 episodes).

  python degradation_sweep.py --learned trained/run20m_newcourse_ppo \
      --learned-b trained/run20m_ppo --json-out sweep.json
"""
import argparse, json
import numpy as np

import opencat_gym_env
from benchmark_gaits import ScriptedGait, _load_learned, _bench
from benchmark_decathlon import _apply

D = np.radians

AXES = {
    "torque":  ("TORQUE_CUTBACK",   [0.0, 0.15, 0.30, 0.45, 0.55, 0.65, 0.70]),
    "imu":     ("RANDOM_GYRO",      [0.0, 0.02, 0.04, 0.06, 0.08, 0.10]),
    "payload": ("PAYLOAD_MASS_NOM", [0.040, 0.061, 0.080, 0.100, 0.120, 0.140]),
}


def _set_axis(axis, level, bare=False):
    """Reset to a clean baseline, then dial in exactly one stressor."""
    _apply({})                       # zeroes _ZERO knobs, DR_EVAL_FULL on, payload per _EXTRA_DR
    # payload-on is the deployed condition, but its inertia masks single
    # stressors (same reason the decathlon has bare-robot cells) -- --bare is
    # where torque / IMU degradation actually shows a curve.
    opencat_gym_env.PAYLOAD_PROB = 0.0 if bare else 1.0
    opencat_gym_env.PAYLOAD_MASS_RAND = 0.0     # fixed payload so the sweep is clean
    opencat_gym_env.ROUGH_TERRAIN = 0.0
    opencat_gym_env.TORQUE_CUTBACK = 0.0
    opencat_gym_env.RANDOM_GYRO = 0.02          # the trained nominal
    if axis == "torque":
        opencat_gym_env.TORQUE_CUTBACK = level
    elif axis == "imu":
        opencat_gym_env.RANDOM_GYRO = level
    elif axis == "payload":
        opencat_gym_env.PAYLOAD_MASS_NOM = level


def _onset(levels, fell):
    """First swept level where fall rate crosses 15% (the 'it starts failing here' point)."""
    for lv, fr in zip(levels, fell):
        if fr >= 0.15:
            return lv
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned", required=True)
    ap.add_argument("--learned-b", default=None, help="optional second policy to overlay")
    ap.add_argument("--scripted", action="store_true", help="also sweep the scripted wkF gait")
    ap.add_argument("--bare", action="store_true",
                    help="PAYLOAD_PROB=0 -- bare robot, where torque/IMU stressors actually bite "
                         "(payload-on masks them, same as the decathlon's bare-robot cells)")
    ap.add_argument("--episodes", type=int, default=25)
    ap.add_argument("--axes", default="torque,imu,payload")
    ap.add_argument("--seed", type=int, default=2000)
    ap.add_argument("--json-out", default="degradation_sweep.json")
    args = ap.parse_args()

    from opencat_gym_env import OpenCatGymEnv
    env = OpenCatGymEnv()
    gaits = [("learned", _load_learned(args.learned))]
    if args.learned_b:
        gaits.append(("learned_b", _load_learned(args.learned_b)))
    if args.scripted:
        gaits.append(("scripted", ScriptedGait(env)))

    out = {"learned": args.learned, "learned_b": args.learned_b,
           "episodes": args.episodes, "bare": args.bare, "axes": {}}

    for axis in args.axes.split(","):
        axis = axis.strip()
        knob, levels = AXES[axis]
        print(f"\n{'='*78}\nAXIS: {axis}   ({knob})   levels {levels}\n{'='*78}")
        hdr = f"{'level':>8}  " + "  ".join(f"{n:>22}" for n, _ in gaits)
        print(hdr)
        print(f"{'':>8}  " + "  ".join(f"{'fell%  spd   trkErr':>22}" for _ in gaits))
        rows = {n: {"fell": [], "speed": [], "trk": []} for n, _ in gaits}
        for lv in levels:
            _set_axis(axis, lv, bare=args.bare)
            cells = []
            for name, model in gaits:
                s, _ = _bench(env, model, args.episodes, args.seed)
                rows[name]["fell"].append(s["fell_fraction"])
                rows[name]["speed"].append(s["forward_speed_mps_mean"])
                rows[name]["trk"].append(s.get("speed_track_err_mean"))
                cells.append(f"{s['fell_fraction']*100:4.0f}  {s['forward_speed_mps_mean']:.3f}  "
                             f"{(s.get('speed_track_err_mean') or 0):.3f}")
            lvl_str = f"{lv:.3f}" if axis == "payload" else f"{lv:.2f}"
            print(f"{lvl_str:>8}  " + "  ".join(f"{c:>22}" for c in cells))
        out["axes"][axis] = {
            "knob": knob, "levels": levels,
            "series": {n: rows[n] for n in rows},
            "degradation_onset": {n: _onset(levels, rows[n]["fell"]) for n in rows},
        }
        print("  degradation onset (fall rate >= 15%):")
        for n in rows:
            o = out["axes"][axis]["degradation_onset"][n]
            print(f"    {n:>12}: {o if o is not None else 'held across the whole sweep'}")

    env.close()
    with open(args.json_out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nwrote {args.json_out}")

    # headline: which policy holds its margin longer, per axis
    if args.learned_b:
        print(f"\n{'-'*78}\nMARGIN COMPARISON (later onset = more real-world headroom):")
        for axis in out["axes"]:
            oa = out["axes"][axis]["degradation_onset"]
            a_o, b_o = oa.get("learned"), oa.get("learned_b")
            def k(x): return 1e9 if x is None else x
            better = "learned" if k(a_o) > k(b_o) else ("learned_b" if k(b_o) > k(a_o) else "tie")
            print(f"  {axis:>8}: learned onset {a_o}  |  learned_b onset {b_o}  ->  {better}")


if __name__ == "__main__":
    main()
