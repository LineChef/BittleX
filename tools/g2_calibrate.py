#!/usr/bin/env python3
"""Calibration builder (Phase 3 of docs/rl/real-data-pipeline.md): turn the ingested real-hardware logs into a sim calibration snapshot.

    python tools/g2_calibrate.py build            # fit what the usable runs support, write the next numbered snapshot (never changes an old one)
    python tools/g2_calibrate.py status           # the current snapshot, the latest snapshot, and what blocks each
    python tools/g2_calibrate.py show [ID]        # one snapshot: every value, its range, its checks, the one-page diff against the profile
    python tools/g2_calibrate.py harm-check ID POLICY [POLICY ...]   # score the policies in the old and the new world (idle Mac only; slow)
    python tools/g2_calibrate.py reject PARAM [NOTE]    # a person refuses one parameter for good: still measured and reported, never applied (unreject PARAM undoes it)
    python tools/g2_calibrate.py approve ID       # a person approves (the only way a change beyond noise, or a first snapshot, goes live)
    python tools/g2_calibrate.py revert           # point "current" back at the previous snapshot
    (the g2cal alias)

Flow: `g2data` ingests the Pi's run logs -> this builder fits -> snapshot `~/g2_data/calibration/snapshots/NNNN.json` (immutable) -> approval -> `g2_profile` loads the
approved snapshot at launch (`current.json` is a pointer, so a revert is safe) and each run records the snapshot id (`G2_CAL_ID`).

What is fitted today (the "confident tier" that walk logs alone can support):
  G2E_IMU_HOLD_STEPS          control ticks per fresh IMU frame (loop rate / measured frame rate)
  G2E_CMD_PATH_EXTRA_MS_MAX   extra command-path delay: the loop's tick jitter (99th percentile tick minus the median tick), in ms
Reported as monitored statistics (targets for the sim-versus-real gap, not parameters): roll and pitch spread per floor, tick rate, IMU frame rate.
Needs data we do not have yet, so it is listed as "needs data" and never guessed: IMU bias and noise at rest (the rest-IMU recorder, Phase 1), servo rate and force
(the bench data), fall and snag rates (many more metres walked).

Guards (from the plan): a fixed WHITELIST of parameters, each with physical bounds; there is no yaw, heading, lateral or drift key (a test enforces it) and no fit reads yaw;
a minimum number of supporting runs and seconds; reproducibility (the median of the odd runs must agree with the median of the even runs); a drift-proxy screen (a per-run
estimate that tracks that run's heading change is dropped); only the current fit-ok hardware epoch is used; floors and pack-voltage bands are reported, never mixed away.
Approval is automatic, by statistical gates (user, 2026-10-08): all fit checks pass, the harm check passes, the hardware epoch is unchanged, and every value either stays within its own noise
or moves for real with strong evidence (20 runs, 120 s) and a modest size (at most 25% of the value it replaces). A failed harm check blocks the snapshot; anything else waits for a person
(`approve`); every automatic approval is logged in approvals.jsonl and `revert` undoes it.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import g2_ingest as ingest  # noqa: E402

DATA = os.path.expanduser(os.environ.get("G2_DATA_DIR", "~/g2_data"))
STORE = os.path.join(DATA, "store")
CAL = os.path.join(DATA, "calibration")
SNAPS = os.path.join(CAL, "snapshots")
GYM = os.path.join(ROOT, "rl_training", "opencat-gym")

# the whole list of parameters the builder may ever write: name -> (low, high, decimals, absolute tolerance for "the same value")
WHITELIST = {
    "G2E_IMU_HOLD_STEPS": (4, 40, 0, 1.0),
    "G2E_CMD_PATH_EXTRA_MS_MAX": (0.0, 30.0, 1, 1.0),
}
FORBIDDEN_WORDS = ("YAW", "HEADING", "DRIFT", "LATERAL", "TURN")           # a key containing one of these is never written
NEEDS_DATA = {
    "G2E_IMU_BIAS_DEG / G2E_RANDOM_GYRO": "IMU bias and noise at rest: needs the rest-IMU recorder (Phase 1)",
    "G2E_SERVO_RATE_LIMIT_DEG_S / G2E_MOTOR_FORCE": "servo rate and force: needs the bench servo data (sysid plan)",
    "fall and snag rates": "needs many more metres walked per floor",
}
MIN_RUNS = 10
MIN_SECONDS = 60.0
PROXY_RHO = 0.7               # a per-run estimate this correlated with that run's heading change is a drift proxy
PROXY_MIN_RUNS = 8
CUMULATIVE_CAP = 0.25         # relative change allowed since the last human-approved snapshot before a person must look


# ----------------------------------------------------------------------------------------------------------------------------------- per-run estimates

def read_run(path: str):
    """(header, rows) of a run log, plain or gzip."""
    if path.endswith(".gz"):
        with gzip.open(path, "rt", newline="") as f:
            text = [ln for ln in f if ln.strip() and not ln.startswith("#")]
        import csv
        rows = list(csv.reader(text))
        return (rows[0], rows[1:]) if rows else ([], [])
    return ingest.read_csv(path)


def run_estimates(head, rows) -> dict | None:
    """Per-run estimates from the steady window (after the stand): loop rate, IMU frame rate, tick jitter. Reads no yaw and no heading."""
    t = ingest.column(head, rows, "t")
    n = ingest.column(head, rows, "imu_n")
    if t is None or n is None or len(t) < 20:
        return None
    s = t >= t[0] + ingest.FIRST_SKIP_S
    if s.sum() < 20:
        return None
    ts, ns = t[s], n[s]
    dt = np.diff(ts)
    dt = dt[dt > 0]
    if len(dt) < 10 or not np.isfinite(ns).all():
        return None
    med = float(np.median(dt))
    span = float(ts[-1] - ts[0])
    fresh = float((np.diff(ns) > 0).sum() / span) if span > 0 else 0.0
    if fresh <= 0:
        return None
    jitter_ms = max(0.0, (float(np.percentile(dt, 99)) - med) * 1e3)
    return {"loop_hz": 1.0 / med, "imu_hz": fresh, "tick_median_ms": med * 1e3, "jitter_ms": jitter_ms, "seconds": span,
            "G2E_IMU_HOLD_STEPS": float(round((1.0 / med) / fresh)), "G2E_CMD_PATH_EXTRA_MS_MAX": jitter_ms}


def spearman(a, b) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return 0.0
    ra, rb = np.argsort(np.argsort(a)).astype(float), np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


# ----------------------------------------------------------------------------------------------------------------------------------- fitting

def fit_param(name: str, vals: list[float], seconds: float, proxy: list[float] | None = None, old: float | None = None) -> dict:
    """One parameter from per-run estimates: the median, its noise, and every check. `proxy` = each run's heading change (an audit input only)."""
    lo, hi, dec, tol = WHITELIST[name]
    v = np.asarray(vals, float)
    n = len(v)
    out: dict = {"n_runs": n, "seconds": round(seconds, 1), "checks": [], "old": old}
    if n == 0:
        out.update(status="needs data", reason="no usable run")
        return out
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) * 1.4826
    noise = max(2.0 * mad / math.sqrt(n), tol / 2.0)
    out.update(median=round(med, 3), noise=round(noise, 3))
    out["checks"].append(["enough runs", n >= MIN_RUNS, f"{n} runs (need {MIN_RUNS})"])
    out["checks"].append(["enough seconds", seconds >= MIN_SECONDS, f"{seconds:.0f} s (need {MIN_SECONDS:.0f})"])
    if n >= 4:
        a, b = float(np.median(v[0::2])), float(np.median(v[1::2]))
        ok = abs(a - b) <= max(noise * 2.0, tol)
        out["checks"].append(["reproducible (odd runs vs even runs)", ok, f"{a:.2f} vs {b:.2f}"])
    else:
        out["checks"].append(["reproducible (odd runs vs even runs)", False, "too few runs to split"])
    value = min(max(med, lo), hi)
    out["checks"].append(["inside physical bounds", lo <= med <= hi, f"{med:.2f} in [{lo}, {hi}]"])
    if proxy is not None and n >= PROXY_MIN_RUNS and len(proxy) == n:
        rho = spearman(v, proxy)
        out["checks"].append(["not a drift proxy", abs(rho) < PROXY_RHO, f"rank correlation with each run's heading change {rho:+.2f} (limit {PROXY_RHO})"])
    out["value"] = round(value, dec) if dec else int(round(value))
    failed = [c[0] for c in out["checks"] if not c[1]]
    out["status"] = "ok" if not failed else "insufficient"
    if failed:
        out["reason"] = "failed: " + ", ".join(failed)
    if old is not None and out["status"] == "ok":
        out["changed"] = abs(float(out["value"]) - float(old)) > 1e-9
        out["within_noise"] = abs(float(out["value"]) - float(old)) <= noise
    return out


