"""Robustness sweep -- where does a policy break as we vary the sim-to-real
axes one at a time? No training. Each axis is swept from its nominal value
outward; everything else held at nominal, DR eval terrain on, fixed forward
command. Reports fall rate + forward speed + body-tilt RMS per setting, and
flags the value where the gait first degrades (first_degrade_at).

    python robustness_sweep.py --learned trained/run20m_ppo --seeds 16
    python robustness_sweep.py --learned trained/run20m_newcourse_ppo \
        --learned-b trained/run20m_ppo --bare --seeds 24

--learned-b overlays a second policy and reports which one holds its margin
(reaches a higher first-degrade value) longer per axis. --bare drops the
payload (PAYLOAD_PROB=0) -- the torque-cutback and IMU axes are largely masked
by the payload's inertia otherwise, same reason the decathlon has bare-robot
cells.

Purpose: size the bands for a transfer-hardening DR run (or show one isn't
needed). The cliffs here are sim-model cliffs, not measured-hardware cliffs --
read them as "how much headroom does the current policy have", not as a
hardware prediction.
"""
import argparse, json, sys, os
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

import opencat_gym_env as E
E.GUI_MODE = False

# axis name -> (env attr, nominal, [sweep values], units)
AXES = {
    "payload_mass_g":   ("PAYLOAD_MASS_NOM", 0.075, [0.05, 0.075, 0.10, 0.13, 0.16, 0.19], "kg"),
    "cmd_latency_steps":("CMD_LATENCY_STEPS", 0,     [0, 1, 2, 3, 4, 6],                    "steps @80Hz"),
    "joint_offset_deg": ("JOINT_OFFSET_DEG", 0.0,   [0.0, 1.0, 2.0, 3.0, 5.0, 8.0],        "deg"),
    "imu_noise":        ("RANDOM_GYRO",      0.02,  [0.01, 0.02, 0.04, 0.06, 0.10, 0.15],  "std"),
    "joint_sensor_pct": ("RANDOM_JOINT_ANGS",5,     [0, 5, 10, 15, 20, 30],                "%"),
    "torque_cutback":   ("TORQUE_CUTBACK",   0.35,  [0.0, 0.2, 0.35, 0.5, 0.65, 0.8],      "frac"),
}

# every axis' env attr, so we can reset all to nominal before each cell
_NOMINAL = {v[0]: v[1] for v in AXES.values()}


def rollout(model, seeds, steps=300, cmd=0.10):
    import pybullet as p
    from opencat_gym_env import OpenCatGymEnv
    env = OpenCatGymEnv()
    falls, sp, tilt_rms = 0, [], []
    for s in range(seeds):
        np.random.seed(7000 + s)
        obs, _ = env.reset()
        env.set_command(fwd=cmd, yaw=0.0)
        x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        tl, n, fell = [], 0, False
        for _ in range(steps):
            a, _ = model.predict(obs, deterministic=True)
            obs, _, term, trunc, _ = env.step(a)
            q = p.getBasePositionAndOrientation(env.robot_id)[1]
            rp = p.getEulerFromQuaternion(q)
            tl.append(max(abs(rp[0]), abs(rp[1])))
            n += 1
            if term:
                fell = True
                break
        x1 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
        falls += fell
        sp.append((x1 - x0) / (n / 80.0))
        tilt_rms.append(float(np.sqrt(np.mean(np.square(tl)))))
    env.close()
    return {
        "fall_rate": falls / seeds,
        "fwd_mps": float(np.mean(sp)),
        "tilt_rms": float(np.mean(tilt_rms)),
    }


def _degrades(r, base):
    dfwd = r["fwd_mps"] - base["fwd_mps"]
    return (r["fall_rate"] >= 0.15) or (dfwd <= -0.25 * base["fwd_mps"]), dfwd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned", default="trained/run20m_ppo")
    ap.add_argument("--learned-b", default=None,
                    help="overlay a second policy; report which holds its margin longer per axis")
    ap.add_argument("--bare", action="store_true",
                    help="PAYLOAD_PROB=0 -- torque-cutback / IMU axes are masked by the payload otherwise")
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    E.DR_EVAL_FULL = True
    E.PAYLOAD_PROB = 0.0 if args.bare else 1.0
    E.PAYLOAD_MASS_RAND = 0.0
    E.ROUGH_TERRAIN = getattr(E, "ROUGH_TERRAIN", 0.0)
    from stable_baselines3 import PPO
    gaits = [("A", args.learned, PPO.load(args.learned))]
    if args.learned_b:
        gaits.append(("B", args.learned_b, PPO.load(args.learned_b)))

    # nominal baseline per gait (all axes at nominal). PAYLOAD_PROB is not in
    # _NOMINAL, so the per-axis reset loop below never clobbers it.
    for attr, val in _NOMINAL.items():
        setattr(E, attr, val)
    base = {}
    for tag, path, m in gaits:
        base[tag] = rollout(m, args.seeds)
        print(f"BASELINE {tag} ({path}): fall {base[tag]['fall_rate']:.0%} | "
              f"fwd {base[tag]['fwd_mps']:.3f} m/s | tilt_rms {base[tag]['tilt_rms']:.3f} rad")
    print(f"  (payload {'OFF -- bare robot' if args.bare else 'on'})\n")

    out = {"learned": args.learned, "learned_b": args.learned_b, "bare": args.bare,
           "seeds": args.seeds, "baseline": base, "axes": {}}
    for axis, (attr, nom, vals, units) in AXES.items():
        print(f"=== {axis}  ({units}, nominal {nom}) ===")
        cols = "  ".join(f"{t+':fall% fwd Δfwd':>22}" for t, _, _ in gaits)
        print(f"    {'value':>8}  {cols}")
        rows = []
        cliff = {t: None for t, _, _ in gaits}
        for v in vals:
            for a2, n2 in _NOMINAL.items():
                setattr(E, a2, n2)
            setattr(E, attr, v)

            cells, per_gait = [], {}
            for tag, _, m in gaits:
                r = rollout(m, args.seeds)
                bad, dfwd = _degrades(r, base[tag])
                if bad and cliff[tag] is None and v != nom:
                    cliff[tag] = v
                cells.append(f"{r['fall_rate']*100:4.0f} {r['fwd_mps']:.3f} {dfwd:+.3f}"
                             + ("*" if bad else " "))
                per_gait[tag] = {**r, "d_fwd": dfwd, "degrades": bool(bad)}
            print(f"    {v:>8}  " + "  ".join(f"{c:>22}" for c in cells))
            rows.append({"value": v, "gaits": per_gait})
        out["axes"][axis] = {"attr": attr, "nominal": nom, "units": units,
                             "first_degrade_at": cliff, "rows": rows}
        line = "  |  ".join(f"{t}: {cliff[t] if cliff[t] is not None else 'held'}" for t, _, _ in gaits)
        print(f"    -> first degradation --  {line}")
        if len(gaits) == 2:
            def k(x): return 1e9 if x is None else x
            ca, cb = cliff["A"], cliff["B"]
            better = "A" if k(ca) > k(cb) else ("B" if k(cb) > k(ca) else "tie")
            print(f"       margin: {'A' if better=='A' else 'B' if better=='B' else 'neither'} holds longer"
                  f" ({better})")
        print()

    for a2, n2 in _NOMINAL.items():   # leave the module clean
        setattr(E, a2, n2)
    jp = args.json_out or "robustness_sweep.json"
    json.dump(out, open(jp, "w"), indent=1)
    print(f"wrote {jp}")


if __name__ == "__main__":
    main()
