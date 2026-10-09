"""Probe candidate BASE gaits in the sim, with no policy and no training (user, 2026-10-09: "probe foot clearance ... using the high-step as the base comparison").

    ../../.venv/bin/python gait_probe.py wkf hsA hsB hsC [--episodes 100] [--ladder-episodes 40] [--jobs 8]

Each name is a reference in reference_gait/<name>_ref.npy (wkf = the scripted walk; build variants with build_highstep_reference.py / build_symmetric_reference.py). The base gait is
played open loop (the scripted walk with that reference) through a subset of benchmark V5: flat, the 12.5 s calm walk, downhill, 5 deg cross-slope, rubble, boxes, a 15 mm random ledge,
and the step-up / step-down size ladders at the 30 mm tops. It prints foot clearance, calm-walk roll and heading, falls per cell and the ledge ladders (falls | success) side by side."""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CELLS = "T1.1,N1,T2.1,T3.1,T6.1,T7.1,T5.1"


def child(name: str, episodes: int, ladder_episodes: int, jobs: int, out: str) -> None:
    sys.path.insert(0, HERE)
    os.chdir(HERE)
    import benchmark_v4
    import benchmark_v5
    res = benchmark_v4.run("scripted", CELLS, episodes, 1000, jobs, None, (), None, mirror_gap=False, quiet=True)
    lad = benchmark_v5.run_ladder("scripted", (), ladder_episodes, jobs=jobs, hazards=["ledge_up", "ledge_down"], quiet=True)
    json.dump({"cells": res["cells"], "ladder": lad["summary"]}, open(out, "w"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--episodes", type=int, default=100)
    ap.add_argument("--ladder-episodes", type=int, default=40)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--child", help=argparse.SUPPRESS)
    ap.add_argument("--out", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.child:
        child(a.child, a.episodes, a.ladder_episodes, a.jobs, a.out)
        return
    if not a.names:
        ap.error("give at least one gait name")
    results = {}
    for n in a.names:
        out = os.path.join(HERE, "trained", f".gait_probe_{n}.json")
        env = dict(os.environ, G2E_V5_LEDGE_TOP="0.03")
        env.pop("G2E_SKILL_REF", None)
        if n != "wkf":
            env["G2E_SKILL_REF"] = n
        subprocess.run([sys.executable, __file__, "--child", n, "--out", out, "--episodes", str(a.episodes), "--ladder-episodes", str(a.ladder_episodes), "--jobs", str(a.jobs)],
                       env=env, check=True)
        results[n] = json.load(open(out))
        os.remove(out)
    print(f"{'gait':8s} {'clear90':>8s} {'roll':>5s} {'head':>5s}  " + " ".join(f"{c:>5s}" for c in CELLS.split(",") if c != "N1"))
    for n, r in results.items():
        c = {x["id"]: x for x in r["cells"]}
        print(f"{n:8s} {c['N1'].get('foot_clear_p90_mm', float('nan')):8.1f} {c['N1']['roll_std_deg']:5.1f} {c['N1']['heading_mean_deg']:+5.0f}  "
              + " ".join(f"{c[k]['fell_fraction']:5.2f}" for k in CELLS.split(",") if k != "N1"))
    print("\nledge ladders at 7.5 / 15 / 22.5 / 30 mm: falls | success")
    for n, r in results.items():
        for h in ("ledge_up", "ledge_down"):
            x = r["ladder"][h]
            print(f"  {n:8s} {h:10s} {[round(v, 2) for v in x['falls']]} | {[round(v, 2) for v in x['success']]}")


if __name__ == "__main__":
    main()
