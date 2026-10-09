"""Final exam for the overnight candidates (2026-10-09): every finalist and V3 scored on all 29 benchmark cells with 100 paired episodes each (the nightly comparisons used 40, too few to
separate real differences from noise on edge cells such as the 10 deg side-hill), then each finalist's paired verdict against V3 (McNemar on the falls, p < 0.05) and a fall-rate table.

    ../../.venv/bin/python final_exam.py                  # waits for trained/v4_c2_ppo.zip, then scores V3 and the finalists below
Results: trained/final_exam/<name>.json and trained/final_exam/summary.json (not committed)."""
import json
import os
import sys
import time

EPISODES = 100
FINALISTS = [      # (name, policy path, levers the policy was trained with)
    ("c1_2.0M", "trained/checkpoints/v4_c1_2000000_steps", "stage2"),
    ("c1_2.2M", "trained/checkpoints/v4_c1_2200000_steps", "stage2"),
    ("c2_1.0M", "trained/checkpoints/v4_c2_1000000_steps", "stage2"),
    ("c2_2.0M", "trained/checkpoints/v4_c2_2000000_steps", "stage2"),
    ("c2_final", "trained/v4_c2_ppo", "stage2"),
]


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ".")
    import benchmark_v4
    import phase_v3 as V3
    import phase_v4 as P
    import paired_compare as C
    os.makedirs("trained/final_exam", exist_ok=True)
    while not os.path.exists("trained/v4_c2_ppo.zip"):
        time.sleep(30)
    jobs = [("V3", P.V3_POLICY, [])] + [(n, p, P.STAGE2_LEVERS) for n, p, _ in FINALISTS]
    for name, path, lv in jobs:
        f = f"trained/final_exam/{name}.json"
        if os.path.exists(f):
            continue
        saved = dict(os.environ)
        try:
            res = benchmark_v4.run(path, "all", EPISODES, 1000, V3.SCORE_JOBS, None, tuple(P.obs_levers(lv)), None, mirror_gap=True, quiet=True)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        json.dump(res, open(f, "w"), indent=1)
        print(f"[exam] scored {name}", flush=True)
    v3 = {c["id"]: c for c in json.load(open("trained/final_exam/V3.json"))["cells"]}
    summary = {}
    for name, _, _ in FINALISTS:
        r = json.load(open(f"trained/final_exam/{name}.json"))
        cells = {c["id"]: c for c in r["cells"]}
        better, worse = [], []
        for cid, c in v3.items():
            p, n10, n01 = C.mcnemar(c["ep_fell"], cells[cid]["ep_fell"])
            if p < 0.05:
                (better if n10 > n01 else worse).append(cid)
        summary[name] = dict(better=better, worse=worse, same=len(v3) - len(better) - len(worse), mirror_gap=r.get("mirror_gap"),
                             falls={cid: round(c["fell_fraction"], 3) for cid, c in cells.items()},
                             n1=dict(speed=cells["N1"]["speed_mps"], roll=cells["N1"]["roll_std_deg"], asym=cells["N1"]["lr_asym_max_deg"], heading=cells["N1"]["heading_mean_deg"]))
        print(f"[exam] {name}: {len(better)} better {better}, {len(worse)} worse {worse}, {summary[name]['same']} same | mirror {r.get('mirror_gap')}", flush=True)
    summary["V3"] = dict(falls={cid: round(c["fell_fraction"], 3) for cid, c in v3.items()}, mirror_gap=json.load(open("trained/final_exam/V3.json")).get("mirror_gap"))
    json.dump(summary, open("trained/final_exam/summary.json", "w"), indent=1)
    print("exam done", flush=True)


if __name__ == "__main__":
    main()
