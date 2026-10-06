"""Replay real walk logs' IMU readings through the deployed policy, offline, to test the yaw sign the Pi feeds it.

    ../../.venv/bin/python replay_real_obs.py [--policy trained/Release_CandidateV2.1_ppo.onnx] [log.csv ...]

For each `run_gait.py --log` CSV (default: docs/rl/real-walk-data/2026-10-06/*.csv) the logged roll/pitch/yaw rows are fed through
`ResidualGaitPolicy` the way `run_gait.run` does it (reset on the first frame with yaw 0, then one `step` per logged tick, rate obs zero).
Pass 1 uses the yaw as logged: if it reproduces the logged joint commands, the replay is faithful. Pass 2 negates the yaw (the PyBullet
convention, + = left, if the firmware's + = right). Prints, per pass, the match against the log and the left/right bias of the commands.
The policy's joint history comes from its own outputs, so the replay is closed in the joints but open in the body: pass 2 shows what the
policy would have commanded at the same moments, not where G2 would then have gone.
"""
import argparse
import glob
import math
import os
import sys

import numpy as np

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "pi_pipeline", "gait"))
from residual_policy import ResidualGaitPolicy  # noqa: E402
from run_gait import STAND_URDF_DEG, euler_to_quat  # noqa: E402

JOINTS = ["FLsh", "FLel", "FRsh", "FRel", "BRhip", "BRkn", "BLhip", "BLkn"]


def load(path):
    rows = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or line.startswith("t,"):
                continue
            c = line.strip().split(",")
            rows.append([float(x) for x in c[1:4]] + [int(x) for x in c[7:15]])
    a = np.array(rows, dtype=float)
    return a[:, :3], a[:, 3:]


def replay(policy, rpy, yaw_sign):
    policy.set_command(fwd=0.10, yaw=0.0)
    policy.reset(np.deg2rad(np.array(STAND_URDF_DEG, dtype=float)), euler_to_quat(rpy[0, 0], rpy[0, 1], 0.0), [0, 0, 0])
    out = []
    for r, p_, y in rpy:
        out.append(policy.step(euler_to_quat(r, p_, yaw_sign * y), [0.0, 0.0, 0.0]))
    return np.array(out, dtype=float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--policy", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "trained", "Release_CandidateV2.1_ppo.onnx"))
    a = ap.parse_args()
    logs = a.logs or sorted(glob.glob(os.path.join(_ROOT, "docs", "rl", "real-walk-data", "2026-10-06", "*.csv")))
    pol = ResidualGaitPolicy(onnx_path=a.policy)
    for path in logs:
        rpy, logged = load(path)
        dyaw = math.degrees(rpy[-1, 2] - rpy[0, 2])
        print(f"\n{os.path.basename(path)}: {len(rpy)} ticks, logged yaw change {dyaw:+.0f} deg (firmware sign, + = right)")
        print(f"  {'':16s}" + " ".join(f"{j:>6s}" for j in JOINTS))
        print(f"  {'logged mean':16s}" + " ".join(f"{v:6.1f}" for v in logged.mean(0)))
        for name, sign in (("yaw as logged", 1.0), ("yaw negated", -1.0)):
            jd = replay(pol, rpy, sign)
            exact = float(np.mean(np.all(jd == logged, axis=1)))
            mae = float(np.mean(np.abs(jd - logged)))
            print(f"  {name + ' mean':16s}" + " ".join(f"{v:6.1f}" for v in jd.mean(0))
                  + f"   ticks identical to log {exact:5.1%}, mean |diff| {mae:.2f} deg")


if __name__ == "__main__":
    main()
