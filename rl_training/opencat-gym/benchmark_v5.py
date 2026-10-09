"""Benchmark V5 (2026-10-09, docs/plan-detail/v5-training-plan.md): everything benchmark_v4 scores (the T / N cells, now with the side-hill in both directions and the
ledge split into up and down), plus the SIZE LADDER: each training hazard on its own at four sizes up to the top of its V5 training ladder, in 7.5 s episodes (the
same length as V5's hazard training episodes), so the report can say "the largest size it passes" per hazard and compare it with the scripted walk.

    python benchmark_v5.py --policy trained/<tag>_ppo --levers privileged_critic,heading_blind --json-out out.json [--episodes 40] [--ladder-episodes 40] [--jobs 8]
    python benchmark_v5.py --policy scripted --json-out trained/v5_scripted.json          # the baseline (the scripted wkF walk, no learned correction)

A ladder cell forces exactly one hazard at one size (opencat_gym_env.set_forced_hazards) on an otherwise calm floor (no shoves, no randomization: benchmark_decathlon
_apply), commands 0.10 m/s, and records falls, how far G2 walked, and whether it got past the first object / the whole obstacle field / the ledge edge. A size counts as
PASSED when at most PASS_FALLS of its episodes fall. Episode e uses seed seed0 + e, so every policy meets the same courses (paired)."""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np

import g2_profile

LADDER_STEPS = 600                 # 7.5 s, the V5 hazard-episode length
PASS_FALLS = 0.20                  # a size is passed when no more than this share of its episodes fall
# hazard -> (label, unit, unit factor for display, sizes in FR_BOUND units). Tops = the V5 training ladder's tops (user, 2026-10-09).
LADDER = {
    "sidehill_l": ("Side-hill, left side down", "deg", 1, (2.0, 4.0, 6.0, 8.0)),
    "sidehill_r": ("Side-hill, right side down", "deg", 1, (2.0, 4.0, 6.0, 8.0)),
    "climb": ("Uphill", "deg", 1, (2.5, 5.0, 7.5, 10.0)),
    "descent": ("Downhill", "deg", 1, (2.5, 5.0, 7.5, 10.0)),
    "ledge_up": ("Step up", "mm", 1000, (0.010, 0.020, 0.030, 0.035)),
    "ledge_down": ("Step down", "mm", 1000, (0.010, 0.020, 0.030, 0.040)),
    "rubble": ("Rubble", "x level-1 size", 1, (0.5, 1.0, 1.5, 2.0)),
    "boxes": ("Box obstacles", "x level-1 size", 1, (0.5, 1.0, 1.5, 2.0)),
    "snag": ("Snag obstacles (cable-like)", "x level-1 size", 1, (0.5, 1.0, 1.5, 2.0)),
    "rough": ("Rough floor", "x level-1 size", 1, (0.5, 1.0, 1.5, 2.0)),
    "cutback": ("Overheated servos", "x level-1 size", 1, (0.5, 1.0, 1.5, 2.0)),
}
OBJECT_HAZARDS = ("rubble", "boxes", "snag")          # hazards with solid objects to get past
LEDGE_HAZARDS = ("ledge_up", "ledge_down")


_LEDGE_TOP = float(os.environ.get("G2E_V5_LEDGE_TOP", "0") or 0)       # set by phase_v5 for the preflight / 20M / report: step-up and step-down ladders in quarters of this top (user: 30 mm)
if _LEDGE_TOP > 0:
    for _h, _lab in (("ledge_up", "Step up"), ("ledge_down", "Step down")):
        LADDER[_h] = (_lab, "mm", 1000, tuple(round(_LEDGE_TOP * f, 5) for f in (0.25, 0.5, 0.75, 1.0)))


def ladder_cells(hazards=None):
    """[(cell id, hazard or None, size)]: a 7.5 s hazard-free walk first (the ladder's own baseline), then every hazard x size."""
    out = [("Z0", None, 0.0)]
    for h, (_, _, _, sizes) in LADDER.items():
        if hazards and h not in hazards:
            continue
        for i, s in enumerate(sizes):
            out.append((f"Z.{h}.{i + 1}", h, float(s)))
    return out


