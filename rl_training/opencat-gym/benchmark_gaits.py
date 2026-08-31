"""Head-to-head: the learned RL gait vs. Bittle's canned scripted gait, on the
same obstacle course.

Both gaits run *inside the training env*, so they face identical obstacle
layouts, pushes, and physics -- and with matched per-episode RNG seeds, episode
N is the exact same course for both. Metrics come from evaluate_policy.py so they
line up with everything else in the project.

The "scripted" gait is Bittle's built-in `wkF` walk keyframes
(reference_gait/wkf_ref.npy) played as a controller: each step it steers the
joints toward the current keyframe. Optionally a crude proportional tilt
correction (`--scripted-balance K`) approximates the firmware's gyro-balance
layer -- without it this is pure open-loop and a *floor* for the real scripted
gait's performance. The definitive comparison is on hardware.

Usage:
  python benchmark_gaits.py                               # walk_r2 vs scripted, difficulty sweep
  python benchmark_gaits.py --learned trained/walk_r2_ppo --episodes 20
  python benchmark_gaits.py --scripted-balance 0.6        # give the scripted gait balance assist
  python benchmark_gaits.py --gif                         # also render one course per gait
"""
import argparse
import json
import os

import numpy as np
import pybullet as p

import opencat_gym_env
opencat_gym_env.GUI_MODE = False
from opencat_gym_env import OpenCatGymEnv, BOUND_ANG, STEP_ANGLE, WKF_REF

from evaluate_policy import run_episode, summarize

_BOUND = np.deg2rad(BOUND_ANG)
_DS = np.deg2rad(STEP_ANGLE)


class ScriptedGait:
    """SB3-`predict`-compatible controller that tracks the wkF keyframes."""

    def __init__(self, env, balance_k: float = 0.0):
        self._env = env
        self._k = balance_k
        self._phase = 0
        if WKF_REF is None:
            raise SystemExit("reference_gait/wkf_ref.npy missing -- run build_wkf_reference.py")

    def reset(self):
        self._phase = 0

    def predict(self, obs, deterministic=True):  # noqa: ARG002
        rid = self._env.robot_id
        cur = np.array([p.getJointState(rid, j)[0] for j in self._env.joint_id])
        target = np.clip(WKF_REF[self._phase % len(WKF_REF)], -_BOUND, _BOUND).astype(float)

        if self._k:
            roll, pitch, _ = p.getEulerFromQuaternion(
                p.getBasePositionAndOrientation(rid)[1])
            # URDF joints [FLs,FLk,FRs,FRk,BRs,BRk,BLs,BLk]: nudge fronts down /
            # rears up against pitch, left/right against roll.
            corr = np.array([-pitch, -pitch, -pitch, -pitch, pitch, pitch, pitch, pitch]) \
                 + np.array([-roll, -roll, roll, roll, roll, roll, -roll, -roll])
            target = np.clip(target + self._k * corr, -_BOUND, _BOUND)

        self._phase += 1
        return np.clip((target - cur) / _DS, -1.0, 1.0), None


def _load_learned(path):
    from stable_baselines3 import PPO
    return PPO.load(path)


def _bench(env, model, episodes, seed0):
    eps = []
    for e in range(episodes):
        np.random.seed(seed0 + e)          # episode e = same course for every gait
        if hasattr(model, "reset"):
            model.reset()
        eps.append(run_episode(env, model))
    return summarize(eps)


_KEYS = ["fell_fraction", "forward_distance_m_mean", "forward_speed_mps_mean",
         "episode_len_mean", "diagonal_trot_corr_mean", "roll_var_mean",
         "yaw_abs_max_deg_mean", "med_stumble_recovery_rate", "big_stumble_recovery_rate"]


