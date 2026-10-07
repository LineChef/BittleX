"""Yaw against time for the firmware turn gaits in the calibrated sim (open-loop, zero residual), to compare with the real turn runs (docs/rl/real-walk-log.md).

    G2E_LONG_EP_PROB=1 G2E_LONG_EP_LEN=4800 python turn_gate_curve.py 60 3        # seconds per episode, episodes per direction

The sim's own episode limit is 12.5 s; `G2E_LONG_EP_PROB=1` with `G2E_LONG_EP_LEN` (steps at 80 Hz) lifts it. Prints, per episode, the yaw in degrees (firmware convention, + = right) at 5, 10, 15, 20, 30, 45 and 60 s.
"""
import sys, os, json, time
sys.path.insert(0, os.getcwd())
import turn_gate_probe as T          # sets the calibrated profile and the turn blend, same as the gate probe
import numpy as np
import pybullet as p
E = T.E
seconds, episodes = float(sys.argv[1]), int(sys.argv[2])
env = E.OpenCatGymEnv()
t0 = time.time()
for name, yc in (("wkL", E.CMD_YAW_MAX), ("wkR", -E.CMD_YAW_MAX)):
    for ep in range(episodes):
        env.reset(seed=1234 + ep)
        env.set_command(fwd=E.PHASE_RATE_NOM_CMD, yaw=yc)
        yaws, n = [], 0
        while True:
            _, _, term, trunc, _ = env.step(np.zeros(8))
            n += 1
            yaws.append(p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])[2])
            if term or trunc or n >= int(seconds * E.CONTROL_HZ):
                break
        u = -np.degrees(np.unwrap(np.array(yaws)))          # firmware convention: + = right turn
        u = u - u[0]
        marks = [5, 10, 15, 20, 30, 45, 60]
        at = {m: round(float(u[min(int(m * E.CONTROL_HZ), len(u) - 1)]), 1) for m in marks if m <= seconds}
        print(json.dumps({"skill": name, "episode": ep, "seconds_simulated": round(len(u) / E.CONTROL_HZ, 1), "yaw_deg_at_s": at, "ended_early": bool(term or trunc)}), flush=True)
print(json.dumps({"wall_seconds": round(time.time() - t0, 1)}), flush=True)
