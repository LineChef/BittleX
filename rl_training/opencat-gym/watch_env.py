"""Environment exports for the viewers (watch_v3.sh): `python watch_env.py <tag>` prints `export K=V; ...` for the shell to eval.

It is the run's own training environment, from the same function the training launch uses (g2_profile.env_for_job on the run's queue job), so what you watch is generated exactly
as it is in training: no calm mode, no omitted hazards, no fixed difficulty. The levels and the ramp position follow the run (watch_trained.py reads them live).
"""
import json
import os
import sys

import g2_profile as G

tag = sys.argv[1] if len(sys.argv) > 1 else "v3_20m"
queue = json.load(open("trained/v3_queue.json"))
jobs = queue if isinstance(queue, list) else queue.get("jobs", queue)
job = next((j for j in jobs if j.get("tag") == tag), None)
if job is None:
    sys.exit(f"{tag} is not a job in trained/v3_queue.json; the viewer needs the run's job to build its exact training environment")
if job.get("levers") == "K3":
    job = dict(job, levers=json.load(open("trained/v3_results.json"))["v3_k3"]["levers"])
print("; ".join(f"export {k}={v}" for k, v in G.env_for_job(job).items()))
