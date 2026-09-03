"""Score the H1 head-to-head from measured numbers -> comparison table + verdict.

Enter what you measured on the robot (per the rubric in
docs/rl-runs/h1-head-to-head-rubric.md). This just does the bookkeeping and
applies the decision rule -- no measurement, no simulation.

    python pi_pipeline/gait/h1_score.py --from runs.json
    python pi_pipeline/gait/h1_score.py --template > runs.json    # blank sheet to fill in

runs.json shape:
{
  "session": "2026-09-15 carpet + floor",
  "conditions": {
    "C1": {"SCR": {"speed": 0.11, "heading_deg": 3, "falls": 0, "n": 5, "gait": 3},
           "RL":  {"speed": 0.10, "heading_deg": 1, "falls": 0, "n": 5, "gait": 3}},
    "C3": {"SCR": {"speed": 0.0,  "heading_deg": 0, "falls": 5, "n": 5, "gait": 0},
           "RL":  {"speed": 0.08, "heading_deg": 2, "falls": 1, "n": 5, "gait": 2}}
  },
  "recovery_C6": {"SCR": 0.2, "RL": 0.5},          # fraction of staggers caught
  "can_do": {"speed_command": true, "stand": true, "backward": true, "heading_hold": true},
  "notes": ""
}
Any missing field is treated as "not measured" and skipped.
"""
from __future__ import annotations

import argparse
import json
import sys

EVERYDAY = ("C1", "C2", "C3")   # conditions where RL falling more than SCR is disqualifying
BETTER_METRICS = ("speed", "heading_deg", "gait", "recovery")  # need RL clearly better on >=2


def _cmp(cid, m, scr, rl):
    """-> ('RL' | 'SCR' | 'tie' | None, human string). Lower is better for heading_deg."""
    a, b = scr.get(m), rl.get(m)
    if a is None or b is None:
        return None, "     —"
    if m == "heading_deg":
        a, b = abs(a), abs(b)
        win = "RL" if b < a - 0.5 else "SCR" if a < b - 0.5 else "tie"
    elif m == "falls":
        fa = a / max(1, scr.get("n", 1)); fb = b / max(1, rl.get("n", 1))
        win = "RL" if fb < fa - 1e-9 else "SCR" if fa < fb - 1e-9 else "tie"
        return win, f"{fa:.0%} vs {fb:.0%}"
    else:  # speed, gait, recovery -- higher better
        win = "RL" if b > a * 1.10 else "SCR" if a > b * 1.10 else "tie"
    return win, f"{a:g} vs {b:g}"


def score(d):
    conds = d.get("conditions", {})
    rows = []
    rl_better_metrics, rl_worse_falls_everyday = set(), []
    for cid in sorted(conds):
        scr = conds[cid].get("SCR", {}); rl = conds[cid].get("RL", {})
        for m in ("speed", "heading_deg", "gait", "falls"):
            win, s = _cmp(cid, m, scr, rl)
            rows.append((cid, m, s, win or ""))
            if win == "RL" and m in BETTER_METRICS:
                rl_better_metrics.add(m)
            if m == "falls" and win == "SCR" and cid in EVERYDAY:
                rl_worse_falls_everyday.append(cid)

    rec = d.get("recovery_C6", {})
    if "SCR" in rec and "RL" in rec:
        win = "RL" if rec["RL"] > rec["SCR"] * 1.10 else "SCR" if rec["SCR"] > rec["RL"] * 1.10 else "tie"
        rows.append(("C6", "recovery", f"{rec['SCR']:.0%} vs {rec['RL']:.0%}", win))
        if win == "RL":
            rl_better_metrics.add("recovery")

    can = d.get("can_do", {})
    can_col = all(can.get(k) for k in ("speed_command", "stand", "backward", "heading_hold")) if can else None

    # verdict
    if rl_worse_falls_everyday:
        verdict = ("FALL BACK to firmware", f"RL falls more than SCR on everyday "
                   f"condition(s): {', '.join(rl_worse_falls_everyday)}.")
    elif len(rl_better_metrics) >= 2 and can_col:
        verdict = ("KEEP building on RL", f"RL clearly better on "
                   f"{sorted(rl_better_metrics)}, no new falls, and delivers the "
                   f"command interface SCR can't.")
    elif len(rl_better_metrics) >= 2 and can_col is None:
        verdict = ("KEEP (pending 'can-do' check)", f"RL better on {sorted(rl_better_metrics)} "
                   f"with no new falls; fill in can_do to confirm.")
    else:
        verdict = ("MIDDLE — one sysid pass + targeted retrain, then re-run H1",
                   "RL transfers but isn't clearly better than SCR on enough axes. "
                   "Run sysid_replay.py, retrain against the corrected model, re-run H1 once.")
    return rows, verdict, sorted(rl_better_metrics), can_col


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="src", help="runs.json")
    ap.add_argument("--template", action="store_true")
    args = ap.parse_args()

    if args.template:
        json.dump({
            "session": "", "conditions": {c: {"SCR": {}, "RL": {}} for c in
                          ("C1", "C2", "C3", "C4", "C5")},
            "recovery_C6": {"SCR": None, "RL": None},
            "can_do": {"speed_command": None, "stand": None, "backward": None, "heading_hold": None},
            "notes": "",
        }, sys.stdout, indent=2)
        print()
        return

    if not args.src:
        ap.error("give --from runs.json (or --template for a blank one)")
    d = json.load(open(args.src))
    rows, (call, why), better, can_col = score(d)

    print(f"\nH1 head-to-head — {d.get('session','(no session label)')}\n")
    print(f"  {'cond':<5} {'metric':<11} {'SCR vs RL':<16} winner")
    print("  " + "-" * 44)
    for cid, m, s, win in rows:
        print(f"  {cid:<5} {m:<11} {s:<16} {win}")
    print()
    print(f"  RL clearly better on: {better or '(nothing)'}")
    print(f"  'can-do' column (speed cmd / stand / backward / heading-hold): "
          f"{'yes' if can_col else 'no' if can_col is False else 'not filled in'}")
    print(f"\n  VERDICT: {call}\n  {why}\n")


if __name__ == "__main__":
    main()
