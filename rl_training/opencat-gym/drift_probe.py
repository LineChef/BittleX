"""How far does a policy drift off a straight line, and how steady is it, with the sim set up like the real G2?

    G2E_PAYLOAD_PROFILE=case G2E_DRIFT_SHOULDER_DEG=8 python drift_probe.py trained/Release_CandidateV2.1_ppo --episodes 12

Runs flat ground, no pushes, commanded straight at 0.10 m/s for 12.5 s per episode (same settings as the real baseline walks). Prints JSON: the heading change
over the episode in degrees (+ = left in the sim, so a real right-hand drift is negative here), its mean and spread, mean |heading change|, yaw-rate rms, roll std,
pitch std, and the fall count. Needs the same G2E_* control-path settings the policy was trained with (run_pipeline.BASE).
"""
import argparse
import json
import os
import sys

BASE_ENV = dict(G2E_IMU_HOLD_STEPS="16", G2E_IMU_RATE_ZERO="1", G2E_CMD_PATH="i", G2E_CMD_PATH_EXTRA_MS_MAX="4", G2E_BODY_MASS_SCALE="1.12",
                G2E_IMU_BIAS_DEG="2", G2E_JOINT_OFFSET_DEG="2", G2E_SERVO_RATE_LIMIT_DEG_S="137", G2E_CMD_SEND_EVERY_N="3",
                G2E_FAC_YAW_TRACK="9.0", G2E_EPISODE_LENGTH="1000")
for k, v in BASE_ENV.items():
    os.environ.setdefault(k, v)

import numpy as np
import pybullet as p

import opencat_gym_env
opencat_gym_env.GUI_MODE = False
# "flat, calm, payload on" like the decathlon's payload mode: full domain randomization of the robot (mass, offsets, IMU) but no pushes, rough ground or torque cutback
opencat_gym_env.DR_EVAL_FULL = True
opencat_gym_env.PAYLOAD_PROB = 1.0
for _k, _v in (("ROUGH_TERRAIN", 0.0), ("TORQUE_CUTBACK", 0.0), ("RANDOM_PUSH", 0.0), ("RANDOM_TERRAIN_PROB", 0.0), ("RANDOM_FRICTION", 0.0)):
    if hasattr(opencat_gym_env, _k):
        setattr(opencat_gym_env, _k, _v)
from opencat_gym_env import OpenCatGymEnv
from stable_baselines3 import PPO


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("policy")
    ap.add_argument("--episodes", type=int, default=12)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--lever", default="", help="a fixed asymmetry for EVERY episode, ';'-separated: offset:J:DEG (servo zero), stroke:J:SCALE (swing amplitude "
                    "of shoulder/hip J), torque:J:SCALE (motor force of joint J), fric:L:SCALE (lateral friction of foot link L), yawtorque:NM (constant "
                    "yaw torque on the body), payy:M (payload sideways shift, metres). Joints: 0 FLsh 1 FLel 2 FRsh 3 FRel 4 BRhip 5 BRkn 6 BLhip 7 BLkn")
    a = ap.parse_args()
    levers = [x.split(":") for x in a.lever.split(";") if x]
    np.random.seed(a.seed)
    model = PPO.load(a.policy)
    env = OpenCatGymEnv()
    out = dict(heading_deg=[], yaw_rate_rms=[], roll_std=[], pitch_std=[], fell=0, steps=[])
    for ep in range(a.episodes):
        obs, _ = env.reset(seed=a.seed + ep)
        env._cmd_fwd, env._cmd_yaw = 0.10, 0.0            # straight at the walked speed
        yaw_torque = 0.0
        for lv in levers:
            kind = lv[0]
            if kind == "offset":
                env._joint_offset[int(lv[1])] += np.deg2rad(float(lv[2]))
            elif kind == "stroke":
                env._stroke_scale = np.ones(8) if env._stroke_scale is None else env._stroke_scale
                env._stroke_scale[int(lv[1])] = float(lv[2])
            elif kind == "torque":
                env._torque_scale[int(lv[1])] = float(lv[2])
            elif kind == "fric":
                p.changeDynamics(env.robot_id, int(lv[1]), lateralFriction=float(lv[2]))
            elif kind == "yawtorque":
                yaw_torque = float(lv[1])
            elif kind == "payy":
                if env._payload_id is not None:
                    for c in range(p.getNumConstraints()):
                        pass
        p0, o0 = p.getBasePositionAndOrientation(env.robot_id)
        yaw0 = p.getEulerFromQuaternion(o0)[2]
        yaws, rolls, pitches, rates = [], [], [], []
        n = 0
        while True:
            act, _ = model.predict(obs, deterministic=True)
            if yaw_torque:
                p.applyExternalTorque(env.robot_id, -1, [0, 0, yaw_torque], p.LINK_FRAME)
            obs, r, term, trunc, info = env.step(act)
            n += 1
            _, o = p.getBasePositionAndOrientation(env.robot_id)
            rl, pt, yw = p.getEulerFromQuaternion(o)
            yaws.append(yw); rolls.append(rl); pitches.append(pt)
            rates.append(p.getBaseVelocity(env.robot_id)[1][2])
            if term or trunc or n >= 1000:
                break
        if term and (max(abs(np.array(rolls))) > 0.9 or max(abs(np.array(pitches))) > 0.9):
            out["fell"] += 1
        dyaw = np.degrees(np.unwrap(np.array(yaws))[-1] - yaw0)
        out["heading_deg"].append(round(float(dyaw), 1))
        out["yaw_rate_rms"].append(round(float(np.sqrt(np.mean(np.square(rates)))), 4))
        out["roll_std"].append(round(float(np.degrees(np.std(rolls))), 2))
        out["pitch_std"].append(round(float(np.degrees(np.std(pitches))), 2))
        out["steps"].append(n)
        pe, _ = p.getBasePositionAndOrientation(env.robot_id)
        out.setdefault("speed", []).append(round(float((pe[0] - p0[0]) / (n / opencat_gym_env.CONTROL_HZ)), 4))
    h = np.array(out["heading_deg"])
    summ = dict(policy=os.path.basename(a.policy), episodes=a.episodes, falls=out["fell"],
                heading_mean_deg=round(float(h.mean()), 1), heading_std_deg=round(float(h.std()), 1), heading_abs_mean_deg=round(float(np.abs(h).mean()), 1),
                yaw_rate_rms=round(float(np.mean(out["yaw_rate_rms"])), 4), roll_std_deg=round(float(np.mean(out["roll_std"])), 2),
                pitch_std_deg=round(float(np.mean(out["pitch_std"])), 2), mean_steps=int(np.mean(out["steps"])), speed_mps=round(float(np.mean(out["speed"])), 4),
                lever=a.lever, env=dict(payload=os.environ.get("G2E_PAYLOAD_PROFILE", "estimate"), drift_deg=os.environ.get("G2E_DRIFT_SHOULDER_DEG", "0")),
                per_episode_heading_deg=out["heading_deg"])
    print(json.dumps(summ))


if __name__ == "__main__":
    main()