def profile_value(name: str) -> float | None:
    """What the profile uses today for `name` (RECIPE + CALIBRATION), read without importing the training code."""
    try:
        sys.path.insert(0, GYM)
        import g2_profile
        v = {**g2_profile.RECIPE, **g2_profile.CALIBRATION}.get(name)
        return None if v is None else float(v)
    except Exception:  # noqa: BLE001
        return None
    finally:
        if GYM in sys.path:
            sys.path.remove(GYM)


def current_epoch(manifest: dict, epochs: dict) -> str | None:
    """The newest hardware epoch that is fit_ok and has runs."""
    have = {r["epoch"] for r in manifest["runs"]}
    ok = [e for e in epochs.values() if e.get("fit_ok") and e["id"] in have]
    return max(ok, key=lambda e: e["start"])["id"] if ok else None


def build(manifest: dict, store: str | None = None, epochs: dict | None = None, old_values=None) -> dict:
    store = store or STORE
    old_values = old_values or profile_value
    epochs = epochs if epochs is not None else ingest.load_epochs()
    epoch = current_epoch(manifest, epochs)
    runs = [r for r in manifest["runs"] if r["status"] == "usable" and r["epoch"] == epoch]
    per: dict[str, list] = {k: [] for k in WHITELIST}
    proxy: list[float] = []
    secs, used = 0.0, 0
    for r in runs:
        path = os.path.join(store, r["day"], r["run"] + ".csv.gz")
        if not os.path.isfile(path):
            continue
        est = run_estimates(*read_run(path))
        if est is None:
            continue
        used += 1
        secs += est["seconds"]
        for k in WHITELIST:
            per[k].append(est[k])
        proxy.append(float((r["metrics"].get("monitor") or {}).get("yaw_change_deg", 0.0)))         # an audit input only; never a fit input
    params = {k: fit_param(k, per[k], secs, proxy, old_values(k)) for k in WHITELIST}
    for k, why in read_rejected().items():          # refused by a person: measured and reported, never applied
        if k in params:
            params[k] = dict(params[k], status="rejected", reason=f"rejected by the user on {why.get('at', '?')}" + (f": {why['note']}" if why.get("note") else ""))
    monitor: dict = {}
    for r in runs:
        g = monitor.setdefault(r["surface"], {"runs": 0, "seconds": 0.0, "roll": [], "pitch": []})
        g["runs"] += 1
        g["seconds"] += r["metrics"].get("steady_s", 0.0)
        g["roll"].append(r["roll_std_deg"]), g["pitch"].append(r["pitch_std_deg"])
    monitor = {s: {"runs": g["runs"], "seconds": round(g["seconds"], 1), "roll_std_deg": round(float(np.nanmedian(g["roll"])), 2),
                   "pitch_std_deg": round(float(np.nanmedian(g["pitch"])), 2)} for s, g in monitor.items()}
    allruns = [r for r in manifest["runs"] if r["epoch"] == epoch]
    walked = sum(r["metrics"].get("duration_s", 0.0) for r in allruns)
    falls = sum(1 for r in allruns if r.get("end_reason") == "fall")
    snap = {"epoch": epoch, "made": time.strftime("%Y-%m-%dT%H:%M:%S"), "runs_total": len(manifest["runs"]), "runs_used": used, "seconds_used": round(secs, 1),
            "params": params, "env": {k: str(p["value"]) for k, p in params.items() if p.get("status") == "ok"},
            "monitor": monitor, "events": {"falls": falls, "walked_s": round(walked, 1), "falls_per_walked_hour": round(falls / walked * 3600, 2) if walked else None},
            "needs_data": NEEDS_DATA, "harm_check": {"status": "not run"}, "drift_canary": {"status": "not run"}}
    return snap


