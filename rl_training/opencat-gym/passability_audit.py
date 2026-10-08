"""Is the hardest training course still passable? (user, 2026-10-08, after a floor bug put 11-29 cm walls in front of G2 in about one episode in six)

PART A -- geometry (this file, `geometry`): no policy, no stepping. For each hazard at a pinned difficulty level, generate many episodes with the TRAINING sampler (the 20M's
course settings, hard levels x1.10) and scan the lane ahead of the robot with rays. Per episode it measures
  forced rise   the smallest wall the robot must climb in the next 1.2 m, over three lanes (a gap beside an obstacle makes it avoidable): the largest rise within any 2 cm of travel
  tilt          the ground tilt (deg)
  spawn         whether the robot's body overlaps the ground or an obstacle by more than 1 cm at the start (buried or wedged)
and prints the distribution, the share of episodes over each wall height, and the worst episodes (seed + settings) so each can be reproduced and looked at.
  ../../.venv/bin/python passability_audit.py geometry [--levels 1.0,1.25] [--episodes 300] [--cats terrain,ledge,slope,combo]

PART B -- capability (`capability`, run when the Mac is idle): the best available policies against each hazard at rising magnitudes, to find where "very hard" ends and "impossible" begins.
"""
import argparse
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

CHILD = r'''
import json, os, sys
sys.path.insert(0, %(here)r)
import g2_profile
env = g2_profile.next_final_env()          # the parked fresh final's own training environment (caps included): what is audited is what trains
env.update({"G2E_SCALE_ALL_HAZARDS": "1", "G2E_ADAPTIVE_LEVEL": "1", "G2E_CATEGORY_LEVELS": "1", "G2E_LEVEL_START": "0", "G2E_RECORD_EVERY": "0"})
env.update(%(extra)r)
g2_profile.set_environ(env)
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
CATS, LV = %(cats)r, %(level)r
E.CATEGORY_OVERRIDE = {c: LV for c in CATS}
e = E.OpenCatGymEnv(); e.set_ramp_steps(5e6)
XS = np.arange(0.02, 1.20, 0.005)
LANES = (-0.12, 0.0, 0.12)
rows = []
for k in range(%(episodes)d):
    seed = 9000 + k
    np.random.seed(seed)
    e.reset(seed=seed)
    robot = e.robot_id
    forced, lane_rises = None, []
    for y in LANES:
        res = p.rayTestBatch([[x, y, 1.0] for x in XS], [[x, y, -1.0] for x in XS])
        h = np.array([np.nan if (r[0] < 0 or r[0] == robot) else 1.0 - 2.0 * r[2] for r in res])
        good = ~np.isnan(h)
        if good.sum() < 10:
            continue
        idx = np.where(good, np.arange(len(h)), 0); np.maximum.accumulate(idx, out=idx); h = h[idx]
        rise = float(np.max(h[4:] - h[:-4]))                     # the biggest climb within 2 cm of travel
        lane_rises.append(rise)
    forced = min(lane_rises) if lane_rises else float("nan")
    p.performCollisionDetection()
    pen = 0.0
    for o in range(p.getNumBodies()):
        oid = p.getBodyUniqueId(o)
        if oid in (robot, e._payload_id, e._head_id, e._rear_id):        # the welded payload boxes have collisions switched off: not ground
            continue
        for c in p.getClosestPoints(robot, oid, 0.0):
            pen = min(pen, c[8])                                 # contactDistance: negative = the bodies overlap at the start
    buried = bool(pen < -0.01)
    rp = getattr(e, "_slope_rp", (0.0, 0.0))
    rows.append({"seed": seed, "forced_rise_m": forced, "tilt_deg": float(np.degrees(max(abs(rp[0]), abs(rp[1])))), "buried": buried,
                 "ledge_h": float(getattr(e, "_ledge_h", 0.0)), "ledge_dir": int(getattr(e, "_ledge_dir", 0)), "slope_rp_deg": [round(float(np.degrees(x)), 1) for x in rp]})
print("ROWS " + json.dumps(rows))
'''


