"""Author `inspect_peer_ref.npy` -- a nose-DOWN 'peer' pose for INSPECT.

The current INSPECT keyframe (`cr_ref.npy`) is a roughly level low crouch: it
lowers the body-mounted camera but keeps it horizontal, so it doesn't gain much
downward view of the ground right in front. This builds the alternative: front
legs kneel / rear legs stay tall -> the body pitches nose-down ~15-20 deg -> the
camera aims at the near ground (a "play bow").

Method: empirical search in PyBullet. For a grid of (front-shoulder, front-knee,
rear-hip, rear-knee) offsets from the neutral stance, drop the robot into the
pose, let it settle, and measure body pitch / height / stability. Pick the pose
closest to the target nose-down pitch that stays upright, save it as a 1-frame
(1, 8) keyframe in the reference_gait format (radians, URDF joint order).

    python reference_gait/build_inspect_peer.py            # search + save
    python reference_gait/build_inspect_peer.py --render   # watch the winner
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("G2E_OBSTACLE_COUNT", "0")
os.environ.setdefault("G2E_RANDOM_TERRAIN_PROB", "0")
os.environ.setdefault("G2E_SLOPE_MAX_DEG", "0")
os.environ.setdefault("G2E_CLIFF_PROB", "0")

import pybullet as p                                                   # noqa: E402
import opencat_gym_env                                                 # noqa: E402
from opencat_gym_env import OpenCatGymEnv, WKF_REF                      # noqa: E402

HERE = os.path.dirname(__file__)
NAMES = ["FLsh", "FLkn", "FRsh", "FRkn", "BRhip", "BRkn", "BLhip", "BLkn"]
FRONT_SH, FRONT_KN = [0, 2], [1, 3]
REAR_HIP, REAR_KN = [4, 6], [5, 7]

TARGET_PITCH = 0.22        # rad, nose-down (+ve = nose down in this URDF). ~13 deg.
SETTLE = 80


def pose_from(stance, a, b, c, d):
    q = stance.copy()
    for i in FRONT_SH:
        q[i] += a
    for i in FRONT_KN:
        q[i] += b            # -ve = front legs kneel
    for i in REAR_HIP:
        q[i] += c
    for i in REAR_KN:
        q[i] += d            # +ve = rear knees straighten (rear stands tall)
    return q


def measure(env, pose):
    p.resetBasePositionAndOrientation(env.robot_id, [0, 0, 0.12], [0, 0, 0, 1])
    p.resetBaseVelocity(env.robot_id, [0, 0, 0], [0, 0, 0])
    for _ in range(SETTLE):
        env._abs_joint_override = pose
        env.step(np.zeros(8, dtype=np.float32))
        env._abs_joint_override = None
    (x, y, z), orn = p.getBasePositionAndOrientation(env.robot_id)
    roll, pitch, _ = p.getEulerFromQuaternion(orn)
    return pitch, z, roll


def search(env, stance):
    grid_a = [-0.45, -0.30, -0.15, 0.0, 0.15]     # FLsh: -ve = front legs reach forward
    grid_b = [-0.20, -0.45, -0.70, -0.95]         # FLkn: -ve = front knees bend (kneel)
    grid_c = [-0.35, -0.20, -0.05, 0.10]          # BRhip
    grid_d = [-0.10, 0.10, 0.30, 0.50]            # BRkn: +ve = rear knees straighten (rear tall)
    best, best_cost = None, 1e9
    for a in grid_a:
        for b in grid_b:
            for c in grid_c:
                for d in grid_d:
                    pose = pose_from(stance, a, b, c, d)
                    if pose.min() < -1.9 or pose.max() > 1.9:
                        continue
                    pitch, z, roll = measure(env, pose)
                    upright = abs(roll) < 0.35 and z > 0.02
                    if not upright:
                        continue
                    cost = abs(pitch - TARGET_PITCH) + 0.5 * max(0.0, 0.05 - z)
                    if cost < best_cost:
                        best_cost, best = cost, (a, b, c, d, pitch, z, roll)
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true")
    args = ap.parse_args()

    opencat_gym_env.GUI_MODE = args.render
    opencat_gym_env.DR_EVAL_FULL = False
    env = OpenCatGymEnv()
    env.reset()
    stance = WKF_REF.mean(axis=0)

    best = search(env, stance)
    if best is None:
        print("no stable nose-down pose found in the grid -- widen it")
        env.close()
        return
    a, b, c, d, pitch, z, roll = best
    pose = pose_from(stance, a, b, c, d)
    print(f"winner: a(FLsh)={a:+.2f} b(FLkn)={b:+.2f} c(BRhip)={c:+.2f} d(BRkn)={d:+.2f}")
    print(f"  settled pitch {np.rad2deg(pitch):+.1f} deg (target {np.rad2deg(TARGET_PITCH):+.1f}), "
          f"height {z:.3f} m, roll {np.rad2deg(roll):+.1f} deg")
    print("  pose (deg):", dict(zip(NAMES, np.rad2deg(pose).round(1))))

    out = os.path.join(HERE, "inspect_peer_ref.npy")
    np.save(out, pose.reshape(1, 8).astype(np.float64))
    print(f"saved {out}  shape (1, 8)")

    if args.render:
        print("holding the pose in the GUI -- Ctrl-C to exit")
        try:
            while True:
                env._abs_joint_override = pose
                env.step(np.zeros(8, dtype=np.float32))
                env._abs_joint_override = None
        except KeyboardInterrupt:
            pass
    env.close()


if __name__ == "__main__":
    main()