def rejected_path() -> str:
    return os.path.join(CAL, "rejected.json")


def read_rejected() -> dict:
    """Parameters a person has refused: {name: {"value": ..., "at": ..., "note": ...}}. They are never written into a snapshot's env until `g2cal unreject`."""
    try:
        return json.load(open(rejected_path()))
    except (OSError, ValueError):
        return {}


def reject(name: str, note: str = "", value=None) -> None:
    if name not in WHITELIST:
        raise ValueError(f"{name} is not a calibration parameter")
    r = read_rejected()
    r[name] = {"value": value, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "note": note}
    os.makedirs(CAL, exist_ok=True)
    json.dump(r, open(rejected_path(), "w"), indent=1)


def unreject(name: str) -> None:
    r = read_rejected()
    r.pop(name, None)
    json.dump(r, open(rejected_path(), "w"), indent=1)


def check_whitelist(env: dict) -> None:
    for k in env:
        if k not in WHITELIST or any(w in k.upper() for w in FORBIDDEN_WORDS):
            raise ValueError(f"{k} is not an allowed calibration key")


# ----------------------------------------------------------------------------------------------------------------------------------- harm check

def evaluate_harm(base: dict, cand: dict, speed_tol: float = 0.10, mirror_tol: float = 0.02) -> dict:
    """Compare two benchmark results (the policy scored in the old world and in the snapshot world): flat-ground falls must not rise, the mirror gap must not
    worsen, and no cell may drop beyond its noise (falls: two binomial standard errors plus one episode; speed: more than `speed_tol` of the old speed)."""
    problems = []
    b = {c["id"]: c for c in base["cells"]}
    for c in cand["cells"]:
        o = b.get(c["id"])
        if o is None:
            continue
        n = max(1, int(c.get("n") or c.get("episodes") or 1))
        p0 = float(o.get("fell_fraction") or 0.0)
        se = math.sqrt(max(p0 * (1 - p0), 0.0) / n)
        rise = float(c.get("fell_fraction") or 0.0) - p0
        if c.get("tag") == "gate" and rise > 1e-9:
            problems.append(f"{c['id']}: flat-ground falls rose {p0:.3f} -> {c.get('fell_fraction'):.3f}")
        elif rise > 2 * se + 1.0 / n:
            problems.append(f"{c['id']}: falls rose {p0:.3f} -> {c.get('fell_fraction'):.3f} (beyond noise)")
        s0, s1 = o.get("speed_mps"), c.get("speed_mps")
        if s0 and s1 is not None and s0 > 0 and (s0 - s1) / s0 > speed_tol:
            problems.append(f"{c['id']}: speed fell {s0:.3f} -> {s1:.3f}")
    mg0, mg1 = base.get("mirror_gap"), cand.get("mirror_gap")
    if mg0 is not None and mg1 is not None and mg1 - mg0 > mirror_tol:
        problems.append(f"mirror gap worsened {mg0:.3f} -> {mg1:.3f}")
    return {"status": "failed" if problems else "passed", "problems": problems}


