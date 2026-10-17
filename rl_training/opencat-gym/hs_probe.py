"""Score a gait for the high-step creep plan (docs/archive/plan-detail/high-step-creep-training-plan.md): a calm flat walk and a step-up ladder judged foot by foot.

    ../../.venv/bin/python hs_probe.py --policy scripted --ref creep --json-out x.json                     # the creep base, open loop
    ../../.venv/bin/python hs_probe.py --policy trained/hs_s0_ppo --ref creep --levers hs_creep,privileged_critic,heading_blind --json-out x.json
    ../../.venv/bin/python hs_probe.py --policy trained/v6_s4_avg5_ppo --levers privileged_critic,heading_blind --cmd 0.10 --json-out v6.json      # V6 for comparison

Flat: `--flat-episodes` calm walks of `--flat-seconds` (no shoves, no randomization) at `--cmd`: falls, speed, heading, roll, front and rear paw lift (90th - 5th percentile of
paw height), share of time a rear paw is off the ground, body height and the mean rear knee angle (the anti-crouch checks).
Step-ups: for each size, `--ledge-episodes` episodes of `--ledge-seconds` on a calm floor with one step-up whose edge is 0.11 m ahead. A paw is "up" once it touches the block's top
surface; SUCCESS = not fallen, all four paws up, and the body ended at least 0.10 m past the edge. Also: falls, all-four-up share, front-up share, median time to all four up.
The benchmark ladders' "success" (half the commanded distance in 7.5 s) hides where a step-up fails: V6 gets its front feet onto 10 mm in 34 of 40 episodes and scores 0 there.
"""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LEDGES_DEFAULT = "0.0075,0.010,0.0125,0.015,0.0175,0.020,0.025"
CROSS_PAST_M = 0.10


def world_env(levers, ref, nom_cmd):
    sys.path.insert(0, HERE)
    import g2_profile
    env = {k: str(v) for k, v in g2_profile.scoring_env(*[l for l in levers if l in g2_profile.LEVERS]).items()}
    for l in levers:                                     # the creep's world settings (base gait, cadence) must reach the scorer even though they are not observation levers
        if l.startswith("hs_"):
            env.update({k: v for k, v in g2_profile.LEVERS[l].items() if k in g2_profile.HS_WORLD_KEYS})
    if ref:
        env["G2E_SKILL_REF"] = ref
    if nom_cmd:
        env["G2E_PHASE_RATE_NOM_CMD"] = str(nom_cmd)
    env["G2E_FR_SPLIT_SIDE"] = "1"
    return env


