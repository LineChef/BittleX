"""Environment exports for the viewers (watch_v3.sh): `python watch_env.py <tag>` prints `export K=V; ...` for the shell to eval.

It is the run's own training environment, from the same function the training launch uses (g2_profile.env_for_job on the run's queue job), so what you watch is generated exactly
as it is in training: no calm mode, no omitted hazards, no fixed difficulty. The levels and the ramp position follow the run (watch_trained.py reads them live).
"""
import ast
import json
import os
import re
import sys

import g2_profile as G


def v4_env(tag):
    """The V4 screening runs and the V4 20M are launched by phase_v4.py, not from the V3 queue: rebuild their environment from the START line the runner logged
    (levers, seed, extra settings), the same way phase_v4.job_env does. None when the tag has no such line."""
    try:
        lines = open("trained/phase_v4.log", errors="replace").read().splitlines()
    except OSError:
        return None
    t = re.escape(tag)
    for ln in reversed(lines):
        m = re.search(rf"\] {t} START: levers (\[.*?\]) seed (\d+)(?: extra (\{{.*\}}))?\s*$", ln)
        if m:                                                                   # a 3M screen
            levers, seed, extra = ast.literal_eval(m.group(1)), m.group(2), (ast.literal_eval(m.group(3)) if m.group(3) else {})
            env = G.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(levers)})
            env.update({"G2E_SEED": seed})
            env.pop("G2E_PLATEAU_STOP", None)
            env.update(extra)
            return {k: v for k, v in env.items() if v != ""}
        m = re.search(rf"\] {t} START: the 20M with (\[.*?\])(?: (\{{.*?\}}))? \(plateau", ln)
        if m:                                                                   # the 20M
            levers, extra = ast.literal_eval(m.group(1)), (ast.literal_eval(m.group(2)) if m.group(2) else {})
            env = G.env_for_job({"kind": "final", "tag": tag, "fresh": True, "levers": list(levers)})
            env.update(extra)
            return {k: v for k, v in env.items() if v != ""}
    return None


tag = sys.argv[1] if len(sys.argv) > 1 else "v3_20m"
queue = json.load(open("trained/v3_queue.json"))
jobs = queue if isinstance(queue, list) else queue.get("jobs", queue)
job = next((j for j in jobs if j.get("tag") == tag), None)
if job is None:
    env = v4_env(tag)
    if env is None:
        sys.exit(f"{tag} is neither a job in trained/v3_queue.json nor a run in trained/phase_v4.log; the viewer needs the run's settings to build its exact training environment")
else:
    if job.get("levers") == "K3":
        job = dict(job, levers=json.load(open("trained/v3_results.json"))["v3_k3"]["levers"])
    env = G.env_for_job(job)
print("; ".join(f"export {k}={v}" for k, v in env.items()))