def busy_processes() -> list[str]:
    """Other jobs that would be slowed by a benchmark (the harm check runs only on an idle Mac): 'script (pid N)' for each."""
    import re
    import subprocess
    out = subprocess.run(["ps", "-axo", "pid,command"], capture_output=True, text=True).stdout.splitlines()
    me = os.getpid()
    found = []
    for ln in out:
        m = re.search(r"\b(train\.py|benchmark_\w+\.py|phase_v3\.py)\b", ln)
        pid = ln.split(None, 1)[0] if ln.strip() else ""
        if m and pid.isdigit() and int(pid) != me and "g2_calibrate" not in ln:
            found.append(f"{m.group(1)} (pid {pid})")
    return found


def default_policies() -> list[str]:
    """The policies a calibration must not harm: the frozen V2.1 reference and the newest V3 run's final policy, if there is one (G2_CAL_POLICIES overrides)."""
    env = os.environ.get("G2_CAL_POLICIES")
    if env:
        return [p.strip() for p in env.split(",") if p.strip()]
    out = ["trained/Release_CandidateV2.1_ppo"]
    for cand in ("trained/v3_20m_ppo",):
        if os.path.exists(os.path.join(GYM, cand + ".zip")):
            out.append(cand)
    return out


def run_harm_check(snap: dict, policies: list[str], episodes: int = 24, jobs: int = 8) -> dict:
    """Score each policy in the current world and in the snapshot world with the V3 scorer (benchmark_v4); the verdict is the worst of the policies."""
    busy = busy_processes()
    if busy:
        raise RuntimeError("the Mac is not idle (the harm check never competes with a training run or a benchmark): " + "; ".join(busy[:3]))
    sys.path.insert(0, GYM)
    os.chdir(GYM)
    import benchmark_v4
    saved = dict(os.environ)
    results, problems, verdict = {}, [], "passed"
    try:
        for p in policies:
            base = benchmark_v4.run(p, "all", episodes, 1000, jobs, None, (), None, mirror_gap=True, quiet=True, extra_env=None)
            cand = benchmark_v4.run(p, "all", episodes, 1000, jobs, None, (), None, mirror_gap=True, quiet=True, extra_env=snap["env"])
            r = evaluate_harm(base, cand)
            results[p] = r
            if r["status"] != "passed":
                verdict = "failed"
                problems += [f"{os.path.basename(p)}: {x}" for x in r["problems"]]
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return {"status": verdict, "problems": problems, "policies": results, "episodes": episodes, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}


