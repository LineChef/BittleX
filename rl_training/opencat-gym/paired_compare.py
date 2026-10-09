"""Automated V3-vs-checkpoint paired comparison (overnight plan, 2026-10-09): when a run writes a checkpoint on a PAIR_EVERY boundary, copy it to a policy of its own and run the
full V3 vs V4 comparison on it (29 cells x 40 paired episodes, ladder, replays, report page), then print the count of cells that are significantly better / worse / the same.

    ../../.venv/bin/python paired_compare.py TAG LEVER,LEVER,... [EVERY_STEPS]      # runs until the trainer is gone

Per checkpoint: trained/<TAG>_at<N>M_ppo.zip, report in trained/v4_report_<TAG>_at<N>M/ , one line in trained/<TAG>_paired.jsonl. Resumable."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from math import comb

import phase_v4 as P


def mcnemar(x, y):
    n10 = sum(1 for p, q in zip(x, y) if p and not q)       # V3 fell, the checkpoint did not
    n01 = sum(1 for p, q in zip(x, y) if q and not p)
    n = n10 + n01
    if n == 0:
        return 1.0, n10, n01
    k = min(n10, n01)
    return min(1.0, sum(comb(n, i) for i in range(k + 1)) / 2 ** n * 2), n10, n01


def verdicts(name):
    d = f"trained/v4_report_{name}"
    a, b = json.load(open(f"{d}/v21.json")), json.load(open(f"{d}/final.json"))
    ca, cb = {c["id"]: c for c in a["cells"]}, {c["id"]: c for c in b["cells"]}
    better, worse, same, detail = [], [], [], {}
    for cid in ca:
        if cid not in cb:
            continue
        p, n10, n01 = mcnemar(ca[cid]["ep_fell"], cb[cid]["ep_fell"])
        v = "better" if (p < 0.05 and n10 > n01) else ("worse" if (p < 0.05 and n01 > n10) else "same")
        {"better": better, "worse": worse, "same": same}[v].append(cid)
        detail[cid] = dict(v3_fell=ca[cid]["fell_fraction"], fell=cb[cid]["fell_fraction"], v3_speed=ca[cid]["speed_mps"], speed=cb[cid]["speed_mps"], p=round(p, 4))
    return dict(better=better, worse=worse, same=len(same), mirror_gap=b.get("mirror_gap"), v3_mirror_gap=a.get("mirror_gap"), cells=detail)


def main(tag, levers, every=5_000_000):
    out = f"trained/{tag}_paired.jsonl"
    done = {json.loads(l)["step"] for l in open(out)} if os.path.exists(out) else set()
    while True:
        training = subprocess.run(["pgrep", "-f", f"[t]rain.py --tag {tag}"], capture_output=True).returncode == 0
        steps = sorted(int(m.group(1)) for f in os.listdir("trained/checkpoints") for m in [re.fullmatch(rf"{tag}_(\d+)_steps\.zip", f)] if m and int(m.group(1)) % every == 0)
        todo = [s for s in steps if s not in done and os.path.getmtime(f"trained/checkpoints/{tag}_{s}_steps.zip") < time.time() - 20]
        for s in todo:
            name = f"{tag}_at{s // 10**6}M"
            shutil.copy(f"trained/checkpoints/{tag}_{s}_steps.zip", f"trained/{name}_ppo.zip")
            P.compare_v3_v4(name, levers)
            v = verdicts(name)
            open(out, "a").write(json.dumps(dict(step=s, **v)) + "\n")
            done.add(s)
            print(f"[paired {s / 1e6:.0f}M] vs V3: {len(v['better'])} better {v['better']}, {len(v['worse'])} worse {v['worse']}, {v['same']} same | mirror gap {v['mirror_gap']} (V3 {v['v3_mirror_gap']}) | report trained/v4_report_{name}/v3_vs_v4_report.html", flush=True)
        if not training and not todo:
            break
        time.sleep(60)
    print("paired done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2].split(","), int(float(sys.argv[3])) if len(sys.argv) > 3 else 5_000_000)
