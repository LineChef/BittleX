"""Do the 0.2 in wide shoulders and CLpaw help? Stock legs against the new legs, in the arm world (user, 2026-11-01).

    python compare_legs.py score     # scores ARM1X and Petoi's scripted arm walk on STOCK legs with today's benchmark (the old numbers predate the snag / rubble ladder fix);
                                     # the new-legs rows come from phase_arm2.py's reports (trained/arm2_report/). Needs the Mac idle, about 25 min.
    python compare_legs.py table     # the comparison (printed and saved to trained/arm2_report/legs_compare.json)
    python compare_legs.py wait      # wait for "ARM2 COMPLETE" in trained/phase_arm2.log, then score and print the table

Three questions, each from runs that differ in one thing:
  1. The parts alone, same policy:   ARM1X on stock legs -> ARM1X on the new legs; Petoi's walk on stock -> on the new legs (no learning involved at all)
  2. The parts plus retraining:      ARM1X on stock legs (what runs today) -> ARM2 on the new legs
  3. What retraining adds:           ARM1X on the new legs -> ARM2 on the new legs
Every number is from the simulator: it has no model of servo load, heat or shaft side load on the wider track, so it cannot say the parts are safe, only whether they should help."""
import json
import os
import sys

import numpy as np

sys.path.insert(0, ".")
os.environ["G2_PAYLOAD_PROFILE"] = "arm"
os.environ.pop("G2_BUILD", None)                                    # stock legs for the scoring done here
import phase_armx as AX                                             # the stock-leg arm runner: its clean_environ / score / readers are the same code ARM1X was scored with
import phase_v5 as V5

R2 = "trained/arm2_report"
FILES = {
    "stock_scripted": f"{R2}/scripted_stock.json", "stock_arm1x": f"{R2}/arm1x_stock.json",
    "new_scripted": f"{R2}/scripted_newlegs.json", "new_arm1x": f"{R2}/arm1x_newlegs.json", "new_arm2": f"{R2}/arm2.json",
}
LABEL = {"stock_scripted": "Petoi's walk, stock legs", "stock_arm1x": "ARM1X, stock legs (today)", "new_scripted": "Petoi's walk, new legs",
         "new_arm1x": "ARM1X, new legs", "new_arm2": "ARM2, new legs"}


def score_stock():
    os.makedirs(R2, exist_ok=True)
    if not os.path.exists(FILES["stock_arm1x"]):
        print("scoring ARM1X on stock legs ...", flush=True)
        json.dump(AX.score("trained/armx_s4_avg5_ppo"), open(FILES["stock_arm1x"], "w"), indent=1)
    if not os.path.exists(FILES["stock_scripted"]):
        print("scoring Petoi's scripted arm walk on stock legs ...", flush=True)
        AX.clean_environ()
        json.dump(V5.score("scripted", [], AX.SCORE_EPISODES, AX.SCORE_LADDER_EPISODES), open(FILES["stock_scripted"], "w"), indent=1)


def metrics(res):
    c = AX.cm(res)["N1"]
    s = res["size_ladder"]["summary"]
    m = dict(flat_falls=AX.flat_falls(res), speed=c["path_speed_mps"], roll=c["roll_std_deg"], heading=c["heading_abs_mean_deg"],
             ladder_falls=AX.ladder(res)["falls"], ladder_success=AX.ladder(res)["success"])
    for h, v in s.items():
        m[f"{h}_success"] = float(np.mean(v["success"]))
        m[f"{h}_falls"] = float(v["mean_falls"])
    return m


# the hazards compared: snag and rubble ladder scores before 2026-11-01 are not comparable (the old ladder used one cable size at every rung), so the stock rows are rescored here
ORDER = [("flat_falls", "Flat-ground falls", "{:.2f}", False), ("speed", "Calm-walk speed (m/s)", "{:.3f}", True), ("roll", "Roll (deg, lower is steadier)", "{:.1f}", False),
         ("heading", "Heading drift (deg)", "{:.0f}", False), ("ladder_falls", "Falls over all hazards", "{:.3f}", False), ("ladder_success", "Success over all hazards", "{:.2f}", True)]


def table():
    have = {k: json.load(open(f)) for k, f in FILES.items() if os.path.exists(f)}
    M = {k: metrics(v) for k, v in have.items()}
    haz = sorted({k[:-8] for m in M.values() for k in m if k.endswith("_success") and k != "ladder_success"})
    rows = ORDER + [(f"{h}_success", f"{h.replace('_', ' ')}: success", "{:.2f}", True) for h in haz] + [(f"{h}_falls", f"{h.replace('_', ' ')}: falls", "{:.2f}", False) for h in haz]
    cols = [k for k in LABEL if k in M]
    out = {"labels": {k: LABEL[k] for k in cols}, "metrics": {k: M[k] for k in cols}, "comparisons": {}}
    print(f"{'':36s}" + "".join(f"{LABEL[k][:24]:>26s}" for k in cols))
    for key, name, fmt, up_good in rows:
        print(f"{name:36s}" + "".join(f"{(fmt.format(M[k][key]) if key in M[k] else '-'):>26s}" for k in cols))
    pairs = [("the parts alone, ARM1X", "stock_arm1x", "new_arm1x"), ("the parts alone, Petoi's walk", "stock_scripted", "new_scripted"),
             ("the parts plus retraining", "stock_arm1x", "new_arm2"), ("what retraining adds on the new legs", "new_arm1x", "new_arm2")]
    for name, a, b in pairs:
        if a in M and b in M:
            d = {key: M[b][key] - M[a][key] for key, *_ in rows if key in M[a] and key in M[b]}
            out["comparisons"][name] = d
            print(f"\n{name}: {LABEL[a]} -> {LABEL[b]}")
            for key, nm, fmt, up_good in rows:
                if key in d and abs(d[key]) >= 1e-9:
                    better = (d[key] > 0) == up_good
                    print(f"   {nm:34s} {d[key]:+.3f}  {'better' if better else 'worse'}")
    json.dump(out, open(f"{R2}/legs_compare.json", "w"), indent=1)
    return out


def wait():
    import time
    while "ARM2 COMPLETE" not in (open("trained/phase_arm2.log").read() if os.path.exists("trained/phase_arm2.log") else ""):
        time.sleep(60)
    score_stock()
    table()
    print("LEGS COMPARE COMPLETE", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "table"
    {"score": score_stock, "table": table, "wait": wait}[cmd]()
