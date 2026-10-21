"""Carpet-pad fit (carpet plan, user 2026-10-20): find the CARPET_PAD settings under which V7 behaves in the sim the way it did on the real carpet.

    ../../.venv/bin/python carpet_fit.py --grid 300,600,1200,2500 --damp 5,15 --episodes 20 [--cmd 0.10] [--json-out X]

Real target (2026-10-20, 1/4 in cut pile on a springy cushion pad, a fingertip sinks 1/4 in): V7 fell 6 times out of 6, on the first step, on his side 1.0-1.5 s after
the walk started, at 0.10 and at 0.05 m/s, with the firmware balance on or off. On hardwood the same policy walks (48 walks on 2026-10-18).
Each setting runs the calm flat walk (benchmark_v4's N1: 12.5 s, the scoring profile, full randomization, the same seeds for every setting) with V7 on the pad and
reports: falls, the time of the fall from the first step, which side, the deepest paw sink (contact penetration into the pad, mm, 95th percentile over the
stance) and the distance walked before the fall."""
import argparse
import json
import multiprocessing as mp
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

V7_POLICY, V7_LEVERS = "trained/pod_s4_ppo", ("privileged_critic", "heading_blind")
DT = 3.0 / 240.0                      # one env.step = 3 physics steps at 1/240 s


def _worker(job):
    os.environ.update(job["env"])
    import pybullet as p
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned
    from opencat_gym_env import OpenCatGymEnv
    E.ADAPTIVE_PUSH = False
    for k in ("CARPET_PAD_K", "CARPET_PAD_C", "CARPET_PAD_DEPTH", "CARPET_PAD_MU"):     # a pooled process imported the env for an earlier job: set this job's pad directly
        setattr(E, k, float(job["env"]["G2E_" + k]))
    env = OpenCatGymEnv()
    B._apply({})
    for k, v in job.get("set", {}).items():                                            # --set: any env knob, after the cell defaults
        setattr(E, k, v)
    if job.get("payload_dz") or job.get("payload_dy"):                                 # --payload-dz / --payload-dy: the pod's centre raised / moved sideways (m; -y = G2's right)
        E.PAYLOAD_POS = (E.PAYLOAD_POS[0], E.PAYLOAD_POS[1] + job.get("payload_dy", 0.0), E.PAYLOAD_POS[2] + job.get("payload_dz", 0.0))
    E.EPISODE_LENGTH = 1000
    env.set_command(fwd=job["cmd"], yaw=0.0)
    env._reflex_on = False
    if job["policy"].startswith("scripted"):                                          # "scripted" / "scripted:K": the base gait itself (zero residual), K = balance nudge
        from benchmark_gaits import ScriptedGait
        E.CMD_SEND_EVERY_N = 1
        model = ScriptedGait(env, balance_k=float(job["policy"].split(":")[1]) if ":" in job["policy"] else 0.0)
    else:
        model = _load_learned(job["policy"])
    out = []
    for e in range(job["episodes"]):
        np.random.seed(job["seed"] + e)
        if hasattr(model, "reset"):
            model.reset()
        obs, _ = env.reset()
        if job.get("weak"):                                                                # --weak: chosen joints' motor force scaled for the whole episode
            env._torque_scale = np.asarray(env._torque_scale, dtype=float).copy()
            for j, s in job["weak"].items():
                env._torque_scale[j] *= s
        rid = env.robot_id
        x0 = p.getBasePositionAndOrientation(rid)[0][0]
        sink, steps, fell, roll_at_fall = [], 0, False, 0.0
        r0 = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(rid)[1])[0]
        lean = 0.0                                                                     # the most-right roll in the first 1.5 s, deg from the start (real hardwood: median 8)
        t10 = None                                                                     # when the roll first passes 10 deg either way (real carpet: 0.48-0.85 s)
        while True:
            a, _ = model.predict(obs, deterministic=True)
            obs, _, term, trunc, _ = env.step(a)
            steps += 1
            for c in p.getContactPoints(bodyA=rid, bodyB=env._plane_id):
                if c[8] < 0:
                    sink.append(-c[8] * 1000.0)
            pos, orn = p.getBasePositionAndOrientation(rid)
            r, pt, _ = p.getEulerFromQuaternion(orn)
            if t10 is None and abs(np.degrees(r - r0)) >= 10:
                t10 = round(steps * DT, 2)
            if steps * DT <= 1.5:
                lean = max(lean, np.degrees(r - r0))                           # the sim's roll is + with the RIGHT side down (G2's IMU: -)
            if abs(r) > np.radians(60) or abs(pt) > np.radians(60):          # the real fall guard's threshold
                fell, roll_at_fall = True, r
                break
            if term or trunc:
                fell = bool(term and steps < E.EPISODE_LENGTH)
                roll_at_fall = r
                break
        out.append(dict(fell=fell, t_fall=round(steps * DT, 2) if fell else None, side=("right" if roll_at_fall > 0 else "left") if fell else None,
                        sink_p95_mm=round(float(np.percentile(sink, 95)), 2) if sink else 0.0, sink_med_mm=round(float(np.median(sink)), 2) if sink else 0.0,
                        dist_in=round((pos[0] - x0) / 0.0254, 1), lean_deg=round(float(lean), 1), t10=t10, pad=bool(getattr(env, "_pad_on", False))))
    return job["key"], out


