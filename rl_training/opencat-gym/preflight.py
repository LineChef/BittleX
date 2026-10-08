"""One command that must PASS before a 20M is offered for the user's go (2026-10-08 training upgrade; docs/plan-detail/handoff-2026-10-08.md section 12).

    ../../.venv/bin/python preflight.py                 # the recipe phase_v4 adopted (trained/v4_results.json)
    ../../.venv/bin/python preflight.py --levers mirror,big_batch,frontier

Checks, in order (about 10-15 minutes on the native stack, Mac idle):
  1. the RL test suite (every test_*.py here)
  2. the job's environment: every G2E_ setting it sets is read by the env or the trainer; the hazard shares and bounds hold (a reset sample)
  3. the passability audit's geometry and scene checks on the job's own environment (no buried starts, no floating objects, no walls past the bounds)
  4. a 100k-step training smoke run of the exact job environment (curriculum updates and the monitor every 30k steps, episode recording on), then: no Python error in
     its log, the curriculum and health lines present, every recorded episode replays exactly, the checkpoint names land on 200k boundaries
Exit code 0 = PASS. The smoke run's files are deleted afterwards. Nothing here waits for a person.
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
SMOKE = "zz_preflight_smoke"


def step(name, ok, detail=""):
    print(f"[preflight] {'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)
    return ok


def job_env(levers, extra):
    sys.path.insert(0, HERE)
    import g2_profile
    env = g2_profile.env_for_job({"kind": "final", "tag": SMOKE, "fresh": True, "levers": list(levers)})
    env.update(extra or {})
    return {k: v for k, v in env.items() if v != ""}


def wiring(env):
    """Every G2E_ key the job sets must be read somewhere (a silently ignored setting is how G2E_ROUGH_TERRAIN_PROB went unnoticed)."""
    src = "".join(open(os.path.join(HERE, f)).read() for f in ("opencat_gym_env.py", "train.py", "mirror.py", "episode_recorder.py", "firmware_model.py", "priv_policy.py"))
    missing = []
    for k in env:
        if not k.startswith("G2E_"):
            continue
        stem = k[4:]
        if k not in src and not re.search(r'_g2e\(\s*"%s"' % re.escape(stem), src):
            missing.append(k)
    return missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--levers", default=None)
    ap.add_argument("--steps", default="1e5")
    a = ap.parse_args()
    if a.levers:
        levers, extra = a.levers.split(","), {}
    else:
        r = json.load(open(os.path.join(HERE, "trained/v4_results.json")))
        levers, extra = r["base"], r.get("base_extra", {})
    print(f"[preflight] recipe: levers {levers} {extra or ''}", flush=True)
    ok = True
    t = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:warnings"] + sorted(glob.glob(os.path.join(HERE, "test_*.py"))), cwd=HERE, capture_output=True, text=True)
    ok &= step("RL test suite", t.returncode == 0, t.stdout.strip().splitlines()[-1] if t.stdout.strip() else t.stderr[-300:])
    env = job_env(levers, extra)
    miss = wiring(env)
    ok &= step("every setting is read", not miss, f"unread: {miss}" if miss else f"{sum(k.startswith('G2E_') for k in env)} settings")
    for mode in ("geometry", "scene"):
        g = subprocess.run([PY, "passability_audit.py", mode, "--levels", "1.0,1.25", "--episodes", "40"] + (["--cats", "terrain,ledge,slope,combo"] if mode == "geometry" else []),
                           cwd=HERE, capture_output=True, text=True, timeout=3600)
        ok &= step(f"passability audit ({mode})", g.returncode == 0 and "FAILED" not in g.stdout, g.stdout.strip().splitlines()[-1] if g.stdout.strip() else g.stderr[-300:])
    # the smoke run
    for f in glob.glob(os.path.join(HERE, "trained", SMOKE + "*")) + glob.glob(os.path.join(HERE, "trained/checkpoints", SMOKE + "*")):
        shutil.rmtree(f) if os.path.isdir(f) else os.remove(f)
    senv = {**{k: v for k, v in os.environ.items() if not k.startswith("G2E_")}, **env,
            "G2E_PROBE_EVERY": "32768", "G2E_PROBE_EPISODES": "3", "G2E_MONITOR_EVERY": "30000", "G2E_RECORD_EVERY": "10",
            "G2E_RECORD_DIR": f"trained/{SMOKE}_episodes"}
    t0 = time.time()
    r = subprocess.run([PY, "train.py", "--tag", SMOKE, "--steps", a.steps], cwd=HERE, env=senv, capture_output=True, text=True, timeout=7200)
    logtxt = r.stdout + r.stderr
    open(os.path.join(HERE, "trained", SMOKE + "_console.log"), "w").write(logtxt)
    ok &= step("smoke run finished", r.returncode == 0 and os.path.exists(os.path.join(HERE, "trained", SMOKE + "_ppo.zip")),
               f"{(time.time() - t0) / 60:.1f} min" + ("" if r.returncode == 0 else f", exit {r.returncode}: {logtxt[-400:]}"))
    ok &= step("no Python error in the smoke log", "Traceback" not in logtxt)
    cur = "[frontier]" if env.get("G2E_FRONTIER") == "1" else "[probe]"
    ok &= step(f"curriculum lines ({cur}) present", cur in logtxt)
    ok &= step("health lines present", "[health]" in logtxt)
    ck = sorted(os.path.basename(p) for p in glob.glob(os.path.join(HERE, "trained/checkpoints", SMOKE + "_*_steps.zip")))
    ok &= step("checkpoints on 200k boundaries", all(int(re.search(r"_(\d+)_steps", c).group(1)) % 200_000 == 0 for c in ck), ", ".join(ck) or "none (run shorter than 200k)")
    sc = subprocess.run([PY, "-c", "import sys, json; sys.path.insert(0, '.'); import g2_profile, benchmark_v4 as B; lv = %r; "
                         "r = B.run('trained/%s_ppo', 'T1.1,N1,T5.2', 4, 1000, 4, None, tuple(l for l in lv if l in g2_profile.OBS_LEVERS), None, mirror_gap=True, quiet=True, "
                         "ladder=True, ladder_levers=tuple(lv), ladder_episodes=2); print('SCORED', len(r['cells']), r.get('mirror_gap') is not None, bool(r.get('ladder')))" % (list(levers), SMOKE)],
                        cwd=HERE, capture_output=True, text=True, timeout=3600)
    ok &= step("the benchmark scores this recipe's policy (cells, mirror gap, ladder)", "SCORED 3 True True" in sc.stdout, (sc.stdout + sc.stderr)[-300:] if "SCORED 3 True True" not in sc.stdout else "")
    w = subprocess.run([PY, "watch_training.py", SMOKE, "--headless"], cwd=HERE, capture_output=True, text=True, timeout=3600)
    n_ok, n_bad = w.stdout.count("REPLAY MATCHES"), w.stdout.count("DIFFERS")
    ok &= step("recorded episodes replay exactly", n_ok > 0 and n_bad == 0, f"{n_ok} match, {n_bad} differ")
    for f in glob.glob(os.path.join(HERE, "trained", SMOKE + "*")) + glob.glob(os.path.join(HERE, "trained/checkpoints", SMOKE + "*")):
        shutil.rmtree(f) if os.path.isdir(f) else os.remove(f)
    print(f"[preflight] {'ALL PASS' if ok else 'FAILED'}", flush=True)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