def _ladder_worker(job):
    """One process: its own scoring environment (the policy's observation levers), its own policy copy; scores job['cells']."""
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ.update(job["env"])
    import evaluate_policy
    evaluate_policy.EPISODE_CAP = 10 ** 9
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    import benchmark_v4 as V
    from benchmark_gaits import ScriptedGait, _load_learned
    keep = {k: getattr(E, k) for k in ("RANDOM_TERRAIN", "RUBBLE", "TORQUE_CUTBACK", "ROUGH_TERRAIN", "RANDOM_TERRAIN_MAX_H", "RUBBLE_MAX_H", "RUBBLE_N",
                                       "SNAG_OBSTACLE_N") if hasattr(E, k)}
    E.ADAPTIVE_PUSH = False
    env = E.OpenCatGymEnv()
    if job["policy"] == "scripted":
        E.CMD_SEND_EVERY_N = 1
        model = ScriptedGait(env)
    else:
        model = _load_learned(job["policy"])
    out = []
    for cid, h, size in job["cells"]:
        B._apply({})                                   # calm floor: no shoves, no randomization
        for k, v in keep.items():                      # ... but the hazard generators the forced hazard needs stay on
            setattr(E, k, v)
        E.EPISODE_LENGTH = LADDER_STEPS
        env.set_command(fwd=0.10, yaw=0.0)
        env.set_forced_hazards({} if h is None else {h: size})
        env._reflex_on = False
        eps, cross = [], []
        t0 = time.time()
        for e in range(job["episodes"]):
            np.random.seed(job["seed"] + e)
            if hasattr(model, "reset"):
                model.reset()
            r = evaluate_policy.run_episode(env, model)
            eps.append(r)
            dist = float(r[0]["x"][-1]) if r[0]["x"] else 0.0
            objs = sorted(getattr(env, "_obj_far", []) or [])
            ledge = getattr(env, "_ledge_edge", None)
            cross.append(dict(dist=dist, objs=len(objs),
                              past_first=bool(objs) and dist - 0.10 > objs[0], past_all=bool(objs) and dist - 0.10 > objs[-1],
                              past_ledge=ledge is not None and dist - 0.10 > ledge + 0.05))
        env.set_forced_hazards(None)
        m = V.v4_metrics(eps)
        fell = m["ep_fell"]
        need = 0.5 * 0.10 * LADDER_STEPS / 80.0
        m.update(dict(id=cid, hazard=h, size=size, episodes=len(eps), steps=LADDER_STEPS, seconds=round(time.time() - t0, 1),
                      success=float(np.mean([(not f) and c["dist"] >= need for f, c in zip(fell, cross)])),
                      dist_median_m=float(np.median([c["dist"] for c in cross]))))
        if h in OBJECT_HAZARDS:
            w = [c for c in cross if c["objs"]]
            m["with_objects"] = len(w)
            m["past_first"] = float(np.mean([c["past_first"] for c in w])) if w else None
            m["past_all"] = float(np.mean([c["past_all"] for c in w])) if w else None
        if h in LEDGE_HAZARDS:
            m["past_ledge"] = float(np.mean([c["past_ledge"] for c in cross]))
        for k in ("joint_mean_deg",):
            m.pop(k, None)
        out.append(m)
        print(f"  [{os.getpid()}] {cid}: fell {m['fell_fraction']:.0%}  success {m['success']:.0%}  dist {m['dist_median_m']:.2f} m  ({time.time() - t0:.0f} s)", flush=True)
    return out


def run_ladder(policy, levers=(), episodes=40, seed=5000, jobs=8, hazards=None, quiet=False):
    """The size ladder for one policy; returns {"cells": [...], "summary": ladder_summary(...)}."""
    env = {k: str(v) for k, v in g2_profile.scoring_env(*levers).items()}
    env["G2E_FR_SPLIT_SIDE"] = "1"                     # the forced side-hill names (no effect on anything else)
    cells = ladder_cells(hazards)
    buckets = [cells[i::max(1, jobs)] for i in range(max(1, min(jobs, len(cells))))]
    jl = [dict(policy=policy, env=env, cells=b, episodes=episodes, seed=seed) for b in buckets]
    t0 = time.time()
    if len(jl) == 1:
        res = [_ladder_worker(jl[0])]
    else:
        with mp.get_context("spawn").Pool(len(jl)) as pool:
            res = pool.map(_ladder_worker, jl)
    order = {c[0]: i for i, c in enumerate(cells)}
    out = sorted([c for r in res for c in r], key=lambda c: order[c["id"]])
    if not quiet:
        print(f"ladder done in {time.time() - t0:.0f} s", flush=True)
    return {"cells": out, "summary": ladder_summary(out), "episodes": episodes, "steps": LADDER_STEPS, "pass_falls": PASS_FALLS}


def ladder_summary(cells):
    """Per hazard: falls and success at each size, the largest size PASSED (contiguous from the smallest: every size up to it passes), and the crossing rates."""
    by = {}
    for c in cells:
        if c["hazard"] is None:
            continue
        by.setdefault(c["hazard"], []).append(c)
    out = {}
    for h, cs in by.items():
        cs = sorted(cs, key=lambda c: c["size"])
        top = None
        for c in cs:
            if c["fell_fraction"] <= PASS_FALLS:
                top = c["size"]
            else:
                break
        label, unit, k, _ = LADDER[h]
        out[h] = dict(label=label, unit=unit, factor=k, sizes=[c["size"] for c in cs], falls=[c["fell_fraction"] for c in cs], success=[c["success"] for c in cs],
                      past_all=[c.get("past_all") for c in cs], past_ledge=[c.get("past_ledge") for c in cs], largest_passed=top,
                      mean_falls=float(np.mean([c["fell_fraction"] for c in cs])))
    return out


def run_all(policy, levers=(), episodes=40, ladder_episodes=40, jobs=8, quiet=True):
    """Every benchmark_v4 cell (incl. the V5 side-hill / ledge cells) plus the size ladder, in fresh processes (the scoring environment must be set before the env module
    is imported, and this process may already have imported it)."""
    import benchmark_v4
    saved = dict(os.environ)
    try:
        res = benchmark_v4.run(policy, "all", episodes, 1000, jobs, None, tuple(levers), None, mirror_gap=(policy != "scripted"), quiet=quiet)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    res["size_ladder"] = run_ladder(policy, levers, ladder_episodes, jobs=jobs, quiet=quiet)
    res["bench"] = "v5"
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True)
    ap.add_argument("--levers", default="")
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--ladder-episodes", type=int, default=40)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--ladder-only", action="store_true")
    ap.add_argument("--hazards", default="", help="ladder only these hazards (comma list)")
    a = ap.parse_args()
    lv = tuple(x for x in a.levers.split(",") if x)
    if a.ladder_only:
        res = {"size_ladder": run_ladder(a.policy, lv, a.ladder_episodes, jobs=a.jobs, hazards=[h for h in a.hazards.split(",") if h] or None)}
    else:
        res = run_all(a.policy, lv, a.episodes, a.ladder_episodes, a.jobs, quiet=False)
    os.makedirs(os.path.dirname(os.path.abspath(a.json_out)), exist_ok=True)
    json.dump(res, open(a.json_out, "w"), indent=1)
    print(f"wrote {a.json_out}")


if __name__ == "__main__":
    main()
