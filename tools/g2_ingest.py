#!/usr/bin/env python3
"""Ingest G2's automatic run logs into the real-data store (Phase 2 of docs/rl/real-data-pipeline.md).

    python tools/g2_ingest.py [--raw ~/g2_data/raw_auto] [--store ~/g2_data/store]          (the g2data alias: `g2data sync | ingest | status`)

For every run (`<run>.csv` + `<run>.json` sidecar, optional `<run>.labels.json`) it measures the log, applies the ingest gates, compresses the log losslessly (gzip) into the store and writes `manifest.json`.
NOTHING is deleted and nothing raw is changed: a run that fails a gate is **quarantined** with its reasons (or **excluded** when a person flagged it), and stays in the store. Only `usable` runs may feed a fit,
and each run lists the kinds of fit it may feed (`uses`: `timing` and/or `body`; user, 2026-10-18: gate per fit, not per run).
Drift (yaw / heading) and mean lean are measured and stored under `monitor` for audits only; the gates and the fit inputs never use them (see "Keeping drift out of the sim").

Gates for every fit: not flagged excluded; G2's everyday walk (no test trim, heading hold, constant steer or scripted walk; the everyday constant foot trim is part of his normal gait); the front-foot hold not working
hard; no fall / collision / pickup label; hardware epoch marked `fit_ok`; time increasing; IMU frames fresh (no stretch over 1 s); no missing values in the used columns; a steady window of at least 1 s after the first 1.5 s.
Gates for body fits only (roll and pitch spread, event rates; the loop-timing fits do not depend on them): surface known (label set within 72 h, or a person's override); a steady window of at least 2 s; control loop on
time (under 5% of ticks late; the jitter fit would otherwise only ever see the calm runs); not a statistical outlier (more than 4 robust sigma from its group on roll or pitch spread; groups of 6 or more runs).
A run that ended in a fall, a crash, a stale IMU or any stop other than `stopped` / `complete` is not dropped: its last second is cut and the rest is used (the fall still counts for event rates).
Pack voltage is tagged by band (full 8.0 V and over, mid 7.6 to 8.0, low under 7.6) and groups are never mixed across bands.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import shutil
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EPOCHS_PATH = os.path.join(ROOT, "pi_pipeline", "telemetry", "hardware_epochs.json")
PROFILES_PATH = os.path.join(ROOT, "pi_pipeline", "attachments", "gait_profiles.json")

FIRST_SKIP_S = 1.5            # the stand and ramp-in at the start of every run
MIN_STEADY_S = 2.0            # body fits
MIN_STEADY_TIMING_S = 1.0     # timing fits pool seconds across runs (2026-10-18)
END_CUT_S = 1.0               # a run that did not end cleanly: the last second is cut, the rest is used (2026-10-18)
LATE_TICK_S = 0.025           # two control ticks at 80 Hz
MAX_LATE_FRACTION = 0.05
MAX_IMU_AGE_S = 1.0
MAX_SURFACE_AGE_H = 72.0          # user, 2026-10-08: was 12 h; a floor label stays right for days when G2 keeps living in the same room
GOOD_END = ("stopped", "complete")
BAD_LABELS = ("fall", "collision", "pickup")
MAX_HOLD_U = 0.30             # the front-foot heading hold (on in every walk since 2026-10-07) is active much of the time on tile (median mean |u| 0.19); above 0.30 it was doing most of the steering
MIN_GROUP = 6
OUTLIER_SIGMA = 4.0
USES = ("body", "timing")
BODY_ONLY = {"floor", "floor_age", "steady_body", "late", "outlier"}     # checks that keep a run out of body fits only; every other check blocks every fit


def volt_band(v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return "unknown"
    return "full" if v >= 8.0 else "mid" if v >= 7.6 else "low"


def load_epochs(path: str = EPOCHS_PATH) -> dict:
    try:
        return {e["id"]: e for e in json.load(open(path))}
    except (OSError, ValueError):
        return {}


def epoch_at(started, epochs: dict) -> str | None:
    """The hardware epoch in force when a run started (the newest epoch whose start is not after it). The Mac's epoch file is the authority:
    the Pi stamps each run from its own copy, which lags when hardware changes before the file reaches it (2026-10-18: the pod and AI head runs were stamped hw-2026-10-07)."""
    if not started:
        return None
    best = None
    for e in sorted((e for e in epochs.values() if e.get("start")), key=lambda e: e["start"]):     # an epoch without a start time never matches
        if e["start"] <= str(started):
            best = e["id"]
    return best


def read_csv(path: str) -> tuple[list[str], list[list[str]]]:
    with open(path, newline="") as f:
        lines = [ln for ln in f if ln.strip() and not ln.startswith("#")]
    rows = list(csv.reader(lines))
    return (rows[0], rows[1:]) if rows else ([], [])


def column(head: list[str], rows: list[list[str]], name: str) -> np.ndarray | None:
    if name not in head:
        return None
    i = head.index(name)
    out = []
    for r in rows:
        try:
            out.append(float(r[i]))
        except (ValueError, IndexError):
            out.append(float("nan"))
    return np.array(out, dtype=float)


def window(t: np.ndarray, end_reason=None) -> tuple[np.ndarray, np.ndarray]:
    """(kept rows, steady rows) of a run log: a run that did not end cleanly loses its last `END_CUT_S` (the fall or the exit itself); the steady window also
    skips the first `FIRST_SKIP_S` (the stand and ramp-in). Shared with the calibration builder so both read the same rows."""
    cut = 0.0 if end_reason in GOOD_END else END_CUT_S
    keep = t <= (t[-1] - cut)
    return keep, keep & (t >= (t[0] + FIRST_SKIP_S))


def measure(csv_path: str, end_reason=None) -> dict:
    head, rows = read_csv(csv_path)
    m: dict = {"rows": len(rows)}
    t = column(head, rows, "t")
    if t is None or len(t) < 5:
        return m
    dt = np.diff(t)
    keep, steady = window(t, end_reason)
    kept_dt = np.diff(t[keep]) if keep.sum() > 1 else dt
    m.update(duration_s=round(float(t[-1] - t[0]), 2), tick_median_ms=round(float(np.median(dt)) * 1e3, 2), late_fraction=round(float((kept_dt > LATE_TICK_S).mean()), 4),
             time_increasing=bool((dt > 0).all()))
    if end_reason not in GOOD_END:
        m["cut_end_s"] = END_CUT_S
    m["steady_s"] = round(float(t[steady][-1] - t[steady][0]), 2) if steady.sum() > 2 else 0.0
    roll, pitch, yaw = (column(head, rows, c) for c in ("roll", "pitch", "yaw"))
    if roll is not None and pitch is not None and steady.sum() > 2:
        r, p = np.degrees(roll[steady]), np.degrees(pitch[steady])
        m.update(roll_std_deg=round(float(np.nanstd(r)), 3), pitch_std_deg=round(float(np.nanstd(p)), 3))
        m["monitor"] = {"roll_mean_deg": round(float(np.nanmean(r)), 2), "pitch_mean_deg": round(float(np.nanmean(p)), 2)}
        if yaw is not None:
            m["monitor"]["yaw_change_deg"] = round(float(np.degrees(np.nanmax(yaw[steady]) - np.nanmin(yaw[steady]))), 1)          # audit only: never a fit input
    for name in ("roll", "pitch", "t"):
        c = column(head, rows, name)
        if c is not None and np.isnan(c[keep]).any():
            m["missing_values"] = True
    u = column(head, rows, "steer_u")
    if u is not None and steady.sum() > 2 and np.isfinite(u[steady]).any():
        m["steer_u_mean_abs"] = round(float(np.nanmean(np.abs(u[steady]))), 3)            # how hard the heading hold worked in the steady window
    n, age, volt, az = (column(head, rows, c) for c in ("imu_n", "imu_age_s", "volt", "az"))
    if n is not None:
        m["imu_fresh_hz"] = round(float((np.diff(n) > 0).sum() / max(t[-1] - t[0], 1e-9)), 2)
    if age is not None and np.isfinite(age[keep]).any():
        m["imu_age_max_s"] = round(float(np.nanmax(age[keep])), 3)
    if volt is not None and np.isfinite(volt).any():
        m["volt_mean"] = round(float(np.nanmean(volt)), 2)
    if az is not None and np.isfinite(az).any():
        m["az_median"] = round(float(np.nanmedian(az)), 2)
    return m


def floor_override(side: dict, overrides: list) -> str | None:
    """A person's statement of the floor for a time range (`~/g2_data/floor_overrides.json`: [{"from": "2026-10-08T08:00", "to": "2026-10-08T11:00", "surface": "tile"}]).
    It replaces the label G2 recorded (and its age); `"surface": "unknown"` takes the runs out of every fit until someone says what floor they were on. None = no override."""
    t = (side.get("started") or "")[:16]
    for o in overrides:
        if o["from"][:16] <= t <= o["to"][:16]:
            return o["surface"]
    return None


def trim_key(trim) -> tuple | None:
    """A foot trim as a sidecar records it ([["fl", -0.3]]) or as text ("fl=-0.3", "fl=-0.3/fr=+0.1") -> a comparable tuple; None for no trim."""
    if not trim:
        return None
    if isinstance(trim, str):
        trim = [(f, v) for f, _, v in (part.strip().partition("=") for part in trim.split("/") if part.strip())]
        if any(str(v).strip().lower() in ("", "off", "none") for _, v in trim):
            return None
    return tuple(sorted((str(f).strip().lower(), round(float(v), 3)) for f, v in trim)) or None


def everyday_trims(policy, surface=None, profiles_path: str = PROFILES_PATH) -> set:
    """The constant foot trims G2 walks with every day on `policy`: its `DEFAULT_TRIMS` entry (gait/heading_hold.py) and the trims saved with an attachment's
    gait for that policy (the gait's own trim, and its per-floor trim for `surface`). A walk with one of these is his normal gait, not a steering test."""
    name = os.path.basename(str(policy or ""))
    out = set()
    try:
        sys.path.insert(0, ROOT)
        from pi_pipeline.gait.heading_hold import DEFAULT_TRIMS
        out.add(trim_key(DEFAULT_TRIMS.get(name)))
    except Exception:  # noqa: BLE001
        pass
    finally:
        if ROOT in sys.path:
            sys.path.remove(ROOT)
    try:
        profiles = json.load(open(profiles_path))
    except (OSError, ValueError):
        profiles = {}
    for prof in profiles.values() if isinstance(profiles, dict) else []:
        for g in [prof.get("current")] + list(prof.get("history") or []):
            if isinstance(g, dict) and os.path.basename(str(g.get("policy") or "")) == name:
                out.add(trim_key(g.get("trim")))
                if surface:
                    out.add(trim_key((g.get("trim_by_floor") or {}).get(surface)))
    out.discard(None)
    return out


def everyday_trim(side: dict, surface=None) -> bool:
    """Was this walk's foot trim the everyday one? The walk loop records `foot_trim_source: "everyday"` since 2026-10-18; older sidecars are compared with the table."""
    if side.get("foot_trim_source") == "everyday":
        return True
    return trim_key(side.get("foot_trim")) in everyday_trims(side.get("policy"), surface)


def checks(side: dict, labels: list, m: dict, epochs: dict, overrides: list | None = None) -> list[tuple[str, str]]:
    """(code, reason) for every check a run fails; codes in `BODY_ONLY` keep it out of body fits only. Empty list = usable for every fit. 'excluded' means a person said so."""
    why: list[tuple[str, str]] = []
    if side.get("excluded"):
        return [("excluded", "excluded: " + str(side.get("excluded_reason", "flagged by a person")))]
    ov = floor_override(side, overrides or [])
    surface = ov if ov is not None else side.get("surface")
    applied = [k for k in ("heading_hold", "steer_const", "scripted") if side.get(k)]
    if side.get("foot_trim") and not everyday_trim(side, surface):
        applied.append("foot_trim")
    if applied:                          # a test walk with a steering intervention or no learned correction: not G2's natural gait, never a fit source
        why.append(("steering", "steering test run (" + ", ".join(applied) + "): never fed to the sim"))
    if side.get("foot_hold") and m.get("steer_u_mean_abs", 0.0) > MAX_HOLD_U:
        why.append(("hold", f"the front-foot heading hold worked hard (mean |u| {m['steer_u_mean_abs']:.2f} > {MAX_HOLD_U}): not G2's natural gait"))
    bad = sorted({x["tag"] for x in labels if x.get("tag") in BAD_LABELS})
    if bad:
        why.append(("label", "labelled " + ", ".join(bad)))
    ep = epochs.get(side.get("epoch"))
    if ep is None or not ep.get("fit_ok"):
        why.append(("epoch", f"hardware epoch {side.get('epoch')} is not marked fit_ok"))
    if surface in (None, "", "unknown"):
        why.append(("floor", "floor not set" if ov is None else "floor not confirmed for this time (floor_overrides.json)"))
    age = side.get("surface_age_h")
    if ov is None and age is not None and age > MAX_SURFACE_AGE_H:
        why.append(("floor_age", f"floor label is {age:.0f} h old"))
    if m.get("rows", 0) < 5:
        why.append(("rows", f"too few rows ({m.get('rows', 0)})"))                 # a run stopped almost at once: nothing to judge, not a damaged log
        return why
    if not m.get("time_increasing", False):
        why.append(("clock", "time does not increase (damaged log)"))
    steady = m.get("steady_s", 0.0)
    if steady < MIN_STEADY_TIMING_S:
        why.append(("steady", f"steady window {steady:.1f} s is under {MIN_STEADY_TIMING_S:.0f} s"))
    elif steady < MIN_STEADY_S:
        why.append(("steady_body", f"steady window {steady:.1f} s is under {MIN_STEADY_S:.0f} s"))
    if m.get("late_fraction", 1.0) > MAX_LATE_FRACTION:
        why.append(("late", f"{m.get('late_fraction', 1.0) * 100:.0f}% of ticks late"))
    if m.get("imu_age_max_s") is not None and m["imu_age_max_s"] > MAX_IMU_AGE_S:
        why.append(("imu", f"IMU stale for {m['imu_age_max_s']:.1f} s"))
    if m.get("missing_values"):
        why.append(("missing", "missing values"))
    return why


def gate(side: dict, labels: list, m: dict, epochs: dict, overrides: list | None = None) -> list[str]:
    """Reasons a run may not feed some fit (empty list = usable for every fit)."""
    return [w for _, w in checks(side, labels, m, epochs, overrides)]


def uses_for(codes) -> list[str]:
    """The kinds of fit a run may feed, given the codes of the checks it failed."""
    codes = set(codes)
    if "excluded" in codes:
        return []
    return [u for u in USES if not any(c not in BODY_ONLY or u == "body" for c in codes)]


def uses_of(run: dict) -> list[str]:
    """A manifest entry's `uses`; a manifest written before 2026-10-18 had none: its usable runs were usable for every fit."""
    if "uses" in run:
        return list(run["uses"])
    return list(USES) if run.get("status") == "usable" else []


def status_of(uses: list, codes) -> str:
    return "excluded" if "excluded" in set(codes) else "usable" if uses else "quarantined"


def outliers(entries: list[dict]) -> None:
    """Quarantine runs far from the rest of their group (epoch, surface, voltage band, policy) on roll or pitch spread. Robust: median and MAD."""
    groups: dict = {}
    for e in entries:
        if "body" in e["uses"]:
            groups.setdefault((e["epoch"], e["surface"], e["volt_band"], e["policy"]), []).append(e)
    for g in groups.values():
        if len(g) < MIN_GROUP:
            continue
        for key in ("roll_std_deg", "pitch_std_deg"):
            v = np.array([x[key] for x in g], dtype=float)
            med = float(np.median(v))
            mad = float(np.median(np.abs(v - med))) * 1.4826
            if mad <= 0:
                continue
            for x, val in zip(g, v):
                if abs(val - med) / mad > OUTLIER_SIGMA and "body" in x["uses"]:
                    x["reasons"].append(f"outlier on {key}: {val:.1f} vs the group's {med:.1f}")
                    x["reason_codes"].append("outlier")
                    x["uses"] = uses_for(x["reason_codes"])
                    x["status"] = status_of(x["uses"], x["reason_codes"])


def ingest(raw: str, store: str, epochs: dict | None = None) -> dict:
    epochs = epochs if epochs is not None else load_epochs()
    try:
        overrides = json.load(open(os.path.join(os.path.dirname(os.path.abspath(raw)), "floor_overrides.json")))
    except (OSError, ValueError):
        overrides = []
    entries = []
    for day in sorted(d for d in os.listdir(raw) if os.path.isdir(os.path.join(raw, d))) if os.path.isdir(raw) else []:
        for fn in sorted(os.listdir(os.path.join(raw, day))):
            if not fn.endswith(".json") or fn.endswith(".labels.json"):
                continue
            stem = fn[:-5]
            side_path, csv_path = os.path.join(raw, day, fn), os.path.join(raw, day, stem + ".csv")
            try:
                side = json.load(open(side_path))
            except (OSError, ValueError):
                continue
            lab_path = os.path.join(raw, day, stem + ".labels.json")
            labels = json.load(open(lab_path)) if os.path.isfile(lab_path) else []
            by_time = epoch_at(side.get("started"), epochs)
            if by_time and by_time != side.get("epoch"):
                side = dict(side, epoch=by_time, epoch_stamped=side.get("epoch"))      # re-tagged from the start time (the stamp is kept)
            m = measure(csv_path, side.get("end_reason")) if os.path.isfile(csv_path) else {}
            failed = checks(side, labels, m, epochs, overrides) if m else [("nolog", "no log file")]
            codes, why = [c for c, _ in failed], [w for _, w in failed]
            uses = uses_for(codes)
            e = {"run": stem, "day": day, "kind": side.get("kind"), "policy": side.get("policy"), "epoch": side.get("epoch"), "surface": floor_override(side, overrides) or side.get("surface"), "volt_band": volt_band(m.get("volt_mean")),
                 "started": side.get("started"), "end_reason": side.get("end_reason"), "status": status_of(uses, codes), "uses": uses, "reasons": why, "reason_codes": codes,
                 "labels": sorted({x["tag"] for x in labels}),
                 "roll_std_deg": m.get("roll_std_deg", float("nan")), "pitch_std_deg": m.get("pitch_std_deg", float("nan")), "metrics": m}
            entries.append(e)
            dest = os.path.join(store, day)
            os.makedirs(dest, exist_ok=True)
            for src_name in (stem + ".json", stem + ".labels.json"):
                p = os.path.join(raw, day, src_name)
                if os.path.isfile(p):
                    shutil.copy2(p, os.path.join(dest, src_name))
            if os.path.isfile(csv_path):
                gz = os.path.join(dest, stem + ".csv.gz")
                if not os.path.isfile(gz) or os.path.getmtime(gz) < os.path.getmtime(csv_path):
                    with open(csv_path, "rb") as fi, gzip.open(gz + ".tmp", "wb", compresslevel=9) as fo:
                        shutil.copyfileobj(fi, fo)
                    os.replace(gz + ".tmp", gz)
    outliers(entries)
    manifest = {"made": time.strftime("%Y-%m-%dT%H:%M:%S"), "raw": raw, "store": store, "runs": entries}
    os.makedirs(store, exist_ok=True)
    with open(os.path.join(store, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, default=lambda x: None if isinstance(x, float) and math.isnan(x) else x)
    return manifest


def status_text(manifest: dict) -> str:
    runs = manifest["runs"]
    if not runs:
        return "no runs ingested yet"
    by_status: dict = {}
    for r in runs:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    usable_s = sum(r["metrics"].get("steady_s", 0.0) for r in runs if r["status"] == "usable")
    lines = [f"{len(runs)} runs: " + ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())) + f"   usable steady-state walking: {usable_s:.0f} s"]
    lines.append("usable for: " + ", ".join(f"{u} fits {sum(1 for r in runs if u in uses_of(r))}" for u in USES))
    groups: dict = {}
    for r in runs:
        if "body" in uses_of(r):
            k = (r["epoch"], r["surface"], r["volt_band"])
            groups.setdefault(k, [0, 0.0])
            groups[k][0] += 1
            groups[k][1] += r["metrics"].get("steady_s", 0.0)
    if groups:
        lines.append("usable for body fits, by hardware epoch / floor / pack voltage:")
        lines += [f"  {e} / {s} / {b}: {n} runs, {sec:.0f} s" for (e, s, b), (n, sec) in sorted(groups.items(), key=lambda kv: str(kv[0]))]
    reasons: dict = {}
    for r in runs:
        for i, w in enumerate(r["reasons"]):
            code = (r.get("reason_codes") or [None] * len(r["reasons"]))[i]
            key = w.split(":")[0] if w.startswith("excluded") else w.split("(")[0].strip()
            key = (f"steady window under {MIN_STEADY_S:.0f} s" if code == "steady_body" else f"steady window under {MIN_STEADY_TIMING_S:.0f} s") if key.startswith("steady window") else \
                "too few rows" if key.startswith("too few rows") else "outlier" if key.startswith("outlier") else key
            key = f"floor label older than {MAX_SURFACE_AGE_H:.0f} h" if code == "floor_age" else f"over {MAX_LATE_FRACTION * 100:.0f}% of ticks late" if code == "late" else \
                f"IMU stale for over {MAX_IMU_AGE_S:.0f} s" if code == "imu" else key
            key += " [body fits only]" if code in BODY_ONLY else ""
            reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        lines.append("why runs are kept out of a fit (a run can have several reasons):")
        lines += [f"  {n:3d}  {w}" for w, n in sorted(reasons.items(), key=lambda kv: -kv[1])]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", default=os.path.expanduser("~/g2_data/raw_auto"))
    ap.add_argument("--store", default=os.path.expanduser("~/g2_data/store"))
    a = ap.parse_args(argv)
    if not os.path.isdir(a.raw):
        print(f"no raw folder at {a.raw} (run `g2data sync` first)")
        return 1
    print(status_text(ingest(a.raw, a.store)))
    print(f"store: {a.store}  (manifest.json; logs compressed, nothing deleted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
