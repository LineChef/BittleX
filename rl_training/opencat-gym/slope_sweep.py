"""Slope sweep: where are G2's real slope limits? (2026-09-23)

The slope-ceiling campaign (docs/rl/slope-ceiling-log.md) was built on T9.1/T9.2
falls measured while the benchmark was silently running those cells WITHOUT the
payload (the cell-knob leak fixed in hw1). This re-measures from scratch, as
close to G2 as the sim gets:

  - payload on (env default), BODY_MASS_SCALE 1.12, IMU_BIAS_DEG 2, JOINT_OFFSET_DEG 2
  - learned gait through the real control path (5 Hz IMU, no rate, `i` timing);
    the scripted walk runs natively, as the firmware plays kwkF
  - uphill / downhill (pitch; pitch > 0 is downhill) and side-hill (roll; the
    sign picks which side is down), fixed per condition

    python slope_sweep.py --learned trained/hw1_20m_ppo
    python slope_sweep.py --learned trained/hw1_20m_ppo --episodes 10 --up 12,24 --down 12,24 --cross 12
"""
import argparse
import json
import math

import numpy as np

import opencat_gym_env as E
import benchmark_decathlon as B
from benchmark_gaits import ScriptedGait, _load_learned, _bench
from opencat_gym_env import OpenCatGymEnv

D = math.radians


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned", default="trained/hw1_20m_ppo")
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--seconds", type=float, default=5.0)
    ap.add_argument("--up", default="4,8,12,16,20,24,28")
    ap.add_argument("--down", default="4,8,12,16,20,24,28")
    ap.add_argument("--cross", default="5,8,12,16,20")
    ap.add_argument("--seed", type=int, default=3000)
    ap.add_argument("--json-out", default="trained/slope_sweep_hw1_20m.json")
    args = ap.parse_args()

    conds = [("flat", 0.0, 0.0)]
    # env sign: pitch > 0 is DOWNHILL for forward walking (verified 2026-09-23)
    conds += [(f"up {v}", 0.0, -D(float(v))) for v in args.up.split(",") if v]
    conds += [(f"down {v}", 0.0, D(float(v))) for v in args.down.split(",") if v]
    conds += [(f"side {v}", D(float(v)), 0.0) for v in args.cross.split(",") if v]

    E.ADAPTIVE_PUSH = False
    E.EPISODE_LENGTH = int(args.seconds * 80)
    realistic = dict(BODY_MASS_SCALE=1.12, IMU_BIAS_DEG=2.0, JOINT_OFFSET_DEG=2.0,
                     # pure slopes: a rough-terrain episode resets the grade to 0
                     # (opencat_gym_env reset, 2026-09-05 slope-collapse fix), and the
                     # random servo torque cut would confound the slope effect
                     ROUGH_TERRAIN=0.0, TORQUE_CUTBACK=0.0)
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    learned = _load_learned(args.learned)
    scripted = ScriptedGait(env)

    def hw(on):
        E.IMU_HOLD_STEPS = 16 if on else 0
        E.IMU_RATE_ZERO = bool(on)
        E.CMD_PATH = "i" if on else ""

    out = []
    print(f"{'slope':>9} | {'learned falls':>13} {'m/s':>6} {'drift°':>6} | {'scripted falls':>14} {'m/s':>6} {'drift°':>6}")
    for name, roll, pitch in conds:
        B._apply({})
        for k, v in realistic.items():
            setattr(E, k, v)
        E.SLOPE_FIXED_RP = (roll, pitch) if (roll or pitch) else None
        E.EPISODE_LENGTH = int(args.seconds * 80)
        hw(True)
        rl, _ = _bench(env, learned, args.episodes, args.seed)
        hw(False)
        sc, _ = _bench(env, scripted, args.episodes, args.seed)
        row = dict(slope=name, roll_deg=math.degrees(roll), pitch_deg=math.degrees(pitch),
                   learned={k: rl.get(k) for k in B._METRICS}, scripted={k: sc.get(k) for k in B._METRICS})
        out.append(row)
        print(f"{name:>9} | {rl['fell_fraction']*100:12.0f}% {rl['forward_speed_mps_mean']:6.3f} {rl['heading_drift_deg_mean']:6.1f} | "
              f"{sc['fell_fraction']*100:13.0f}% {sc['forward_speed_mps_mean']:6.3f} {sc['heading_drift_deg_mean']:6.1f}", flush=True)
    with open(args.json_out, "w") as f:
        json.dump(dict(learned=args.learned, episodes=args.episodes, seconds=args.seconds,
                       realistic=realistic, rows=out), f, indent=1)


if __name__ == "__main__":
    main()
