"""Commanded-locomotion eval: stand, backward, speed-tracking, yaw-tracking,
heading-hold. Complements the Decathlon (which only measures cruise-forward).

    python benchmark_commanded.py --learned trained/<tag>_ppo [--episodes 20] [--json-out f.json]
"""
import argparse
import json

import numpy as np
import pybullet as p

import opencat_gym_env
from opencat_gym_env import OpenCatGymEnv, CONTROL_HZ
from stable_baselines3 import PPO


def rollout(env, model, fwd, yaw, episodes, seed0, push=0.0):
    opencat_gym_env.IMPULSE_PUSH = push
    opencat_gym_env.IMPULSE_PUSH_PROB = 0.006 if push else 0.0
    env.set_command(fwd=fwd, yaw=yaw)
    vfwd, yrate, dhead, dlat, fell, held = [], [], [], [], 0, []
    for e in range(episodes):
        np.random.seed(seed0 + e)
        obs, _ = env.reset()
        env.set_command(fwd=fwd, yaw=yaw)
        p0, q0 = p.getBasePositionAndOrientation(env.robot_id)
        y0 = p.getEulerFromQuaternion(q0)[2]
        vfs, yrs, steps = [], [], 0
        term = trunc = False
        while not (term or trunc):
            a, _ = model.predict(obs, deterministic=True)
            obs, _, term, trunc, info = env.step(a)
            vfs.append(info["v_fwd_mps"])
            yrs.append(p.getBaseVelocity(env.robot_id)[1][2])
            steps += 1
        p1, q1 = p.getBasePositionAndOrientation(env.robot_id)
        y1 = p.getEulerFromQuaternion(q1)[2]
        vfwd.append(np.mean(vfs[-60:]) if vfs else 0.0)
        yrate.append(np.mean(yrs[-60:]) if yrs else 0.0)
        cmd_head = yaw * (steps / CONTROL_HZ)
        dhead.append(((y1 - y0) - cmd_head + np.pi) % (2 * np.pi) - np.pi)
        dlat.append(p1[1] - p0[1])
        fell += int(term)
        held.append(steps)
    opencat_gym_env.IMPULSE_PUSH = 0.0
    return dict(
        v_fwd=float(np.mean(vfwd)), v_fwd_err=float(np.mean(np.abs(np.array(vfwd) - fwd))),
        yaw_rate=float(np.mean(yrate)), yaw_err=float(np.mean(np.abs(np.array(yrate) - yaw))),
        heading_err_deg=float(np.degrees(np.mean(np.abs(dhead)))),
        lat_drift_m=float(np.mean(np.abs(dlat))),
        fell=fell, episodes=episodes, mean_len=float(np.mean(held)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned", required=True)
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--seed", type=int, default=5000)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    opencat_gym_env.ADAPTIVE_PUSH = False
    for k in ("SLOPE_MAX_DEG", "START_POSE_JITTER", "STUCK_FOOT_PROB", "SUSTAINED_FORCE",
              "DEFORM_GROUND", "SLIP_PATCH", "RANDOM_TERRAIN", "RANDOM_PUSH",
              "ROUGH_TERRAIN", "PHASE_RAND"):
        if hasattr(opencat_gym_env, k):
            setattr(opencat_gym_env, k, 0.0)
    if hasattr(opencat_gym_env, "SLOPE_FIXED_RP"):
        opencat_gym_env.SLOPE_FIXED_RP = (0.0, 0.0)
    opencat_gym_env.DR_EVAL_FULL = True
    env = OpenCatGymEnv()
    model = PPO.load(args.learned)

    tests = [
        ("stand-hold",       0.00,  0.00, 0.0),
        ("stand + shoves",   0.00,  0.00, 0.55),
        ("creep",            0.04,  0.00, 0.0),
        ("cruise",           0.10,  0.00, 0.0),
        ("fast",             0.13,  0.00, 0.0),
        ("backward",        -0.06,  0.00, 0.0),
        ("turn left",        0.08,  0.30, 0.0),
        ("turn right",       0.08, -0.30, 0.0),
        ("tight turn",       0.05,  0.45, 0.0),
    ]
    out = {"learned": args.learned, "episodes": args.episodes, "tests": {}}
    hdr = f"{'test':<16}{'cmd f/yaw':>12}{'v_fwd':>8}{'v_err':>7}{'yaw':>7}{'yaw_err':>8}{'head_err':>9}{'lat_m':>7}{'fell':>6}"
    print(hdr); print("-" * len(hdr))
    for name, f, y, push in tests:
        r = rollout(env, model, f, y, args.episodes, args.seed, push)
        out["tests"][name] = r
        print(f"{name:<16}{f:+.2f}/{y:+.2f}   {r['v_fwd']:+.3f} {r['v_fwd_err']:.3f} "
              f"{r['yaw_rate']:+.2f} {r['yaw_err']:.3f}  {r['heading_err_deg']:6.1f}  "
              f"{r['lat_drift_m']:.3f} {r['fell']:>3}/{r['episodes']}")
    env.close()

    # plain-language verdicts
    print("\nverdicts:")
    st = out["tests"]["stand-hold"]
    print(f"  stand      : {'holds' if st['fell']==0 and st['lat_drift_m']<0.06 else 'WEAK'} "
          f"({st['fell']} falls, {st['lat_drift_m']:.3f} m drift)")
    bw = out["tests"]["backward"]
    print(f"  backward   : {'OK' if bw['v_fwd']<-0.02 and bw['fell']<=args.episodes*0.2 else 'WEAK'} "
          f"(v_fwd {bw['v_fwd']:+.3f}, {bw['fell']} falls)")
    cr = out["tests"]["cruise"]
    print(f"  heading    : {'holds straight' if cr['heading_err_deg']<8 else 'DRIFTS'} "
          f"({cr['heading_err_deg']:.1f} deg over an episode)")
    trk = np.mean([out['tests'][n]['v_fwd_err'] for n in ('creep','cruise','fast')])
    print(f"  speed track: mean |err| {trk:.3f} m/s  {'good' if trk<0.02 else 'loose'}")
    yt = np.mean([out['tests'][n]['yaw_err'] for n in ('turn left','turn right','tight turn')])
    print(f"  yaw track  : mean |err| {yt:.2f} rad/s  {'good' if yt<0.12 else 'loose'}")
    ss = out["tests"]["stand + shoves"]
    print(f"  stand+shove: {ss['fell']}/{ss['episodes']} falls under repeated shoves")

    if args.json_out:
        with open(args.json_out, "w") as fh:
            json.dump(out, fh, indent=2)
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