# ----------------------------------------------------------------------------------------------------------------------------------- snapshots and approval

def _path(*a) -> str:
    return os.path.join(CAL, *a)


def list_ids(snaps_dir: str | None = None) -> list[int]:
    d = snaps_dir or SNAPS
    return sorted(int(f[:-5]) for f in os.listdir(d) if f.endswith(".json") and f[:-5].isdigit()) if os.path.isdir(d) else []


def load_snapshot(i: int) -> dict:
    return json.load(open(os.path.join(SNAPS, f"{i:04d}.json")))


def save_snapshot(snap: dict) -> int:
    check_whitelist(snap["env"])
    os.makedirs(SNAPS, exist_ok=True)
    ids = list_ids()
    i = (ids[-1] + 1) if ids else 1
    snap = dict(snap, id=i)
    path = os.path.join(SNAPS, f"{i:04d}.json")
    with open(path + ".tmp", "w") as f:
        json.dump(snap, f, indent=1)
    os.replace(path + ".tmp", path)
    os.chmod(path, 0o444)                                                       # immutable: harm-check results go in their own file
    return i


def harm_path(i: int) -> str:
    return _path("harm", f"{i:04d}.json")


def harm_status(i: int) -> dict:
    try:
        return json.load(open(harm_path(i)))
    except (OSError, ValueError):
        return {"status": "not run"}


def read_current() -> int | None:
    try:
        return int(json.load(open(_path("current.json")))["id"])
    except (OSError, ValueError, KeyError):
        return None


def write_current(i: int | None, how: str, who: str) -> None:
    os.makedirs(CAL, exist_ok=True)
    with open(_path("approvals.jsonl"), "a") as f:
        f.write(json.dumps({"id": i, "how": how, "who": who, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}) + "\n")
    with open(_path("current.json.tmp"), "w") as f:
        json.dump({"id": i}, f)
    os.replace(_path("current.json.tmp"), _path("current.json"))


# The statistical gates that decide approval (user, 2026-10-08: "make the approval automatic based on statistical gates"; before that the first snapshot and every change beyond noise waited for a person).
CHANGE_MIN_RUNS = 20          # a value that actually moves needs more evidence than one that stays: runs ...
CHANGE_MIN_SECONDS = 120.0    # ... and seconds of steady walking behind it
CHANGE_MAX_RELATIVE = CUMULATIVE_CAP     # and a modest size: at most this fraction of the value it replaces (the profile's value, or the last human-approved snapshot's)