def _worker(job):
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ.update(job["env"])
    sys.path.insert(0, HERE)
    os.chdir(HERE)
    import numpy as np
    import opencat_gym_env as E
    E.GUI_MODE = False
    import pybullet as p
    import benchmark_decathlon as B
    from benchmark_gaits import ScriptedGait, _load_learned
    keep = {k: getattr(E, k) for k in ("RANDOM_TERRAIN", "RUBBLE", "TORQUE_CUTBACK", "ROUGH_TERRAIN", "RANDOM_TERRAIN_MAX_H", "RUBBLE_MAX_H", "RUBBLE_N", "SNAG_OBSTACLE_N") if hasattr(E, k)}
    E.ADAPTIVE_PUSH = False
    env = E.OpenCatGymEnv()
    env.set_ramp_steps(1e12)
    if job["policy"] == "scripted":
        E.CMD_SEND_EVERY_N = 1
        model = ScriptedGait(env)
    else:
        model = _load_learned(job["policy"])
    PAWS = (3, 6, 9, 12)                                  # FL, FR, BR, BL
    kind, size = job["kind"], job["size"]
    steps = int(round(job["seconds"] * 80))
    recs = []
    for e in range(job["episodes"]):
        B._apply({})
        for k, v in keep.items():
            setattr(E, k, v)
        E.EPISODE_LENGTH = steps
        env.set_command(fwd=job["cmd"], yaw=0.0)
        env.set_forced_hazards({"ledge_up": size} if kind == "ledge" else {})
        env._reflex_on = False
        np.random.seed(job["seed"] + e)
        if hasattr(model, "reset"):
            model.reset()
        obs, _ = env.reset(seed=job["seed"] + e)
        rid = env.robot_id
        x0 = p.getBasePositionAndOrientation(rid)[0][0]
        peak, n = 0.0, 0
        if kind == "ledge":
            lid, h = env._ledge_id, env._ledge_h
            lp, lo = p.getBasePositionAndOrientation(lid)
            ip, io = p.invertTransform(lp, lo)
            on_top = {k: 0 for k in PAWS}
        else:
            fz, air, zs, rk, rolls = [[] for _ in PAWS], [[], []], [], [], []
        while True:
            a, _ = model.predict(obs, deterministic=True)
            obs, _r, te, tr, _i = env.step(a)
            n += 1
            pos, orn = p.getBasePositionAndOrientation(rid)
            r_, p_, y_ = p.getEulerFromQuaternion(orn)
            peak = max(peak, abs(r_), abs(p_))
            if kind == "ledge":
                for c in p.getContactPoints(bodyA=rid, bodyB=lid):
                    if c[3] in on_top and not on_top[c[3]]:
                        lc = p.multiplyTransforms(ip, io, c[6], [0, 0, 0, 1])[0]
                        if lc[2] >= h / 2 - 0.0015 and lc[0] > -0.70 + 0.003:
                            on_top[c[3]] = n
            elif n > 80 and peak < 1.0:
                zs.append(pos[2])
                rolls.append(np.degrees(r_))
                for i, l in enumerate(PAWS):
                    fz[i].append(p.getLinkState(rid, l)[0][2])
                for i, l in enumerate((9, 12)):
                    air[i].append(not p.getContactPoints(bodyA=rid, linkIndexA=l))
                js = p.getJointStates(rid, [env.joint_id[5], env.joint_id[7]])
                rk.append(np.degrees(0.5 * (js[0][0] + js[1][0])))
            if te or tr:
                break
        fell = bool(peak > 1.3)
        dur = n / 80.0
        if kind == "ledge":
            past = p.multiplyTransforms(ip, io, pos, [0, 0, 0, 1])[0][0] + 0.70
            all_up = all(on_top.values())
            recs.append(dict(fell=fell, all_up=bool(all_up), front_up=bool(on_top[3] and on_top[6]), past_m=float(past),
                             t_all_up=(max(on_top.values()) / 80.0 if all_up else None),
                             success=bool((not fell) and all_up and past >= CROSS_PAST_M)))
        else:
            rec = dict(fell=fell, speed=float((pos[0] - x0) / dur), heading_deg=float(np.degrees(y_)))
            if zs:
                lift = [1000.0 * (np.percentile(f, 90) - np.percentile(f, 5)) for f in fz]
                rec.update(front_lift_mm=float(np.mean(lift[:2])), rear_lift_mm=float(np.mean(lift[2:])), rear_air=float(np.mean(air[0] + air[1])),
                           body_mm=float(1000.0 * np.mean(zs)), rear_knee_deg=float(np.mean(rk)), roll_sd_deg=float(np.std(rolls)))
            recs.append(rec)
    return dict(kind=kind, size=size, recs=recs)


def run_jobs(jl, jobs=8, fresh=False):
    """The jobs on a spawn pool. fresh=True gives every job its own process (the env reads its G2E_ settings at import, so jobs with DIFFERENT worlds, e.g. a sweep's
    base gaits, must not share one)."""
    with mp.get_context("spawn").Pool(max(1, min(jobs, len(jl))), maxtasksperchild=(1 if fresh else None)) as pool:
        return pool.map(_worker, jl, chunksize=1)


def summarize(cells):
    import numpy as np
    out = {"flat": None, "ledges": []}
    for c in cells:
        r = c["recs"]
        if c["kind"] == "flat":
            m = lambda k: float(np.mean([x[k] for x in r if k in x])) if any(k in x for x in r) else None      # noqa: E731
            out["flat"] = dict(episodes=len(r), falls=float(np.mean([x["fell"] for x in r])), speed=m("speed"), heading_abs_deg=float(np.mean([abs(x["heading_deg"]) for x in r])),
                               front_lift_mm=m("front_lift_mm"), rear_lift_mm=m("rear_lift_mm"), rear_air=m("rear_air"), body_mm=m("body_mm"),
                               rear_knee_deg=m("rear_knee_deg"), roll_sd_deg=m("roll_sd_deg"))
        else:
            t = [x["t_all_up"] for x in r if x["t_all_up"] is not None]
            out["ledges"].append(dict(size_mm=round(c["size"] * 1000, 2), episodes=len(r), success=float(np.mean([x["success"] for x in r])),
                                      falls=float(np.mean([x["fell"] for x in r])), all_up=float(np.mean([x["all_up"] for x in r])),
                                      front_up=float(np.mean([x["front_up"] for x in r])), t_all_up_s=(float(np.median(t)) if t else None)))
    out["ledges"].sort(key=lambda d: d["size_mm"])
    return out


