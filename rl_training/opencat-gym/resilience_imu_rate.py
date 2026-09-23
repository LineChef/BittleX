"""IMU feedback-rate probe: does the deployed gait survive stock-firmware IMU?

Stock OpenCatEsp32 streams orientation at most every 200 ms (`imu.h`
`print6Axis()`, PRINT6AXIS_MIN_INTERVAL = 200 -> 5 Hz), rounded to 0.1 deg,
and carries NO angular rate at all. The policy was trained on fresh
orientation + true roll/pitch rate every 12.5 ms (80 Hz). This drives the sim
closed-loop with the *deployment* code (pi_pipeline/gait/residual_policy.py,
same ONNX the Pi runs) and feeds it IMU data degraded the way the real
serial stream would be, to measure what that gap costs.

Variants (orientation source / angular-rate source):
    fresh_true   80 Hz orientation, true rate          (the training condition)
    fresh_zero   80 Hz orientation, rate = 0
    hold_true    5 Hz held orientation, true rate      (isolates the rate limit)
    hold_zero    5 Hz held orientation, rate = 0       (stock firmware as-is)
    hold_fd      5 Hz held orientation, rate finite-differenced between
                 consecutive 5 Hz samples and held      (best stock-firmware option)

Environments are benchmark_decathlon.py cells (same knob resets via its _apply).

    python resilience_imu_rate.py
    python resilience_imu_rate.py --cells T1.1,T5.1,T6.3 --episodes 30 --json-out trained/imu_rate.json
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "pi_pipeline", "gait"))
sys.path.insert(0, HERE)
os.chdir(HERE)          # opencat_gym_env loads its URDF by relative path

import residual_policy                          # noqa: E402
from residual_policy import ResidualGaitPolicy  # noqa: E402

# The env's module default residual scale follows the current training
# campaign (30 deg for resid30); the deployed ONNX + residual_policy.py use
# their own. Pin the sim to the deploy code's scale BEFORE the env is
# imported (_g2e reads it at import), or actions are physically misapplied.
os.environ["G2E_RESIDUAL_SCALE_DEG"] = str(residual_policy.RESIDUAL_SCALE_DEG)

import opencat_gym_env as E                     # noqa: E402
import pybullet as p                            # noqa: E402

E.GUI_MODE = False
E.DEPLOY_DEBUG = True
E.DR_EVAL_FULL = True

VARIANTS = ("fresh_true", "fresh_zero", "hold_true", "hold_zero", "hold_fd")
HOLD_STEPS = 16          # 80 Hz control / 5 Hz print = 16 ticks per fresh IMU sample
QUANT_DEG = 0.1          # print6Axis formats angles as %7.1f

def _quantize_quat(q):
    """Round-trip through the firmware's 0.1-degree euler print."""
    e = np.rad2deg(p.getEulerFromQuaternion(q))
    e = np.round(e / QUANT_DEG) * QUANT_DEG
    return np.asarray(p.getQuaternionFromEuler(np.deg2rad(e)))


class ImuView:
    """What the Pi would see from the serial stream for one variant."""

    def __init__(self, variant, phase):
        self.hold = variant.startswith("hold")
        self.rate = variant.split("_")[1]          # true | zero | fd
        self.phase = phase                         # tick offset of the first fresh sample
        self.q = None
        self.rp = None
        self.fd = np.zeros(3)

    def read(self, t, quat, angvel):
        fresh = (not self.hold) or self.q is None or (t - self.phase) % HOLD_STEPS == 0
        if fresh:
            q = _quantize_quat(quat) if self.hold else np.asarray(quat)
            rp = np.asarray(p.getEulerFromQuaternion(q)[:2])
            if self.rp is not None:
                self.fd = np.array([*(rp - self.rp) / (HOLD_STEPS / E_HZ), 0.0])
            self.q, self.rp = q, rp
        if self.rate == "true":
            w = np.asarray(angvel)
        elif self.rate == "fd":
            w = self.fd
        else:
            w = np.zeros(3)
        return self.q, w