def summarize(eps):
    falls = [e for e in eps if e["fell"]]
    t = [e["t_fall"] for e in falls]
    return dict(falls=round(len(falls) / len(eps), 2), t_fall_med=round(float(np.median(t)), 2) if t else None,
                right=sum(1 for e in falls if e["side"] == "right"), left=sum(1 for e in falls if e["side"] == "left"),
                sink_p95_mm=round(float(np.median([e["sink_p95_mm"] for e in eps])), 2), sink_med_mm=round(float(np.median([e["sink_med_mm"] for e in eps])), 2),
                dist_in_med=round(float(np.median([e["dist_in"] for e in eps])), 1),
                lean_med=round(float(np.median([e["lean_deg"] for e in eps])), 1), lean_p90=round(float(np.percentile([e["lean_deg"] for e in eps], 90)), 1),
                t10_med=(round(float(np.median([e["t10"] for e in falls if e["t10"] is not None])), 2) if any(e["t10"] is not None for e in falls) else None), pad_frac=round(sum(e["pad"] for e in eps) / len(eps), 2))


# The fitted setup (2026-10-20): the body that reproduces G2's hardwood roll and his right-side carpet falls, and the carpet that reproduces those falls (round 2 of
# the carpet fall check). FITTED_CARPET is the real-like carpet, HARSH_CARPET the softer, grippier end of the training band.
FITTED_BODY = dict(set={"MOTOR_FORCE": 0.10}, payload_dy=-0.008)
FITTED_CARPET = dict(k=120.0, c=2.0, depth=0.012, mu=2.2)
HARSH_CARPET = dict(k=80.0, c=1.5, depth=0.014, mu=2.6)


