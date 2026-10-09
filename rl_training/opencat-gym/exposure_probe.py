"""How much real hazard contact a policy's training gave it (2026-10-09, user: every earlier policy trained in 3.1 s episodes, so its exposure to hazards was limited and the V3 vs V4
comparison has to say so). Run in the policy's OWN training environment (watch_env.py settings), deterministic actions:

    G2E_...=... ../../.venv/bin/python exposure_probe.py POLICY TAG RAMP_STEPS [EPISODES]     # prints one JSON line

For each training-style episode: how long it ran, how far G2 walked, and how it stood to the solid objects in the way (their nearest and farthest x, from the physics bodies):
never reached the first object / reached it / got past the FIRST object / got past the whole field. Hazard-focus episodes are reported separately."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import opencat_gym_env as E

E.GUI_MODE = False
import pybullet as p  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402


def main(policy, tag, ramp, n):
    env = E.OpenCatGymEnv()
    env.set_ramp_steps(ramp)
    fr = f"trained/{tag}_frontier.json"
    if E.FRONTIER and os.path.exists(fr):
        st = json.load(open(fr))
        env.set_frontier({"w": st["weights"], "comfort": {h: max(0, int(f) - 1) for h, f in st["F"].items()}})
    model = PPO.load(policy)
    np.random.seed(11)
    rows = []
    for _ in range(n):
        obs, _ = env.reset()
        focus = getattr(env, "_fr_focus", None) is not None
        skip = {0, env.robot_id, getattr(env, "_payload_id", -1), getattr(env, "_head_id", -1)}
        objs = []
        for b in range(p.getNumBodies()):
            bid = p.getBodyUniqueId(b)
            if bid in skip:
                continue
            lo, hi = p.getAABB(bid)
            if hi[2] - lo[2] >= 0.002 and lo[0] >= -0.05:
                objs.append((lo[0], hi[0]))
        x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        steps, fell = 0, False
        for _t in range(900):
            a, _ = model.predict(obs, deterministic=True)
            obs, _r, te, tr, _i = env.step(a)
            steps += 1
            _, orn = p.getBasePositionAndOrientation(env.robot_id)
            rr, pp, _ = p.getEulerFromQuaternion(orn)
            if max(abs(rr), abs(pp)) > 1.3:
                fell = True
                break
            if te or tr:
                break
        d = p.getBasePositionAndOrientation(env.robot_id)[0][0] - x0
        rows.append(dict(focus=focus, steps=steps, dist=d, fell=fell, objs=sorted(objs)))

    def stats(rs):
        withobj = [r for r in rs if r["objs"]]
        if not rs:
            return {}
        first = [r for r in withobj if r["dist"] >= r["objs"][0][1]]
        whole = [r for r in withobj if r["dist"] >= max(o[1] for o in r["objs"])]
        near = [r for r in withobj if r["dist"] < r["objs"][0][0] - 0.02]
        return dict(episodes=len(rs), seconds_median=float(np.median([r["steps"] for r in rs]) / 80.0), dist_median_m=float(np.median([r["dist"] for r in rs])),
                    with_objects=len(withobj), never_reached=len(near), past_first=len(first), past_whole_field=len(whole), fell=sum(r["fell"] for r in rs))

    print(json.dumps(dict(all=stats(rows), focus=stats([r for r in rows if r["focus"]]))))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], float(sys.argv[3]), int(sys.argv[4]) if len(sys.argv) > 4 else 60)
