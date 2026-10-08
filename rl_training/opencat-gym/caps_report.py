"""Are the top-threshold caps in the right place? (user, 2026-10-08: "if we cap too low the policy will never improve, if we cap too high it won't learn to succeed; monitor this closely")

    ../../.venv/bin/python caps_report.py <tag>            # the report from the run's console log and its caps file
    ../../.venv/bin/python caps_report.py <tag> --watch    # print one review line each time the run passes another 1M steps (for a Monitor)

For each capped hazard (slope: side-hill, climb, descent caps; ledge: the ledge-face cap) it reads the run's `[probe]` lines (every 98k steps the deterministic policy is run on that
category at its level and scored relative to its clean-floor score; the level goes up after good probes and down after a bad one) and the current caps (`trained/<tag>_caps.json`).
The cap BINDS once the level is high enough that the hazard's nominal size (without the cap) exceeds it: binding level = cap / nominal maximum. Verdicts:
  CAP TOO LOW   the level is past the binding level (the cap is what limits difficulty) and the last probes were all good (>= 0.80): raise the cap one step
  CAP TOO HIGH  the cap binds and most of the last probes were bad (<= 0.50): the policy cannot succeed even at the capped size; lower the cap one step
  ON TRACK      anything else (below the binding level the ramp itself, not the cap, limits difficulty)
One step per review (side-hill, climb, descent 2 deg; ledge 0.5 cm). The report never edits the caps; Claude or the user does, by editing the file the run reads while it trains.
"""
import argparse
import json
import os
import re
import sys
import time

NOMINAL = {"sidehill_deg": 15.0, "uphill_deg": 24.0, "downhill_deg": 15.4, "ledge_m": 0.035}      # the largest size each hazard reaches at level 1.0 without a cap, for the OLD default course; see nominal_for()


def nominal_for(tag=None):
    """The largest size each capped hazard reaches at level 1.0 without a cap, in THIS run's course (2026-10-08 review fix: the table above assumed the old 14 deg random tilt,
    so for the next fresh final -- 10 deg x 1.10 hard levels = 11 deg -- the descent cap was reported as binding from level 0.65 when it binds from 0.91).
    Side-hills and climbs come from the targeted slopes (3-15 deg, 12-24 deg x level); descents from the random tilt (SLOPE_MAX_DEG x HARD_SCALE x level); ledges from LEDGE_HEIGHT."""
    try:
        import g2_profile
        env = None
        if tag and os.path.exists("trained/v3_queue.json"):
            for job in json.load(open("trained/v3_queue.json")):
                if job.get("tag") == tag:
                    if not isinstance(job.get("levers"), list):           # "K3": the levers the combined recipe kept
                        res = json.load(open("trained/v3_results.json")) if os.path.exists("trained/v3_results.json") else {}
                        job = dict(job, levers=res.get("v3_k3", {}).get("levers", ["mirror"]))
                    env = g2_profile.env_for_job(job)
        env = env or g2_profile.next_final_env()
        hard = float(env.get("G2E_HARD_SCALE", "1") or 1)
        tilt = float(env.get("G2E_SLOPE_MAX_DEG", "14") or 14) * hard
        return {"sidehill_deg": max(15.0, tilt), "uphill_deg": max(24.0, tilt), "downhill_deg": tilt, "ledge_m": float(env.get("G2E_LEDGE_HEIGHT", "0.035") or 0.035)}
    except Exception:  # noqa: BLE001 -- fall back to the old table rather than fail the review
        return dict(NOMINAL)
CATEGORY_OF = {"sidehill_deg": "slope", "uphill_deg": "slope", "downhill_deg": "slope", "ledge_m": "ledge"}
STEP = {"sidehill_deg": 2.0, "uphill_deg": 2.0, "downhill_deg": 2.0, "ledge_m": 0.005}
LIMIT = {"sidehill_deg": 15.0, "uphill_deg": 24.0, "downhill_deg": 15.4, "ledge_m": 0.037}       # a cap never moves above the course's own design size
WINDOW = 6
GOOD, BAD = 0.80, 0.50
_PROBE = re.compile(r"\[probe\] steps (\d+)\s+clean-floor score ([0-9.]+).*?-> new level: (.*)")
_CAT = re.compile(r"(terrain|ledge|slope|fault) ([0-9.]+) \(([0-9.]+)\) -> ([0-9.]+)")