def decide(snap: dict, last_human: dict | None, current: dict | None = None) -> tuple[str, list[str]]:
    """'auto_approved' | 'needs_user' | 'blocked' | 'pending harm check' | 'empty', with the reasons. A snapshot is approved by the rules when ALL gates hold:
      1. every parameter in it passed its own fit checks (enough runs and seconds, reproducible, in bounds, not a drift proxy);
      2. the harm check passed (flat-ground falls not up, mirror gap not worse, no benchmark cell worse beyond noise); a failed one BLOCKS the snapshot;
      3. the hardware epoch is the same as the approved snapshot's (a hardware change always goes to a person);
      4. each value either stays within its own noise of the value it replaces, or moves for real (beyond noise) with strong evidence (CHANGE_MIN_RUNS runs, CHANGE_MIN_SECONDS seconds)
         and a modest size (at most CHANGE_MAX_RELATIVE of the value it replaces: the profile's value, or the last human-approved snapshot's).
    Anything else waits for the user (`g2cal approve ID`); every automatic approval is logged and `g2cal revert` undoes it."""
    ok = {k: p for k, p in snap["params"].items() if p.get("status") == "ok"}
    if not ok:
        return "empty", ["no parameter has enough data yet: " + "; ".join(f"{k}: {p.get('reason', p.get('status'))}" for k, p in snap["params"].items())]
    hc = snap.get("harm_check", {}).get("status", "not run")
    if hc == "failed":
        return "blocked", ["the harm check failed: " + "; ".join(snap["harm_check"].get("problems", []))]
    if hc != "passed":
        return "pending harm check", ["run `g2cal harm-check` first"]
    why = []
    if current is not None and current.get("epoch") != snap.get("epoch"):
        why.append("the hardware epoch changed since the approved snapshot")
    for k, p in ok.items():
        if not p.get("changed") or p.get("within_noise"):
            continue                                                       # the same value, or a difference smaller than its own noise: nothing to judge
        if p["n_runs"] < CHANGE_MIN_RUNS or p["seconds"] < CHANGE_MIN_SECONDS:
            why.append(f"{k}: {p.get('old')} -> {p['value']} is beyond its noise (+-{p['noise']}) but rests on only {p['n_runs']} runs / {p['seconds']:.0f} s (a change needs {CHANGE_MIN_RUNS} runs and {CHANGE_MIN_SECONDS:.0f} s)")
        ref = float(last_human["env"][k]) if (last_human is not None and k in last_human.get("env", {})) else (float(p["old"]) if p.get("old") is not None else None)
        if ref is not None and abs(float(p["value"]) - ref) > CHANGE_MAX_RELATIVE * max(abs(ref), 1.0):
            why.append(f"{k}: {ref:g} -> {p['value']} moves more than {CHANGE_MAX_RELATIVE:.0%} of the value it replaces")
    return ("needs_user", why) if why else ("auto_approved", ["every gate passed: fit checks, harm check, same epoch, and every change within its noise or backed by strong evidence and modest in size"])


def current_snapshot() -> dict | None:
    i = read_current()
    try:
        return load_snapshot(i) if i else None
    except (OSError, ValueError):
        return None


def last_human_snapshot() -> dict | None:
    try:
        rows = [json.loads(x) for x in open(_path("approvals.jsonl")) if x.strip()]
    except OSError:
        return None
    for r in reversed(rows):
        if r.get("how") == "human" and r.get("id"):
            return load_snapshot(r["id"])
    return None


def with_harm(snap: dict, i: int) -> dict:
    return dict(snap, harm_check=harm_status(i))


