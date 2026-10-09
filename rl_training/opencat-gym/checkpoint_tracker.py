"""Automated learning-curve tracker for a running 20M (2026-10-09, overnight plan): every time the run writes a checkpoint on a 1M boundary (STEP_EVERY), score it on the
calm walk (T1.1, N1: speed, falls, roll / pitch spread, asymmetry, heading drift, servo overload, mirror gap) and run the exposure probe on a fixed moderate course
(every hazard's frontier at bin 4, hazard episodes 7.5 s), the same for every checkpoint and run. One JSON line per checkpoint in trained/<tag>_curve.jsonl, one printed line each.

    ../../.venv/bin/python checkpoint_tracker.py [TAG [LEVER,LEVER,...]]    # runs until the trainer is gone, then scores what is left (levers default to the adopted recipe)

Resumable: a checkpoint already in the curve file is skipped. Nothing here stops or changes the run."""
import json
import os
import re
import subprocess
import sys
import time

import phase_v4 as P
import phase_v3 as V3

STEP_EVERY = 1_000_000
HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def env_for(tag):
    out = subprocess.run([PY, "watch_env.py", tag], capture_output=True, text=True, cwd=HERE).stdout
    return {m.group(1): m.group(2) for m in re.finditer(r"export (\w+)=([^;\n]*)", out)}


def probe(tag, step):
    env = dict(os.environ)
    env.update(env_for(tag))
    env.update({"G2E_HAZARD_EP_LEN": "600", "G2E_HAZARD_X_SCALE": "1.0"})      # the same 7.5 s test for every run, whatever the run trained with
    r = subprocess.run([PY, "exposure_probe.py", f"trained/checkpoints/{tag}_{step}_steps", tag, str(step), "60", "4"], capture_output=True, text=True, cwd=HERE, env=env)
    for ln in reversed(r.stdout.strip().splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)["focus"]
    return {}


def main(tag="v4_20m", levers=None):
    curve = f"trained/{tag}_curve.jsonl"
    done = {json.loads(l)["step"] for l in open(curve)} if os.path.exists(curve) else set()
    levers = levers or json.load(open(P.RESULTS))["base"]
    while True:
        training = subprocess.run(["pgrep", "-f", f"[t]rain.py --tag {tag}"], capture_output=True).returncode == 0
        steps = sorted(int(m.group(1)) for f in os.listdir("trained/checkpoints") for m in [re.fullmatch(rf"{tag}_(\d+)_steps\.zip", f)] if m and int(m.group(1)) % STEP_EVERY == 0)
        todo = [s for s in steps if s not in done and os.path.getmtime(f"trained/checkpoints/{tag}_{s}_steps.zip") < time.time() - 20]
        for s in todo:
            res = V3.score(f"trained/checkpoints/{tag}_{s}_steps", P.obs_levers(levers), spec="T1.1,N1", busy=True)
            m = V3.cellmap(res)
            n1 = m["N1"]
            row = dict(step=s, t1_falls=m["T1.1"]["fell_fraction"], n1_falls=n1["fell_fraction"], n1_speed=n1["speed_mps"], n1_roll_std=n1["roll_std_deg"], n1_pitch_std=n1["pitch_std_deg"],
                       n1_asym=n1["lr_asym_max_deg"], n1_heading=n1["heading_mean_deg"], n1_over=n1["servo_over_frac"], mirror_gap=res.get("mirror_gap"), exposure=probe(tag, s))
            open(curve, "a").write(json.dumps(row) + "\n")
            done.add(s)
            ex = row["exposure"]
            print(f"[curve {s / 1e6:.0f}M] N1 speed {row['n1_speed']:.3f} roll {row['n1_roll_std']:.1f} asym {row['n1_asym']:.1f} head {row['n1_heading']:+.0f} mirror {row['mirror_gap'] or 0:.3f} | "
                  f"fixed course, hazard episodes: past first object {ex.get('past_first', 0)}/{ex.get('with_objects', 0)}, past whole field {ex.get('past_whole_field', 0)}, fell {ex.get('fell', 0)}/{ex.get('episodes', 0)}", flush=True)
        if not training and not todo:
            break
        time.sleep(60)
    print("tracker done", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "v4_20m", sys.argv[2].split(",") if len(sys.argv) > 2 else None)
