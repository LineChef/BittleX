"""Pick the high-step creep's base gait by a sim parameter search (step 1 of docs/plan-detail/high-step-creep-training-plan.md). No training; every candidate is played open loop.

    ../../.venv/bin/python creep_sweep.py --v6-flat trained/hs_v6_baseline.json --out trained/hs_sweep.json      # writes reference_gait/creep_ref.npy (+ .json) for the winner

Round A (flat): each candidate of the grid walks `--flat-episodes` calm 20 s walks at the creep's command. It passes the gates only with
  no falls, rear paw lift >= REAR_LIFT_X x V6's, body height >= V6's, mean rear knee >= V6's - REAR_KNEE_SLACK deg, speed >= MIN_SPEED, and front paw lift >= FRONT_LIFT_X x V6's (the strictest of 1.5 / 1.25 / 1.0 that leaves a candidate).
Round B (step-ups): EVERY candidate that passed round A gets the step-up ladder (7.5 / 12.5 / 15 mm, 15 s); the winner has the best step-up score
  (mean over the sizes of success + all-four-up share - falls / 4). If nothing passes round A, the runner halts: the gates are not loosened silently.
  (2026-10-12, first run: sending only the 4 highest rear lifts to round B picked the most aggressive sway, which falls 80-100% at a step-up edge open loop; every passing
  candidate is scored on step-ups now.)
"""
import argparse
import itertools
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "reference_gait"))
import build_creep_reference as BC      # noqa: E402
import hs_probe as HP                   # noqa: E402

GRID = dict(sway=(12.0, 14.0, 16.0), lean=(0.0,), A=(12.0, 14.0, 16.0), Lr=(35.0, 42.0), Lf=(29.0, 32.0, 35.0))      # lean dropped and front knee lift added (2026-10-12: lean 8 won the first sweeps and halved the front lift)
FRONT_LIFT_X = (1.5, 1.35, 1.25)       # front paw lift >= this x V6's: the strictest level that leaves a passing candidate is used (and logged)
REAR_LIFT_X, REAR_KNEE_SLACK, MIN_SPEED = 2.0, 5.0, 0.025       # rear lift 2x V6's (2026-10-12: was 3x, which crowded out every gait whose front paws lift higher than V6's)
LEDGES = (0.0075, 0.0125, 0.015)
CMD = 0.035
NOM = 0.035


def cand_name(i):
    return f"zzcreep{i:02d}"