def diff_text(snap: dict) -> str:
    lines = [f"snapshot {snap.get('id', '?')}  epoch {snap['epoch']}  {snap['runs_used']} runs, {snap['seconds_used']:.0f} s of steady walking  ({snap['made']})", ""]
    for k, p in snap["params"].items():
        if p.get("status") == "ok":
            tag = "UNCHANGED" if not p.get("changed") else ("within noise" if p.get("within_noise") else "BEYOND NOISE")
            lines.append(f"  {k}: {p.get('old')} -> {p['value']}  (+-{p['noise']}, {p['n_runs']} runs)  {tag}")
        else:
            lines.append(f"  {k}: not fitted ({p.get('reason', p.get('status'))}); measured median {p.get('median', '-')} from {p['n_runs']} runs / {p['seconds']:.0f} s")
        for name, ok, detail in p.get("checks", []):
            lines.append(f"      [{'x' if ok else ' '}] {name}: {detail}")
    lines += ["", "monitored statistics (targets for the sim-versus-real gap):"]
    lines += [f"  {s}: {g['runs']} runs, {g['seconds']:.0f} s, roll sd {g['roll_std_deg']} deg, pitch sd {g['pitch_std_deg']} deg" for s, g in snap["monitor"].items()]
    e = snap["events"]
    lines.append(f"events: {e['falls']} falls in {e['walked_s']:.0f} s walked")
    lines += ["", "still needs data:"] + [f"  {k}: {v}" for k, v in snap["needs_data"].items()]
    return "\n".join(lines)


def current_env() -> dict:
    """The approved snapshot's parameters (what g2_profile loads), or {} when none is approved."""
    i = read_current()
    if not i:
        return {}
    try:
        env = load_snapshot(i)["env"]
        check_whitelist(env)
        return env
    except (OSError, ValueError, KeyError):
        return {}


