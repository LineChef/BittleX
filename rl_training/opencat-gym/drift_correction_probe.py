"""Does a policy actively correct a steady yaw push? (user's question, 2026-10-07: "I can't even tell if it ever learns to actually correct its command drift")

    python drift_correction_probe.py --policy scripted
    python drift_correction_probe.py --policy trained/v3_r_s12_s43_ppo --levers heading_obs [--episodes 6] [--seconds 12.5] [--torques -0.3,-0.2,-0.1,0,0.1,0.2,0.3]

A policy walks straight ahead (command: forward 0.10 m/s, no turn) in the calibrated scoring world while a CONSTANT yaw torque pushes the body (the env's drift fault, applied to every episode at a fixed value instead of a random one).
Prints one JSON line per torque with the heading change in degrees (sim sign: + = left) at 4 s, 8 s and the end, the yaw rate over the last 3 s (near 0 = the heading has settled, i.e. the push is being cancelled; steady and nonzero = the heading is still running away),
the peak heading error, the number of times the heading crossed zero by more than 5 degrees (over-correction), and the fall fraction. `scripted` is the open-loop firmware gait with no policy: the baseline a correcting policy must beat.
Compare the two signs of the push: a policy that only learned one direction shows it here.
"""
import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import g2_profile

ap = argparse.ArgumentParser()
ap.add_argument("--policy", required=True, help="trained/<tag>_ppo (no .zip) or 'scripted'")
ap.add_argument("--levers", default="", help="observation levers the policy was trained with, e.g. heading_obs")
ap.add_argument("--episodes", type=int, default=6)
ap.add_argument("--seconds", type=float, default=12.5)
ap.add_argument("--torques", default="-0.3,-0.2,-0.1,0,0.1,0.2,0.3")
ap.add_argument("--fwd", type=float, default=0.10)
ap.add_argument("--seed", type=int, default=5000)
a = ap.parse_args()

for k in [k for k in os.environ if k.startswith("G2E_")]:
    del os.environ[k]
levers = [x for x in a.levers.split(",") if x]
g2_profile.set_environ(g2_profile.scoring_env(*levers))
os.environ["G2E_EPISODE_LENGTH"] = str(int(a.seconds * 80))      # the env's default episode is 250 steps (3 s); the benchmark cells set it per cell
import opencat_gym_env as E            # noqa: E402  (reads G2E_* at import)
import pybullet as pb                  # noqa: E402

E.GUI_MODE = False
import benchmark_decathlon as B         # noqa: E402
B._apply({})                            # the benchmark's calm flat floor (T1.1): no random shoves, slopes or terrain, so only the push moves the heading
E.EPISODE_LENGTH = int(a.seconds * 80)
env = E.OpenCatGymEnv()
env.set_ramp_steps(1e12)
if a.policy == "scripted":
    from benchmark_gaits import ScriptedGait
    E.CMD_SEND_EVERY_N = 1
    model = ScriptedGait(env)
else:
    from benchmark_gaits import _load_learned
    model = _load_learned(a.policy)
HZ = 80.0
for tq in [float(x) for x in a.torques.split(",")]:
    fins, h4, h8, rates, peaks, crossings, falls = [], [], [], [], [], [], []
    for k in range(a.episodes):
        if hasattr(model, "reset"):
            model.reset()
        obs, _ = env.reset(seed=a.seed + k)
        env.set_command(fwd=a.fwd, yaw=0.0)
        env._drift_torque = tq                                  # a fixed push for this episode
        yaw0 = pb.getEulerFromQuaternion(pb.getBasePositionAndOrientation(env.robot_id)[1])[2]
        yaws, peak_tilt, n = [], 0.0, 0
        while True:
            act, _ = model.predict(obs, deterministic=True)
            obs, _r, te, tr, _i = env.step(act)
            n += 1
            r_, p_, y_ = pb.getEulerFromQuaternion(pb.getBasePositionAndOrientation(env.robot_id)[1])
            yaws.append(y_)
            peak_tilt = max(peak_tilt, abs(r_), abs(p_))
            if te or tr or n >= int(a.seconds * HZ):
                break
        u = np.degrees(np.unwrap(np.array(yaws) - yaw0))
        t = np.arange(len(u)) / HZ
        falls.append(peak_tilt > 1.3)
        if falls[-1] or len(u) < 3 * HZ:
            continue
        at = lambda s: float(np.interp(min(s, t[-1]), t, u))   # noqa: E731
        fins.append(u[-1]); h4.append(at(4.0)); h8.append(at(8.0))
        last = t >= t[-1] - 3.0
        rates.append(float(np.polyfit(t[last], u[last], 1)[0]))
        peaks.append(float(np.max(np.abs(u))))
        s = np.sign(u[np.abs(u) > 5.0])
        crossings.append(int((np.diff(s) != 0).sum()) if len(s) > 1 else 0)
    m = lambda x: round(float(np.mean(x)), 1) if x else None   # noqa: E731
    print(json.dumps({"policy": a.policy, "torque": tq, "episodes_ok": len(fins), "fell": round(float(np.mean(falls)), 2), "heading_4s": m(h4), "heading_8s": m(h8), "heading_end": m(fins),
                      "yaw_rate_last_3s": m(rates), "peak_abs_heading": m(peaks), "zero_crossings": m(crossings)}), flush=True)
