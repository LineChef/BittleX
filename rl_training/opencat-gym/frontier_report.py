"""Where each hazard's frontier is in a frontier-curriculum run (opencat_gym_env FRONTIER; train.py FrontierCurriculum writes trained/<tag>_frontier.json every ~200k steps).

    ../../.venv/bin/python frontier_report.py <tag>

Per hazard: the frontier bin and its size range, the relative success of every bin with data (success / anchor success), how many outcomes each bin has, and whether a bin
is BLOCKED (a full window of outcomes with relative success < 5%: the automatic ceiling, sampled at a 2% floor). Read-only; nothing here changes the run.
"""
import json
import sys


def report(tag):
    s = json.load(open(f"trained/{tag}_frontier.json"))
    K = s["n_bins"]
    print(f"{tag}: {s['steps']:,} steps; anchor (hazard-free) success {s['anchor']:.2f}")
    for h, F in s["F"].items():
        bound = s["bound"][h]
        unit = "deg" if h in ("sidehill", "climb", "descent") else ("cm" if h.startswith("ledge") else "x level-1 size")
        k = 100.0 if unit == "cm" else 1.0
        cells = []
        for b, (succ, n) in enumerate(s["bins"][h]):
            if n:
                rel = succ / max(s["anchor"], 0.3) if s["anchor"] == s["anchor"] else succ
                flag = "F" if b == F else ("X" if s["blocked"].get(h) == b else " ")
                cells.append(f"{flag}{b}:{min(1.0, rel):.2f}/{n}")
        blk = s["blocked"].get(h)
        print(f"  {h:10s} frontier bin {F} = {F / K * bound * k:.3g}-{(F + 1) / K * bound * k:.3g} {unit}"
              + (f"; BLOCKED from {blk / K * bound * k:.3g} {unit}" if blk is not None else "") + "   " + "  ".join(cells))


if __name__ == "__main__":
    report(sys.argv[1])