def run_child(cats, level, episodes, extra):
    code = CHILD % {"here": HERE, "cats": cats, "level": level, "episodes": episodes, "extra": extra}
    r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=3600)
    for line in r.stdout.splitlines():
        if line.startswith("ROWS "):
            return json.loads(line[5:])
    raise RuntimeError(r.stderr[-1500:])


def pct(a, q):
    a = sorted(x for x in a if x == x)
    return a[min(len(a) - 1, int(q * len(a)))] if a else float("nan")


def geometry(a):
    levels = [float(x) for x in a.levels.split(",")]
    configs = {"terrain": ["terrain"], "ledge": ["ledge"], "slope": ["slope"], "combo": ["terrain", "ledge", "slope"]}
    wanted = [c for c in a.cats.split(",") if c in configs]
    out = {}
    print(f"{'hazard':8s} {'level':>5s} {'n':>4s} | forced rise cm: {'p50':>5s} {'p95':>5s} {'max':>5s} | over 3cm  5cm  9cm | tilt deg p95 max | buried")
    for name in wanted:
        for lv in levels:
            rows = run_child(configs[name], lv, a.episodes, {})
            out[f"{name}@{lv}"] = rows
            fr = [r["forced_rise_m"] * 100 for r in rows]
            over = [sum(1 for x in fr if x > t) / max(1, len(fr)) for t in (3, 5, 9)]
            tilt = [r["tilt_deg"] for r in rows]
            print(f"{name:8s} {lv:5.2f} {len(rows):4d} |                {pct(fr, .5):5.1f} {pct(fr, .95):5.1f} {max(fr):5.1f} |      {over[0]:4.0%} {over[1]:4.0%} {over[2]:4.0%} |        {pct(tilt, .95):4.1f} {max(tilt):4.1f} | {sum(r['buried'] for r in rows) / max(1, len(rows)):.1%}", flush=True)
    worst = sorted(((r["forced_rise_m"], k, r) for k, rows in out.items() for r in rows if r["forced_rise_m"] == r["forced_rise_m"]), key=lambda t: -t[0])[:8]
    print("\nworst episodes (reproduce with np.random.seed(seed) then reset(seed=seed) under the same settings):")
    for rise, k, r in worst:
        print(f"  {k:14s} seed {r['seed']}: forced rise {rise * 100:5.1f} cm, ledge {r['ledge_h'] * 100:4.1f} cm dir {r['ledge_dir']:+d}, ground tilt {r['slope_rp_deg']} deg")
    os.makedirs("trained", exist_ok=True)
    json.dump(out, open("trained/passability_geometry.json", "w"))
    print("\nsaved trained/passability_geometry.json")


# ----------------------------------------------------------------------------------------------------------------------------------- Part B: capability

FAMILIES = {                      # hazard family -> (what the magnitude is, the magnitudes to try)
    "sidehill": ("cross-slope roll, deg (either side down)", [4, 6, 8, 10, 12, 15, 18, 20]),
    "uphill": ("climb, deg", [8, 12, 16, 20, 24, 28, 30]),
    "downhill": ("descent, deg", [8, 12, 16, 20, 24]),
    "ledge": ("step height, cm (up or down, lane-spanning)", [2.5, 3.5, 4.5, 6.0, 8.0]),
}