E_HZ = 80.0


def run_episode(env, pol, variant, seed, steps, cmd):
    np.random.seed(seed)
    env.reset()
    env.set_command(fwd=cmd, yaw=0.0)
    pol.set_command(fwd=cmd, yaw=0.0)
    d0 = env._deploy_dbg
    j0 = np.asarray(p.getJointStates(env.robot_id, env.joint_id), dtype=object)[:, 0].astype(float)
    view = ImuView(variant, phase=int(np.random.randint(HOLD_STEPS)))
    q, w = view.read(0, d0["quat"], d0["angvel_raw"])
    pol.reset(j0, q, w)

    lo, hi = env.action_space.low, env.action_space.high
    x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
    tilt_max, fell, n = 0.0, False, 0
    for t in range(1, steps + 1):
        a = pol._sess.run(None, {pol._in_name: pol.obs[None, :]})[0][0]
        _, _, term, trunc, _ = env.step(np.clip(a, lo, hi))
        dbg = env._deploy_dbg
        q, w = view.read(t, dbg["quat"], dbg["angvel_raw"])
        pol.step(q, w)                              # same action as `a`; builds next obs from q, w
        rp = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])
        tilt_max = max(tilt_max, abs(rp[0]), abs(rp[1]))
        n = t
        if term:
            fell = True
            break
        if trunc:
            break
    dx = p.getBasePositionAndOrientation(env.robot_id)[0][0] - x0
    return dict(fell=fell, steps=n, dist=dx, speed=dx / (n / E_HZ), tilt_max_deg=np.rad2deg(tilt_max))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", default=os.path.join(HERE, "trained", "run20m_ppo.onnx"))
    ap.add_argument("--wkf", default=os.path.join(HERE, "reference_gait", "wkf_ref.npy"))
    ap.add_argument("--episodes", type=int, default=10)
    ap.add_argument("--steps", type=int, default=E.EPISODE_LENGTH,
                    help="control ticks per episode (80 Hz); default = training/decathlon length")
    ap.add_argument("--cmd", type=float, default=0.10)
    ap.add_argument("--cells", default="T1.1,T2.3,T3.1,T3.2,T4.2,T5.1,T6.1,T6.3,T6.4,T6.5,T7.2,T8.2",
                    help="benchmark_decathlon.py LADDER cell ids")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    import benchmark_decathlon as B
    from opencat_gym_env import OpenCatGymEnv
    cells = {c[0]: c for c in B.LADDER}
    E.ADAPTIVE_PUSH = False
    E.EPISODE_LENGTH = args.steps
    pol = ResidualGaitPolicy(onnx_path=args.onnx, wkf_path=args.wkf)

    results = {}
    print(f"{'cell':>6} {'variant':>11} {'falls':>6} {'speed m/s':>10} {'dist m':>7} {'tilt° p95':>10}")
    for cid in args.cells.split(","):
        knobs = {k: v for k, v in cells[cid][4].items() if not k.startswith("_")}
        B._apply(knobs)
        env = OpenCatGymEnv()
        for variant in args.variants.split(","):
            eps = [run_episode(env, pol, variant, 9000 + s, args.steps, args.cmd)
                   for s in range(args.episodes)]
            falls = sum(e["fell"] for e in eps)
            r = dict(falls=falls, episodes=len(eps),
                     speed=float(np.mean([e["speed"] for e in eps])),
                     dist=float(np.mean([e["dist"] for e in eps])),
                     tilt_p95=float(np.percentile([e["tilt_max_deg"] for e in eps], 95)),
                     episodes_detail=eps)
            results[f"{cid}/{variant}"] = r
            print(f"{cid:>6} {variant:>11} {falls:>3}/{len(eps):<2} {r['speed']:>10.3f} "
                  f"{r['dist']:>7.2f} {r['tilt_p95']:>10.1f}", flush=True)
        env.close()

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(results, f, indent=1, default=float)


if __name__ == "__main__":
    main()
