"""Time the REAL run20m_ppo policy on this machine, end to end -- ONNX inference
plus the full 278-d observation build (ResidualGaitPolicy.step), the thing the
80 Hz control loop actually does per tick.

On the Pi, run it in a venv that has onnxruntime + numpy:

    ~/g2/.venv/bin/python -m pi_pipeline.gait.bench_real
    # or:  python pi_pipeline/gait/bench_real.py --n 4000

Compare against the synthetic [276-256-256-8] stub from pi_setup.sh (~0.43 ms on
a Zero 2 W). The real number should be close -- a touch higher for the obs-build
(numpy concat + a couple of trig calls) and the exact 278-wide first layer.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from residual_policy import ResidualGaitPolicy, CONTROL_HZ   # noqa: E402


def _fake_imu(rng, tilt=0.05):
    """A plausible mid-walk IMU sample: near-level, small body rates."""
    roll, pitch, yaw = rng.normal(0, tilt, 3)
    cr, sr = np.cos(roll / 2), np.sin(roll / 2)
    cp, sp = np.cos(pitch / 2), np.sin(pitch / 2)
    cy, sy = np.cos(yaw / 2), np.sin(yaw / 2)
    q = np.array([sr * cp * cy - cr * sp * sy,
                  cr * sp * cy + sr * cp * sy,
                  cr * cp * sy - sr * sp * cy,
                  cr * cp * cy + sr * sp * sy])
    gyro = rng.normal(0, 0.3, 3)
    return q, gyro


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", default=None)
    ap.add_argument("--wkf", default=None)
    ap.add_argument("--n", type=int, default=3000, help="timed steps")
    ap.add_argument("--warmup", type=int, default=200)
    ap.add_argument("--cmd", type=float, default=0.10)
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args()

    rng = np.random.default_rng(0)
    pol = ResidualGaitPolicy(onnx_path=args.onnx, wkf_path=args.wkf, intra_op_threads=args.threads)
    pol.set_command(fwd=args.cmd, yaw=0.0)
    q0, g0 = _fake_imu(rng)
    pol.reset(np.deg2rad([50, 0, 50, 0, 50, 0, 50, 0]), q0, g0)

    for _ in range(args.warmup):
        q, g = _fake_imu(rng)
        pol.step(q, g)

    lat = np.empty(args.n)
    for i in range(args.n):
        q, g = _fake_imu(rng)
        t0 = time.perf_counter()
        pol.step(q, g)
        lat[i] = time.perf_counter() - t0
    ms = lat * 1e3

    budget = 1000.0 / CONTROL_HZ
    print(f"ResidualGaitPolicy.step  (real run20m_ppo, {args.threads} threads, n={args.n})")
    print(f"  mean   {ms.mean():.3f} ms")
    print(f"  median {np.median(ms):.3f} ms")
    print(f"  p95    {np.percentile(ms, 95):.3f} ms")
    print(f"  max    {ms.max():.3f} ms")
    print(f"  {CONTROL_HZ:.0f} Hz budget = {budget:.2f} ms  ->  "
          + (f"OK, {100 * ms.mean() / budget:.0f}% of budget"
             if ms.mean() < budget else "TOO SLOW"))
    print(f"  headroom: ~{budget / ms.mean():.0f}x")


if __name__ == "__main__":
    main()
