"""How much does a left/right stride difference turn a policy? (Pi-side heading hold design, 2026-10-06)

    ../../.venv/bin/python steer_probe.py trained/Release_CandidateV2.1_ppo [--episodes 8] [--u -0.2,-0.1,0,0.1,0.2]

The shoulder / hip swing of the LEFT legs (FL shoulder, BL hip) is scaled about the 50 deg stance by (1 - u) and the RIGHT legs (FR shoulder, BR hip) by (1 + u),
on the calibrated G2 profile (g2_profile.scoring_env), commanded 0.10 m/s for 12.5 s. Prints the mean heading change (sim: + = left, so a right turn is negative)
and the turn rate per unit u. Positive u = shorter left strides, so the robot should turn LEFT (+).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g2_profile

g2_profile.set_environ(g2_profile.scoring_env())
import numpy as np
import opencat_gym_env as E

E.GUI_MODE = False
import benchmark_decathlon as B

B._apply({})
E.EPISODE_LENGTH = 1000
from opencat_gym_env import OpenCatGymEnv
from stable_baselines3 import PPO
import pybullet as p

ap = argparse.ArgumentParser()
ap.add_argument("policy")
ap.add_argument("--episodes", type=int, default=8)
ap.add_argument("--u", default="-0.2,-0.1,0,0.1,0.2")
ap.add_argument("--closed-loop", action="store_true",
                help="run pi_pipeline/gait/heading_hold.HeadingHold in the loop (yaw converted to the Pi's right-positive convention): each --u is then a constant "
                     "DISTURBANCE added to the controller's output, and the result is compared with the same disturbance with no controller")
a = ap.parse_args()
if a.closed_loop:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "pi_pipeline", "gait"))
    import heading_hold as HH
model = PPO.load(a.policy)
env = OpenCatGymEnv()
env.set_command(fwd=0.10, yaw=0.0)
res = {}
for u in [float(x) for x in a.u.split(",")]:
    heads, falls = [], 0
    for ep in range(a.episodes):
        np.random.seed(1000 + ep)
        obs, _ = env.reset(seed=1000 + ep)
        sc = np.ones(8)
        sc[0] = sc[6] = 1.0 - u          # left shoulder / hip
        sc[2] = sc[4] = 1.0 + u          # right shoulder / hip
        env._stroke_scale = sc
        y0 = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])[2]
        yaws, tmax = [], 0.0
        hold = HH.HeadingHold() if a.closed_loop else None
        u_dist, step_k = u, 0
        while True:
            if hold is not None:                      # disturbance u_dist + the controller's correction (right-positive heading = -sim yaw)
                yaw_pi = -(p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])[2] - y0)
                uc = hold.update(yaw_pi, 1.0 / 80.0)
                tot = u_dist + uc
                sc = np.ones(8); sc[0] = sc[6] = 1.0 - tot; sc[2] = sc[4] = 1.0 + tot
                env._stroke_scale = sc
            act, _ = model.predict(obs, deterministic=True)
            obs, r, te, tr, _i = env.step(act)
            q = p.getBasePositionAndOrientation(env.robot_id)[1]
            r_, p_, y_ = p.getEulerFromQuaternion(q)
            yaws.append(y_)
            tmax = max(tmax, abs(r_), abs(p_))
            if te or tr:
                break
        falls += tmax > 1.3
        heads.append(np.degrees(np.unwrap(np.array(yaws))[-1] - y0))
    res[u] = (float(np.mean(heads)), float(np.std(heads)), falls)
    print(f"u {u:+.2f}: heading change {res[u][0]:+7.1f} +- {res[u][1]:4.1f} deg over 12.5 s ({res[u][0] / 12.5:+.2f} deg/s), falls {falls}/{a.episodes}", flush=True)
us = np.array(list(res)); hs = np.array([res[u][0] for u in res])
slope = np.polyfit(us, hs, 1)[0]
print(f"turn per unit u: {slope:+.0f} deg per 12.5 s, i.e. {slope / 12.5:+.1f} deg/s per 1.0 of u ({slope / 12.5 * 0.1:+.2f} deg/s per 10% stride difference)")