CAP_CHILD = r'''
import json, sys
sys.path.insert(0, %(here)r)
import g2_profile
env = dict(g2_profile.scoring_env("mirror"))
FAM, MAGS, POLICY, EPS = %(fam)r, %(mags)r, %(policy)r, %(episodes)d
if FAM == "ledge":
    env.update({"G2E_LEDGE_PROB": "1.0", "G2E_LEDGE_RANDOMIZE": "0", "G2E_LEDGE_HEIGHT": "0.01"})
g2_profile.set_environ(env)
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
if FAM == "ledge":
    E.CATEGORY_OVERRIDE = {"ledge": 1.0}
from stable_baselines3 import PPO
m = PPO.load(POLICY)
e = E.OpenCatGymEnv(); e.set_command(fwd=0.10, yaw=0.0); e.set_ramp_steps(5e6)
out = []
for mag in MAGS:
    ok = falls = 0
    prog = []
    for k in range(EPS):
        np.random.seed(7000 + k)
        sgn = 1.0 if k %% 2 == 0 else -1.0
        if FAM == "sidehill":
            E.SLOPE_FIXED_RP = (sgn * np.deg2rad(mag), 0.0)
        elif FAM == "uphill":
            E.SLOPE_FIXED_RP = (0.0, -np.deg2rad(mag))
        elif FAM == "downhill":
            E.SLOPE_FIXED_RP = (0.0, np.deg2rad(mag))
        else:
            E.LEDGE_HEIGHT = mag / 100.0
        obs, _ = e.reset(seed=7000 + k)
        x0 = p.getBasePositionAndOrientation(e.robot_id)[0][0]
        peak, n = 0.0, 0
        while True:
            a, _ = m.predict(obs, deterministic=True)
            obs, r, te, tr, info = e.step(a)
            n += 1
            o = p.getBasePositionAndOrientation(e.robot_id)[1]
            rr, pp, _y = p.getEulerFromQuaternion(o)
            peak = max(peak, abs(rr), abs(pp))
            if te or tr:
                break
        dx = p.getBasePositionAndOrientation(e.robot_id)[0][0] - x0
        fell = peak > 1.3
        falls += fell
        done = dx / (0.10 * n / 80.0)
        prog.append(done)
        ok += (not fell) and done >= 0.5          # passed = stayed up AND covered at least half of the commanded distance
    out.append({"mag": mag, "success": ok / EPS, "falls": falls / EPS, "progress": float(np.mean(prog))})
print("CAP " + json.dumps(out))
'''


def idle_wait(poll=60):
    import time
    sys.path.insert(0, os.path.join(HERE, "..", "..", "tools"))
    while True:
        out = subprocess.run(["ps", "-axo", "pid,command"], capture_output=True, text=True).stdout.splitlines()
        busy = [l for l in out if any(t in l for t in ("train.py", "benchmark_", "phase_v3.py")) and "passability_audit" not in l]
        if not busy:
            return
        time.sleep(poll)


def capability(a):
    if a.wait_idle:
        print("waiting for an idle Mac (the training queue first)...", flush=True)
        idle_wait()
    policies = [x for x in a.policies.split(",") if os.path.exists(os.path.join(HERE, x + ".zip"))]      # chosen after the wait: the 20M's final policy exists by then
    print("policies:", policies, flush=True)
    families = [f for f in a.families.split(",") if f in FAMILIES]
    jobs = []
    for pol in policies:
        for fam in families:
            code = CAP_CHILD % {"here": HERE, "fam": fam, "mags": FAMILIES[fam][1], "policy": pol, "episodes": a.episodes}
            jobs.append((pol, fam, code))
    import concurrent.futures as cf

    def run(j):
        r = subprocess.run([sys.executable, "-c", j[2]], cwd=HERE, capture_output=True, text=True, timeout=7200)
        for line in r.stdout.splitlines():
            if line.startswith("CAP "):
                return j[0], j[1], json.loads(line[4:])
        return j[0], j[1], None
    res = {}
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for pol, fam, rows in ex.map(run, jobs):
            res.setdefault(fam, {})[pol] = rows
    print(f"\nsuccess = stayed up and covered at least half the commanded distance ({a.episodes} episodes per cell, commanded 0.10 m/s)")
    rec = {}
    for fam, (what, mags) in FAMILIES.items():
        if fam not in res:
            continue
        print(f"\n{fam}: {what}")
        print("  magnitude  " + "  ".join(f"{os.path.basename(p):>24s}" for p in res[fam]) + "   best")
        best_ok = None
        for i, mag in enumerate(mags):
            cells = [res[fam][p][i]["success"] if res[fam][p] else float("nan") for p in res[fam]]
            best = max((c for c in cells if c == c), default=float("nan"))
            if best == best and best >= 0.5:
                best_ok = mag
            print(f"  {mag:9g}  " + "  ".join(f"{c:24.0%}" for c in cells) + f"   {best:4.0%}")
        rec[fam] = best_ok
    print("\nlargest magnitude the best policy passes at least half the time:", rec)
    os.makedirs("trained", exist_ok=True)
    json.dump({"results": res, "largest_passable": rec}, open("trained/passability_capability.json", "w"), indent=1)
    print("saved trained/passability_capability.json")


