"""Servo-speed saturation check: what fraction of a trained policy's INTENDED
(pre-limiter) joint deltas would exceed a real servo's speed ceiling.

Built 2026-09-24 reviewing community Bittle/Petoi projects (see
docs/research/community-projects.md) -- a comparable project measured its
own Bittle X servos at ~137 deg/s; we've never measured G2's. This is a
mj_deployability.py-style check (same idea as that project's own tool):
reproduce the env's residual-mode target computation (ref + action *
RESIDUAL_SCALE_DEG) exactly as opencat_gym_env.py's step() computes
`joint_angs`, BEFORE SERVO_RATE_LIMIT_DEG_S is applied -- this measures what
the policy WANTS, not what physically happens. (SERVO_RATE_LIMIT_DEG_S,
added the same day, now enforces the ceiling for real in physics -- verified
separately: against base1_20m, actual physical joint motion after the fix
reads p95 136.8 deg/s, only 4.16% of physical steps over the ceiling, vs
this script's ~26% at the intent level. The gap between "intent" and
"physical outcome" IS the fix working.)

2026-09-24 result against base1_20m (assumed ceiling 137 deg/s, the only
number we have -- not G2's own, servo type/board revision changes it):
mean 98.9 deg/s, p95 261.2 deg/s, max 514.3 deg/s, 26.33% of joint-steps
over the assumed ceiling AT THE INTENT LEVEL. Real number pending G2's own
servo characterization (docs/rl/hardware-gated-backlog.md H13).

    python servo_saturation_check.py --policy trained/base1_20m_ppo --ceiling-deg-s 137
"""
import argparse

import numpy as np

import opencat_gym_env as E
E.GUI_MODE = False
import benchmark_decathlon as B
from benchmark_gaits import _load_learned
from opencat_gym_env import OpenCatGymEnv

CONTROL_HZ = 80.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--ceiling-deg-s", type=float, default=137.0,
                    help="assumed real servo speed ceiling (default: BittleJuice's measured Bittle X number)")
    ap.add_argument("--episodes", type=int, default=20)
    args = ap.parse_args()

    max_deg_per_step = args.ceiling_deg_s / CONTROL_HZ
    m = _load_learned(args.policy)
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    B._apply({})
    E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
    E.EPISODE_LENGTH = 300

    all_deltas_deg = []
    for s in range(args.episodes):
        np.random.seed(2000 + s)
        obs, _ = env.reset()
        prev_target = None
        for t in range(280):
            action, _ = m.predict(obs, deterministic=True)
            is_stand = abs(env._cmd_fwd) < E.STAND_FWD_THRESH
            ref = E.STAND_POSE if is_stand else env._ref_pose(int(env._phase))
            target = ref + action * np.deg2rad(E.RESIDUAL_SCALE_DEG)
            if prev_target is not None and t > 20:   # skip the initial settle
                all_deltas_deg.extend(np.degrees(np.abs(target - prev_target)).tolist())
            prev_target = target
            obs, _, _, _, info = env.step(action)
    env.close()

    d = np.array(all_deltas_deg)
    frac_over = (d > max_deg_per_step).mean()
    print(f"{args.policy}: assumed ceiling {args.ceiling_deg_s} deg/s @ {CONTROL_HZ}Hz "
          f"= {max_deg_per_step:.3f} deg/step budget")
    print(f"n samples: {len(d)}")
    print(f"mean {d.mean():.3f} deg/step ({d.mean()*CONTROL_HZ:.1f} deg/s)  "
          f"p95 {np.percentile(d, 95):.3f} ({np.percentile(d, 95)*CONTROL_HZ:.1f} deg/s)  "
          f"max {d.max():.3f} ({d.max()*CONTROL_HZ:.1f} deg/s)")
    print(f"fraction of joint-steps exceeding the ceiling: {frac_over*100:.2f}%")


if __name__ == "__main__":
    main()