def ceiling(summary, bar=0.8):
    """The tallest step-up with success >= bar, counting up from the smallest size without a gap (0 if none)."""
    top = 0.0
    for L in summary["ledges"]:
        if L["success"] < bar:
            break
        top = L["size_mm"]
    return top


def run(policy, levers=(), ref="", nom_cmd=None, cmd=0.035, flat_episodes=10, flat_seconds=20.0, ledges=LEDGES_DEFAULT, ledge_episodes=20, ledge_seconds=15.0,
        seed=7000, jobs=8, chunk=10):
    env = world_env(list(levers), ref, nom_cmd)
    jl = []
    if flat_episodes:
        for k in range(0, flat_episodes, chunk):
            jl.append(dict(kind="flat", size=0.0, episodes=min(chunk, flat_episodes - k), seconds=flat_seconds, seed=seed + k, policy=policy, env=env, cmd=cmd))
    for s in [float(x) for x in str(ledges).split(",") if x.strip()] if ledges else []:
        for k in range(0, ledge_episodes, chunk):
            jl.append(dict(kind="ledge", size=s, episodes=min(chunk, ledge_episodes - k), seconds=ledge_seconds, seed=seed + 500 + k, policy=policy, env=env, cmd=cmd))
    t0 = time.time()
    parts = run_jobs(jl, jobs)
    merged = {}
    for prt in parts:
        merged.setdefault((prt["kind"], prt["size"]), []).extend(prt["recs"])
    cells = [dict(kind=k, size=s, recs=r) for (k, s), r in merged.items()]
    res = summarize(cells)
    res.update(policy=policy, levers=list(levers), ref=ref, cmd=cmd, nom_cmd=nom_cmd, seconds=round(time.time() - t0, 1), ceiling80_mm=ceiling(res))
    return res


def line(res):
    f = res["flat"] or {}
    fmt = lambda v, s="{:.1f}": (s.format(v) if v is not None else "-")      # noqa: E731
    lad = " ".join(f"{L['size_mm']:g}:{L['success']:.2f}/{L['falls']:.2f}" for L in res["ledges"])
    return (f"flat falls {fmt(f.get('falls'), '{:.2f}')} speed {fmt(f.get('speed'), '{:.3f}')} heading {fmt(f.get('heading_abs_deg'), '{:.0f}')} | lift F {fmt(f.get('front_lift_mm'))} "
            f"R {fmt(f.get('rear_lift_mm'))} mm | body {fmt(f.get('body_mm'))} mm rear knee {fmt(f.get('rear_knee_deg'), '{:+.1f}')} | step-ups mm:success/falls {lad} | 80% ceiling {res.get('ceiling80_mm', 0):g} mm")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--levers", default="")
    ap.add_argument("--ref", default="")
    ap.add_argument("--nom-cmd", type=float, default=None, help="override G2E_PHASE_RATE_NOM_CMD (the hs_creep lever sets 0.035)")
    ap.add_argument("--cmd", type=float, default=0.035)
    ap.add_argument("--flat-episodes", type=int, default=10)
    ap.add_argument("--flat-seconds", type=float, default=20.0)
    ap.add_argument("--ledges", default=LEDGES_DEFAULT)
    ap.add_argument("--ledge-episodes", type=int, default=20)
    ap.add_argument("--ledge-seconds", type=float, default=15.0)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()
    res = run(a.policy, [l for l in a.levers.split(",") if l], a.ref, a.nom_cmd, a.cmd, a.flat_episodes, a.flat_seconds, a.ledges, a.ledge_episodes, a.ledge_seconds, jobs=a.jobs)
    print(line(res), f"({res['seconds']:.0f} s)", flush=True)
    if a.json_out:
        json.dump(res, open(a.json_out, "w"), indent=1)


if __name__ == "__main__":
    main()