# ----------------------------------------------------------------------------------------------------------------------------------- scene sanity

SCENE_CHILD = r'''
import json, sys
sys.path.insert(0, %(here)r)
import g2_profile
env = g2_profile.next_final_env()          # the parked fresh final's own training environment (caps included): what is audited is what trains
env.update({"G2E_SCALE_ALL_HAZARDS": "1", "G2E_ADAPTIVE_LEVEL": "1", "G2E_CATEGORY_LEVELS": "1", "G2E_LEVEL_START": "0", "G2E_RECORD_EVERY": "0"})
env.update(%(force)r)
g2_profile.set_environ(env)
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
E.CATEGORY_OVERRIDE = %(cats)r
e = E.OpenCatGymEnv(); e.set_ramp_steps(5e6)
rows = []
for k in range(%(episodes)d):
    seed = 11000 + k
    np.random.seed(seed); e.reset(seed=seed)
    robot = e.robot_id
    skip = (robot, e._payload_id, e._head_id, e._rear_id)
    p.performCollisionDetection()
    pen, gap, others = 0.0, 9.0, 0
    ground = e._plane_id
    for o in range(p.getNumBodies()):
        oid = p.getBodyUniqueId(o)
        if oid in skip:
            continue
        for c in p.getClosestPoints(robot, oid, 0.05):
            if oid == ground:
                gap = min(gap, c[8])
            pen = min(pen, c[8])
            if oid != ground and c[8] < -0.005:
                others += 1                                            # an obstacle overlapping the robot at the start
    float_n = sunk_n = bodies = 0
    statics = [p.getBodyUniqueId(o) for o in range(p.getNumBodies())]
    statics = [b for b in statics if b not in skip and p.getDynamicsInfo(b, -1)[0] == 0.0]          # the plane/heightfield and the static scenery (obstacles, rubble, snags, ledge blocks)
    for oid in statics:
        if oid == ground:
            continue
        bodies += 1
        dmin, deep = 9.0, 0.0
        for other in statics:
            if other == oid:
                continue
            for c in p.getClosestPoints(oid, other, 0.1):
                dmin = min(dmin, c[8])
                if other == ground:
                    deep = min(deep, c[8])
        if dmin > 0.015:
            float_n += 1                                               # nothing within 1.5 cm underneath or beside it: it hangs in the air
        if deep < -0.02:
            sunk_n += 1                                                # pushed more than 2 cm into the floor
    rows.append({"seed": seed, "pen_cm": pen * 100, "hover_cm": (gap * 100 if gap < 9 else None), "overlap_other": others, "bodies": bodies, "floating": float_n, "sunk": sunk_n})
print("SCENE " + json.dumps(rows))
'''