def ledge_score(summary):
    L = summary["ledges"]
    return sum(x["success"] + x["all_up"] - 0.25 * x["falls"] for x in L) / max(1, len(L))      # getting all four feet up counts most: training fixes falls, not clearance


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v6-flat", required=True, help="hs_probe JSON of V6 (its flat walk is the posture bar)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--flat-episodes", type=int, default=8)
    ap.add_argument("--ledge-episodes", type=int, default=20)
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    v6 = json.load(open(a.v6_flat))["flat"]
    bar = dict(rear_lift_mm=REAR_LIFT_X * v6["rear_lift_mm"], body_mm=v6["body_mm"], rear_knee_deg=v6["rear_knee_deg"] - REAR_KNEE_SLACK, speed=MIN_SPEED)
    keys = list(GRID)
    cands = [dict(zip(keys, vals)) for vals in itertools.product(*(GRID[k] for k in keys))]
    refdir = os.path.join(HERE, "reference_gait")
    names = []
    for i, c in enumerate(cands):
        BC.save(cand_name(i), c, refdir)
        names.append(cand_name(i))
    try:
        jl = [dict(kind="flat", size=0.0, episodes=a.flat_episodes, seconds=20.0, seed=7000, policy="scripted", env=HP.world_env([], n, NOM), cmd=CMD, cand=i)
              for i, n in enumerate(names)]
        parts = HP.run_jobs(jl, a.jobs, fresh=True)
        rows = []
        for i, (c, prt) in enumerate(zip(cands, parts)):
            f = HP.summarize([dict(kind="flat", size=0.0, recs=prt["recs"])])["flat"]
            ok = (f["falls"] == 0 and (f["rear_lift_mm"] or 0) >= bar["rear_lift_mm"] and (f["body_mm"] or 0) >= bar["body_mm"]
                  and (f["rear_knee_deg"] if f["rear_knee_deg"] is not None else -99) >= bar["rear_knee_deg"] and f["speed"] >= bar["speed"])
            ok_front = {x: bool(ok and (f["front_lift_mm"] or 0) >= x * v6["front_lift_mm"]) for x in FRONT_LIFT_X}
            rows.append(dict(i=i, params=c, flat=f, passes=bool(ok), ok_front=ok_front))
            print(f"A {i:02d} {c} | falls {f['falls']:.2f} speed {f['speed']:.3f} lift F {f['front_lift_mm'] or 0:.1f} R {f['rear_lift_mm'] or 0:.1f} body {f['body_mm'] or 0:.1f} "
                  f"knee {f['rear_knee_deg'] if f['rear_knee_deg'] is not None else float('nan'):+.1f} roll {f['roll_sd_deg'] or 0:.1f} | {'PASS' if ok else '-'}", flush=True)
        level = next((x for x in FRONT_LIFT_X if any(r["ok_front"][x] for r in rows)), None)
        passing = sorted([r for r in rows if level is not None and r["ok_front"][level]], key=lambda r: -r["flat"]["rear_lift_mm"])
        bar["front_lift_mm"], bar["front_lift_x"] = (level or 0) * v6["front_lift_mm"], level
        print(f"FRONT LIFT GATE: {level} x V6's front lift ({bar['front_lift_mm']:.1f} mm); {len(passing)} candidates pass", flush=True)
        out = dict(bar=bar, v6_flat=v6, grid=GRID, round_a=rows, round_b=[], winner=None)
        if not passing:
            json.dump(out, open(a.out, "w"), indent=1)
            print("NO CANDIDATE PASSED ROUND A", flush=True)
            sys.exit(2)
        fin = passing
        jl = []
        for r in fin:
            for s in LEDGES:
                for k in range(0, a.ledge_episodes, 10):
                    jl.append(dict(kind="ledge", size=s, episodes=min(10, a.ledge_episodes - k), seconds=15.0, seed=7500 + k, policy="scripted",
                                   env=HP.world_env([], names[r["i"]], NOM), cmd=CMD, cand=r["i"]))
        parts = HP.run_jobs(jl, a.jobs, fresh=True)
        for r in fin:
            mine = {}
            for job, prt in zip(jl, parts):
                if job["cand"] == r["i"]:
                    mine.setdefault(job["size"], []).extend(prt["recs"])
            summ = HP.summarize([dict(kind="ledge", size=s, recs=v) for s, v in mine.items()])
            r["ledges"], r["ledge_score"] = summ["ledges"], ledge_score(summ)
            out["round_b"].append(r)
            print(f"B {r['i']:02d} {r['params']} | score {r['ledge_score']:.3f} | " + " ".join(f"{L['size_mm']:g}:{L['success']:.2f}/{L['all_up']:.2f}/{L['falls']:.2f}" for L in summ["ledges"]),
                  flush=True)
        win = max(fin, key=lambda r: (r["ledge_score"], r["flat"]["rear_lift_mm"]))
        out["winner"] = win
        BC.save("creep", win["params"], refdir)
        json.dump(out, open(a.out, "w"), indent=1)
        print(f"WINNER {win['i']:02d} {win['params']} | step-up score {win['ledge_score']:.3f} | rear lift {win['flat']['rear_lift_mm']:.1f} mm -> reference_gait/creep_ref.npy", flush=True)
    finally:
        for n in names:
            for ext in ("_ref.npy", "_ref.json"):
                p = os.path.join(refdir, n + ext)
                if os.path.exists(p):
                    os.remove(p)


if __name__ == "__main__":
    main()