def run(policy=V7_POLICY, levers=V7_LEVERS, grid=(0.0, 120.0), damp=(10.0,), depth=0.0064, mu=1.0, episodes=20, cmd=0.10, seed=1000, jobs=8, extra=None, weak=None,
        payload_dz=0.0, payload_dy=0.0, quiet=False, env_extra=None):
    """Every (stiffness, damping) setting with `policy`, closed loop; returns {"rows": [...], "episodes": {...}}. Stiffness 0 is the hard floor. `levers`: the policy's
    observation levers (the scoring env must build the same inputs)."""
    import g2_profile
    base = {**g2_profile.scoring_env(*levers), **(env_extra or {})}             # env_extra: settings read at import (G2E_SKILL_REF: another base gait)
    jobs_l = []
    for k in [float(x) for x in grid]:
        for c in ([0.0] if k == 0 else [float(x) for x in damp]):
            env = {**base, "G2E_CARPET_PAD_K": str(k), "G2E_CARPET_PAD_C": str(c), "G2E_CARPET_PAD_DEPTH": str(depth), "G2E_CARPET_PAD_MU": str(mu)}
            per = max(1, episodes // 2)                   # two workers per setting, each its own half of the seeds
            for h in range(2):
                n = per if h == 0 else episodes - per
                jobs_l.append(dict(key=(k, c), env=env, cmd=cmd, episodes=n, seed=seed + h * per, policy=policy, set=extra or {}, weak=weak or {},
                                   payload_dz=payload_dz, payload_dy=payload_dy))
    with mp.get_context("spawn").Pool(jobs, maxtasksperchild=1) as pool:
        res = {}
        for key, eps in pool.imap_unordered(_worker, jobs_l):
            res.setdefault(key, []).extend(eps)
    rows = []
    if not quiet:
        print(f"{'K N/m':>7} {'C':>5} {'falls':>6} {'t_fall':>7} {'R/L':>6} {'sink95':>7} {'sinkmed':>8} {'dist in':>8} {'R lean med/p90':>15} {'t10':>5}")
    for (k, c) in sorted(res):
        s = summarize(res[(k, c)])
        rows.append(dict(k=k, c=c, **s))
        if not quiet:
            print(f"{k:7.0f} {c:5.0f} {s['falls']:6.2f} {str(s['t_fall_med']):>7} {s['right']:>2}/{s['left']:<3} {s['sink_p95_mm']:7.2f} {s['sink_med_mm']:8.2f} "
                  f"{s['dist_in_med']:8.1f} {s['lean_med']:7.1f}/{s['lean_p90']:<6.1f} {str(s['t10_med']):>5}")
    return dict(rows=rows, episodes={f"{k}_{c}": v for (k, c), v in res.items()})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="300,600,1200,2500", help="pad stiffness values, N/m per contact point (0 = the hard floor)")
    ap.add_argument("--damp", default="10", help="pad damping values")
    ap.add_argument("--depth", type=float, default=0.0064)
    ap.add_argument("--mu", type=float, default=1.0)
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--cmd", type=float, default=0.10)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--policy", default=V7_POLICY)
    ap.add_argument("--levers", default=",".join(V7_LEVERS), help="the policy's observation levers")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--set", default="", help="extra env knobs for every setting, e.g. MOTOR_SCALE_ALL=0.8,FAULT_WEAK_PROB=1")
    ap.add_argument("--weak", default="", help="joint:scale pairs, joints 0 FL shoulder, 1 FL knee, 2 FR shoulder, 3 FR knee, 4 RR hip, 5 RR knee, 6 RL hip, 7 RL knee; e.g. 4:0.6,5:0.6")
    ap.add_argument("--payload-dz", type=float, default=0.0, help="raise the pod's centre by this much (m)")
    ap.add_argument("--payload-dy", type=float, default=0.0, help="move the pod's centre sideways (m); negative = toward G2's right")
    ap.add_argument("--env", default="", help="G2E settings read at import, e.g. G2E_SKILL_REF=carpet (the base gait)")
    a = ap.parse_args()
    extra = {kv.split("=")[0]: float(kv.split("=")[1]) for kv in a.set.split(",") if "=" in kv}
    weak = {int(kv.split(":")[0]): float(kv.split(":")[1]) for kv in a.weak.split(",") if ":" in kv}
    out = run(a.policy, [x for x in a.levers.split(",") if x], [float(x) for x in a.grid.split(",")], [float(x) for x in a.damp.split(",")], a.depth, a.mu, a.episodes,
              a.cmd, a.seed, a.jobs, extra, weak, a.payload_dz, a.payload_dy,
              env_extra={kv.split("=")[0]: kv.split("=")[1] for kv in a.env.split(",") if "=" in kv})
    if a.json_out:
        json.dump(dict(args=vars(a), **out), open(a.json_out, "w"), indent=1)


if __name__ == "__main__":
    main()