SCENE_CONFIGS = {                  # name -> (forced generator settings, pinned categories)
    "rough heightfield": ({"G2E_ROUGH_TERRAIN_PROB": "1.0"}, {"terrain": 1.0}),
    "rubble": ({"G2E_RUBBLE_PROB": "1.0", "G2E_ROUGH_TERRAIN_PROB": "0"}, {"terrain": 1.0}),
    "snag obstacles": ({"G2E_SNAG_OBSTACLE_PROB": "1.0", "G2E_ROUGH_TERRAIN_PROB": "0"}, {"terrain": 1.0}),
    "box obstacles": ({"G2E_RANDOM_TERRAIN": "0.05", "G2E_ROUGH_TERRAIN_PROB": "0"}, {"terrain": 1.0}),
    "ledge": ({"G2E_LEDGE_PROB": "1.0"}, {"ledge": 1.0}),
    "surface transition": ({"G2E_SURFACE_TRANSITION_PROB": "1.0", "G2E_ROUGH_TERRAIN_PROB": "0"}, {"ledge": 1.0}),
    "slope": ({"G2E_ROUGH_TERRAIN_PROB": "0"}, {"slope": 1.0}),
    "everything": ({"G2E_SNAG_OBSTACLE_PROB": "1.0", "G2E_LEDGE_PROB": "1.0", "G2E_SURFACE_TRANSITION_PROB": "1.0", "G2E_RUBBLE_PROB": "1.0"}, {"terrain": 1.0, "ledge": 1.0, "slope": 1.0}),
}


def scene(a):
    levels = [float(x) for x in a.levels.split(",")]
    print(f"{'generator':20s} {'lvl':>4s} {'n':>4s} | in ground >1cm | hover p50/p95/max cm | overlaps an obstacle | floating obj | sunk obj")
    allrows = {}
    for name, (force, cats) in SCENE_CONFIGS.items():
        for lv in levels:
            code = SCENE_CHILD % {"here": HERE, "force": force, "cats": {c: v * lv for c, v in cats.items()}, "episodes": a.episodes}
            r = subprocess.run([sys.executable, "-c", code], cwd=HERE, capture_output=True, text=True, timeout=3600)
            rows = None
            for line in r.stdout.splitlines():
                if line.startswith("SCENE "):
                    rows = json.loads(line[6:])
            if rows is None:
                print(f"{name:20s} {lv:4.2f} FAILED {r.stderr[-300:]}")
                continue
            allrows[f"{name}@{lv}"] = rows
            n = len(rows)
            hov = [x["hover_cm"] for x in rows if x["hover_cm"] is not None]
            print(f"{name:20s} {lv:4.2f} {n:4d} | {sum(x['pen_cm'] < -1.0 for x in rows) / n:13.1%} | {pct(hov, .5):5.1f} {pct(hov, .95):5.1f} {max(hov) if hov else float('nan'):5.1f} | {sum(x['overlap_other'] > 0 for x in rows) / n:19.1%} | {sum(x['floating'] > 0 for x in rows) / n:12.1%} | {sum(x['sunk'] > 0 for x in rows) / n:8.1%}", flush=True)
    os.makedirs("trained", exist_ok=True)
    json.dump(allrows, open("trained/passability_scene.json", "w"))
    print("saved trained/passability_scene.json")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("geometry")
    g.add_argument("--levels", default="1.0,1.25")
    g.add_argument("--episodes", type=int, default=300)
    g.add_argument("--cats", default="terrain,ledge,slope,combo")
    sc = sub.add_parser("scene")
    sc.add_argument("--levels", default="1.0,1.25")
    sc.add_argument("--episodes", type=int, default=200)
    c = sub.add_parser("capability")
    c.add_argument("--policies", default="trained/Release_CandidateV2.1_ppo,trained/v3_k3_ppo,trained/v3_20m_ppo")
    c.add_argument("--families", default="sidehill,uphill,downhill,ledge")
    c.add_argument("--episodes", type=int, default=20)
    c.add_argument("--jobs", type=int, default=6)
    c.add_argument("--wait-idle", action="store_true")
    a = ap.parse_args()
    if a.cmd == "geometry":
        geometry(a)
    elif a.cmd == "scene":
        scene(a)
    elif a.cmd == "capability":
        capability(a)


if __name__ == "__main__":
    main()