def _row(name, s):
    def g(k):
        v = s.get(k)
        return "  -  " if v is None else f"{v:6.3f}" if isinstance(v, float) else f"{v}"
    return f"{name:<10} " + " ".join(g(k) for k in _KEYS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned", default="trained/walk_r2_ppo")
    ap.add_argument("--episodes", type=int, default=16)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--scripted-balance", type=float, default=0.0)
    ap.add_argument("--gif", action="store_true")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    # difficulty sweep: (label, terrain m, push m/s)
    course = [
        ("flat",     0.0,   0.0),
        ("obst-20",  0.020, 0.15),
        ("obst-35",  0.035, 0.25),
        ("obst-50",  0.050, 0.35),
    ]

    env = OpenCatGymEnv()
    learned = _load_learned(args.learned)
    scripted = ScriptedGait(env, balance_k=args.scripted_balance)

    results = {}
    for label, terr, push in course:
        for k in ("RANDOM_FRICTION", "RANDOM_MASS", "RANDOM_GYRO", "RANDOM_PUSH", "RANDOM_TERRAIN"):
            setattr(opencat_gym_env, k, 0.0)
        opencat_gym_env.RANDOM_TERRAIN = terr
        opencat_gym_env.RANDOM_PUSH = push
        opencat_gym_env.RANDOM_PUSH_PROB = 0.03
        opencat_gym_env.DR_EVAL_FULL = True

        print(f"\n=== {label}  (terrain {terr} m, push {push} m/s) ===")
        print(f"{'gait':<10} " + " ".join(f"{k.split('_')[0][:6]:>6}" for k in _KEYS))
        rl = _bench(env, learned, args.episodes, args.seed)
        sc = _bench(env, scripted, args.episodes, args.seed)
        print(_row("learned", rl))
        print(_row("scripted", sc))
        results[label] = {"learned": rl, "scripted": sc, "terrain": terr, "push": push}

        if args.gif and label == "obst-35":
            _render(env, learned, "benchmark_learned.gif")
            _render(env, scripted, "benchmark_scripted.gif")

    env.close()
    _verdict(results)
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(results, f, indent=2)


def _render(env, model, out):
    from PIL import Image
    obs, _ = env.reset()
    if hasattr(model, "reset"):
        model.reset()
    frames = []
    for t in range(250):
        a, _ = model.predict(obs, deterministic=True)
        obs, _, term, trunc, _ = env.step(a)
        if t % 3 == 0:
            pos = p.getBasePositionAndOrientation(env.robot_id)[0]
            _, _, rgb, _, _ = p.getCameraImage(
                420, 300,
                viewMatrix=p.computeViewMatrixFromYawPitchRoll(
                    [pos[0], pos[1], 0.05], 0.55, 50, -28, 0, 2),
                projectionMatrix=p.computeProjectionMatrixFOV(60, 1.4, 0.1, 5),
                renderer=p.ER_TINY_RENDERER)
            frames.append(np.reshape(rgb, (300, 420, 4))[:, :, :3].astype(np.uint8))
        if term or trunc:
            break
    Image.fromarray(frames[0]).save(out, save_all=True,
        append_images=[Image.fromarray(f) for f in frames[1:]], duration=45, loop=0)
    print(f"  wrote {out} ({len(frames)} frames)")


def _verdict(results):
    print("\n" + "=" * 70 + "\nVERDICT\n" + "=" * 70)
    for label, r in results.items():
        rl, sc = r["learned"], r["scripted"]
        d_fall = sc["fell_fraction"] - rl["fell_fraction"]
        d_dist = rl["forward_distance_m_mean"] - sc["forward_distance_m_mean"]
        winner = "learned" if (d_fall > 0.05 or (abs(d_fall) <= 0.05 and d_dist > 0.02)) \
                 else "scripted" if (d_fall < -0.05 or d_dist < -0.02) else "~tie"
        print(f"  {label:<9} winner: {winner:<9} "
              f"(scripted falls {sc['fell_fraction']:.0%} vs learned {rl['fell_fraction']:.0%}; "
              f"dist {sc['forward_distance_m_mean']:.2f} vs {rl['forward_distance_m_mean']:.2f} m; "
              f"roll_var {sc['roll_var_mean']:.3f} vs {rl['roll_var_mean']:.3f})")
    print("\nWhy to look for: on obstacles the learned policy reads body tilt each")
    print("step and adjusts, so it trips less and its roll/pitch variance stays")
    print("lower under disturbance; the scripted gait cycles regardless. On flat")
    print("ground the scripted gait may match or beat it on raw speed.")
    print("\nCaveat: the scripted gait here is open-loop keyframes"
          + ("" if True else "") + " (+ balance assist if --scripted-balance);")
    print("the real firmware wkF adds a tuned gyro-balance layer, so real-hardware")
    print("scripted performance is >= this. Confirm on the robot.")


if __name__ == "__main__":
    main()