def parse(lines):
    probes = []
    for ln in lines:
        m = _PROBE.search(ln)
        if m:
            cats = {c: dict(rel=float(r), raw=float(raw), level=float(new)) for c, r, raw, new in _CAT.findall(m.group(3))}
            probes.append(dict(steps=int(m.group(1)), clean=float(m.group(2)), cats=cats))
    return probes


def verdicts(probes, caps, nominal=None):
    nominal = nominal or NOMINAL
    out = {}
    for key, cap in caps.items():
        if key not in nominal or not cap:
            continue
        cat = CATEGORY_OF[key]
        recent = [p["cats"][cat] for p in probes[-WINDOW:] if cat in p["cats"]]
        binding_level = cap / nominal[key]
        if len(recent) < WINDOW:
            out[key] = dict(cap=cap, binding_level=binding_level, verdict="TOO EARLY", why=f"only {len(recent)} probes so far")
            continue
        level = recent[-1]["level"]
        rels = [r["rel"] for r in recent]             # the probe score RELATIVE to the policy's clean-floor score: what the curriculum's up/down thresholds use (2026-10-08 review fix: this read the raw score)
        binds = level >= binding_level - 1e-9
        if binds and all(x >= GOOD for x in rels):
            v, why = "CAP TOO LOW", f"level {level:.2f} is at/over the binding level {binding_level:.2f} and the last {WINDOW} probes were all >= {GOOD}: raise it one step"
        elif binds and sum(x <= BAD for x in rels) >= WINDOW // 2 + 1:
            v, why = "CAP TOO HIGH", f"the cap binds (level {level:.2f} >= {binding_level:.2f}) and {sum(x <= BAD for x in rels)} of the last {WINDOW} probes were <= {BAD}: lower it one step"
        else:
            v, why = "ON TRACK", (f"the cap binds from level {binding_level:.2f}; the level is {level:.2f}" if not binds else f"the cap binds and the probes sit between {min(rels):.2f} and {max(rels):.2f}")
        out[key] = dict(cap=cap, binding_level=binding_level, level=level, recent=rels, verdict=v, why=why)
    return out


def suggest(key, cap, verdict):
    if verdict == "CAP TOO LOW":
        return min(LIMIT[key], cap + STEP[key])
    if verdict == "CAP TOO HIGH":
        return max(STEP[key], cap - STEP[key])
    return cap


def report(tag):
    log = f"trained/{tag}_console.log"
    lines = open(log, errors="replace").read().splitlines() if os.path.exists(log) else []
    probes = parse(lines)
    caps_path = f"trained/{tag}_caps.json"
    caps = json.load(open(caps_path)) if os.path.exists(caps_path) else {}
    steps = probes[-1]["steps"] if probes else 0
    print(f"{tag}: {len(probes)} probes, last at {steps:,} steps; caps {caps or '(none yet)'}")
    for key, v in verdicts(probes, caps, nominal_for(tag)).items():
        new = suggest(key, v["cap"], v["verdict"])
        move = f"  -> suggest {new:g}" if new != v["cap"] else ""
        print(f"  {key:13s} cap {v['cap']:g}: {v['verdict']:12s} {v['why']}{move}")
    return probes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--watch", action="store_true")
    a = ap.parse_args()
    if not a.watch:
        report(a.tag)
        return
    done = 0
    while True:
        log = f"trained/{a.tag}_console.log"
        probes = parse(open(log, errors="replace").read().splitlines()) if os.path.exists(log) else []
        steps = probes[-1]["steps"] if probes else 0
        if steps // 1_000_000 > done:
            done = steps // 1_000_000
            print(f"CAPS REVIEW DUE at {steps:,} steps: run `cd rl_training/opencat-gym && ../../.venv/bin/python caps_report.py {a.tag}`", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    main()