def auto(log=print, min_new_runs: int = MIN_RUNS) -> str:
    """The unattended step: build a snapshot when enough new usable runs have arrived, run its harm check when the Mac is idle, and apply the approval rules.
    Safe to call as often as you like. Returns a one-line summary."""
    mpath = os.path.join(STORE, "manifest.json")
    if not os.path.isfile(mpath):
        return "no ingested data yet"
    ids = list_ids()
    last = load_snapshot(ids[-1]) if ids else None
    manifest = json.load(open(mpath))
    refused = last is not None and any(k in read_rejected() for k in last["env"])               # a person has since refused one of its parameters: it is superseded
    if last is not None and last["env"] and not refused and read_current() != ids[-1] and harm_status(ids[-1])["status"] != "not run":
        verdict, why = decide(with_harm(last, ids[-1]), last_human_snapshot(), current_snapshot())      # the latest snapshot already has its harm check: apply the gates now
        if verdict == "auto_approved":
            write_current(ids[-1], "auto", "rules")
            return f"snapshot {ids[-1]:04d} auto-approved and live for new training runs ({why[0]})"
    if last is None or refused or not (last["env"] and harm_status(ids[-1])["status"] in ("not run",)):     # a snapshot still waiting for its harm check is processed first
        snap = build(manifest)
        epoch_changed = last is not None and snap["epoch"] != last["epoch"]
        new = snap["runs_used"] - (0 if (last is None or epoch_changed or refused) else last["runs_used"])
        if new < min_new_runs and not epoch_changed:
            return f"waiting for data: {new} new usable runs since snapshot {ids[-1] if ids else 'none'} (need {min_new_runs})"
        if not snap["env"]:
            return "nothing to apply yet: " + "; ".join(f"{k}: {v.get('reason', v.get('status'))}" for k, v in snap["params"].items())[:300]
        i = save_snapshot(snap)
        log(f"snapshot {i:04d} written: {snap['runs_used']} runs, {snap['seconds_used']:.0f} s, parameters fitted: {sorted(snap['env']) or 'none yet'}")
        ids, last = list_ids(), load_snapshot(i)
    i = ids[-1]
    snap = with_harm(last, i)
    if not snap["env"]:
        return f"snapshot {i:04d} has no parameter with enough data yet: nothing to approve ({decide(snap, None)[1][0]})"
    if snap["harm_check"]["status"] == "not run":
        try:
            r = run_harm_check(snap, default_policies())
        except RuntimeError as e:
            return f"snapshot {i:04d} waits for an idle Mac to run its harm check ({e})"
        os.makedirs(_path("harm"), exist_ok=True)
        json.dump(r, open(harm_path(i), "w"), indent=1)
        snap = with_harm(last, i)
        log(f"harm check for {i:04d}: {r['status']}")
    verdict, why = decide(snap, last_human_snapshot(), current_snapshot())
    if verdict == "auto_approved" and read_current() != i:
        write_current(i, "auto", "rules")
        return f"snapshot {i:04d} auto-approved and live for new training runs ({why[0]})"
    return f"snapshot {i:04d}: {verdict} ({'; '.join(why)[:300]})"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("status")
    p = sub.add_parser("show"); p.add_argument("id", nargs="?", type=int)
    p = sub.add_parser("harm-check"); p.add_argument("id", type=int); p.add_argument("policies", nargs="+"); p.add_argument("--episodes", type=int, default=24)
    p = sub.add_parser("approve"); p.add_argument("id", type=int)
    sub.add_parser("revert")
    sub.add_parser("auto")
    p = sub.add_parser("reject"); p.add_argument("param"); p.add_argument("note", nargs="*")
    p = sub.add_parser("unreject"); p.add_argument("param")
    a = ap.parse_args(argv)
    if a.cmd == "auto":
        print(auto())
        return 0
    if a.cmd == "reject":
        reject(a.param, " ".join(a.note))
        print(f"{a.param} rejected: it is still measured and reported, but no snapshot will apply it (g2cal unreject {a.param} to allow it again)")
        return 0
    if a.cmd == "unreject":
        unreject(a.param)
        print(f"{a.param} is allowed again")
        return 0
    if a.cmd == "build":
        mpath = os.path.join(STORE, "manifest.json")
        if not os.path.isfile(mpath):
            print("no ingested data yet: run `g2data` first")
            return 1
        snap = build(json.load(open(mpath)))
        i = save_snapshot(snap)
        snap["id"] = i
        print(diff_text(snap))
        verdict, why = decide(with_harm(snap, i), last_human_snapshot(), current_snapshot())
        print(f"\nsnapshot {i:04d} written. verdict: {verdict}")
        for w in why:
            print("  - " + w)
        return 0
    if a.cmd == "status":
        cur, ids = read_current(), list_ids()
        own = "none (the profile's own values are used)"
        print(f"current (live in new training runs): {cur if cur else own}")
        for i in ids[-3:]:
            s = with_harm(load_snapshot(i), i)
            verdict, why = decide(s, last_human_snapshot(), current_snapshot())
            if any(k in read_rejected() for k in s["env"]):
                verdict, why = "superseded", ["it carries a parameter you rejected"]
            print(f"  {i:04d} {s['made']}  epoch {s['epoch']}  {s['runs_used']} runs / {s['seconds_used']:.0f} s  harm check: {s['harm_check']['status']}  -> {verdict}")
            for w in why[:3]:
                print("       " + w)
        if not ids:
            print("  no snapshots yet (`g2cal build`)")
        return 0
    if a.cmd == "show":
        i = a.id or (list_ids() or [None])[-1]
        if i is None:
            print("no snapshots yet")
            return 1
        s = load_snapshot(i)
        print(diff_text(with_harm(s, i)))
        return 0
    if a.cmd == "harm-check":
        s = load_snapshot(a.id)
        if not s["env"]:
            print("this snapshot changes nothing, so there is nothing to check")
            return 1
        r = run_harm_check(s, a.policies, a.episodes)
        os.makedirs(_path("harm"), exist_ok=True)
        json.dump(r, open(harm_path(a.id), "w"), indent=1)
        print(f"harm check: {r['status']}")
        for x in r["problems"]:
            print("  - " + x)
        return 0 if r["status"] == "passed" else 2
    if a.cmd == "approve":
        s = load_snapshot(a.id)
        hc = harm_status(a.id)["status"]
        if hc == "failed":
            print("blocked: the harm check failed; not approvable until the cause is understood")
            return 2
        if hc != "passed":
            print("warning: the harm check has not passed; approving anyway on your word (recorded)")
        write_current(a.id, "human", "user")
        print(f"snapshot {a.id:04d} approved and live for new training runs")
        return 0
    if a.cmd == "revert":
        rows = [json.loads(x) for x in open(_path("approvals.jsonl")) if x.strip()] if os.path.isfile(_path("approvals.jsonl")) else []
        ids = [r["id"] for r in rows]
        prev = ids[-2] if len(ids) >= 2 else None
        write_current(prev, "revert", "user")
        own = "none (the profile's own values)"
        print(f"current is now {prev if prev else own}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
