#!/usr/bin/env python3
"""Ingest G2's automatic run logs into the real-data store (Phase 2 of docs/rl/real-data-pipeline.md).

    python tools/g2_ingest.py [--raw ~/g2_data/raw_auto] [--store ~/g2_data/store]          (the g2data alias: `g2data sync | ingest | status`)

For every run (`<run>.csv` + `<run>.json` sidecar, optional `<run>.labels.json`) it measures the log, applies the ingest gates, compresses the log losslessly (gzip) into the store and writes `manifest.json`.
NOTHING is deleted and nothing raw is changed: a run that fails a gate is **quarantined** with its reasons (or **excluded** when a person flagged it), and stays in the store. Only `usable` runs may feed a fit.
Drift (yaw / heading) and mean lean are measured and stored under `monitor` for audits only; the gates and the fit inputs never use them (see "Keeping drift out of the sim").

Gates (a run is usable only if all pass): not flagged excluded; closed cleanly (ended `stopped` or `complete`, not a fall, a crash, a stale IMU or a battery stop); no fall / collision / pickup label; hardware epoch marked `fit_ok`; surface known (label set within 12 h,
or set before the label kept a timestamp); a steady window of at least 2 s after the first 1.5 s; control loop on time (under 5% of ticks late); IMU frames fresh (no stretch over 1 s); no missing values in the used columns; not a statistical outlier
(more than 4 robust sigma from its group on roll or pitch spread; groups of 6 or more runs). Pack voltage is tagged by band (full 8.0 V and over, mid 7.6 to 8.0, low under 7.6) and groups are never mixed across bands.
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

FIRST_SKIP_S = 1.5            # the stand and ramp-in at the start of every run
MIN_STEADY_S = 2.0
LATE_TICK_S = 0.025           # two control ticks at 80 Hz
MAX_LATE_FRACTION = 0.05
MAX_IMU_AGE_S = 1.0
MAX_SURFACE_AGE_H = 12.0
GOOD_END = ("stopped", "complete")
BAD_LABELS = ("fall", "collision", "pickup")
MAX_HOLD_U = 0.30             # the front-foot heading hold (on in every walk since 2026-10-07) is active much of the time on tile (median mean |u| 0.19); above 0.30 it was doing most of the steering
MIN_GROUP = 6
OUTLIER_SIGMA = 4.0


def volt_band(v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return "unknown"
    return "full" if v >= 8.0 else "mid" if v >= 7.6 else "low"


def load_epochs(path: str = EPOCHS_PATH) -> dict:
    try:
        return {e["id"]: e for e in json.load(open(path))}
    except (OSError, ValueError):
        return {}


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


def measure(csv_path: str) -> dict:
    head, rows = read_csv(csv_path)
    m: dict = {"rows": len(rows)}
    t = column(head, rows, "t")
    if t is None or len(t) < 5:
        return m
    dt = np.diff(t)
    m.update(duration_s=round(float(t[-1] - t[0]), 2), tick_median_ms=round(float(np.median(dt)) * 1e3, 2), late_fraction=round(float((dt > LATE_TICK_S).mean()), 4),
             time_increasing=bool((dt > 0).all()))
    steady = t >= (t[0] + FIRST_SKIP_S)
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
        if c is not None and np.isnan(c).any():
            m["missing_values"] = True
    u = column(head, rows, "steer_u")
    if u is not None and steady.sum() > 2 and np.isfinite(u[steady]).any():
        m["steer_u_mean_abs"] = round(float(np.nanmean(np.abs(u[steady]))), 3)            # how hard the heading hold worked in the steady window
    n, age, volt, az = (column(head, rows, c) for c in ("imu_n", "imu_age_s", "volt", "az"))
    if n is not None:
        m["imu_fresh_hz"] = round(float((np.diff(n) > 0).sum() / max(t[-1] - t[0], 1e-9)), 2)
    if age is not None and np.isfinite(age).any():
        m["imu_age_max_s"] = round(float(np.nanmax(age)), 3)
    if volt is not None and np.isfinite(volt).any():
        m["volt_mean"] = round(float(np.nanmean(volt)), 2)
    if az is not None and np.isfinite(az).any():
        m["az_median"] = round(float(np.nanmedian(az)), 2)
    return m


def floor_confirmed(side: dict, confirmed: list) -> bool:
    """A person confirmed the floor for this run's time (`~/g2_data/floor_confirmed.json`: [{"from": "2026-10-08T08:00", "to": "2026-10-08T11:00", "surface": "tile"}]):
    the label that was set earlier was still right, so its age does not matter."""
    t = (side.get("started") or "")[:16]
    return any(c.get("surface") == side.get("surface") and c["from"][:16] <= t <= c["to"][:16] for c in confirmed)


def gate(side: dict, labels: list, m: dict, epochs: dict, confirmed: list | None = None) -> list[str]:
    """Reasons a run may not feed a fit (empty list = usable). 'excluded' means a person said so."""
    why: list[str] = []
    if side.get("excluded"):
        return ["excluded: " + str(side.get("excluded_reason", "flagged by a person"))]
    if side.get("end_reason") not in GOOD_END:
        why.append(f"did not end cleanly ({side.get('end_reason')})")
    applied = [k for k in ("heading_hold", "steer_const", "foot_trim", "scripted") if side.get(k)]
    if applied:                          # a test walk with a steering intervention or no learned correction: not G2's natural gait, never a fit source
        why.append("steering test run (" + ", ".join(applied) + "): never fed to the sim")
    if side.get("foot_hold") and m.get("steer_u_mean_abs", 0.0) > MAX_HOLD_U:
        why.append(f"the front-foot heading hold worked hard (mean |u| {m['steer_u_mean_abs']:.2f} > {MAX_HOLD_U}): not G2's natural gait")
    bad = sorted({x["tag"] for x in labels if x.get("tag") in BAD_LABELS})
    if bad:
        why.append("labelled " + ", ".join(bad))
    ep = epochs.get(side.get("epoch"))
    if ep is None or not ep.get("fit_ok"):
        why.append(f"hardware epoch {side.get('epoch')} is not marked fit_ok")
    if side.get("surface") in (None, "", "unknown"):
        why.append("floor not set")
    age = side.get("surface_age_h")
    if age is not None and age > MAX_SURFACE_AGE_H and not floor_confirmed(side, confirmed or []):
        why.append(f"floor label is {age:.0f} h old")
    if m.get("rows", 0) < 5:
        why.append(f"too few rows ({m.get('rows', 0)})")                 # a run stopped almost at once: nothing to judge, not a damaged log
        return why
    if not m.get("time_increasing", False):
        why.append("time does not increase (damaged log)")
    if m.get("steady_s", 0.0) < MIN_STEADY_S:
        why.append(f"steady window {m.get('steady_s', 0.0):.1f} s is under {MIN_STEADY_S:.0f} s")
    if m.get("late_fraction", 1.0) > MAX_LATE_FRACTION:
        why.append(f"{m.get('late_fraction', 1.0) * 100:.0f}% of ticks late")
    if m.get("imu_age_max_s") is not None and m["imu_age_max_s"] > MAX_IMU_AGE_S:
        why.append(f"IMU stale for {m['imu_age_max_s']:.1f} s")
    if m.get("missing_values"):
        why.append("missing values")
    return why


def outliers(entries: list[dict]) -> None:
    """Quarantine runs far from the rest of their group (epoch, surface, voltage band, policy) on roll or pitch spread. Robust: median and MAD."""
    groups: dict = {}
    for e in entries:
        if e["status"] == "usable":
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
                if abs(val - med) / mad > OUTLIER_SIGMA and x["status"] == "usable":
                    x["status"], x["reasons"] = "quarantined", [f"outlier on {key}: {val:.1f} vs the group's {med:.1f}"]


def ingest(raw: str, store: str, epochs: dict | None = None) -> dict:
    epochs = epochs if epochs is not None else load_epochs()
    try:
        confirmed = json.load(open(os.path.join(os.path.dirname(os.path.abspath(raw)), "floor_confirmed.json")))
    except (OSError, ValueError):
        confirmed = []
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
            m = measure(csv_path) if os.path.isfile(csv_path) else {}
            why = gate(side, labels, m, epochs, confirmed) if m else ["no log file"]
            status = "excluded" if (why and why[0].startswith("excluded")) else "quarantined" if why else "usable"
            e = {"run": stem, "day": day, "kind": side.get("kind"), "policy": side.get("policy"), "epoch": side.get("epoch"), "surface": side.get("surface"), "volt_band": volt_band(m.get("volt_mean")),
                 "started": side.get("started"), "end_reason": side.get("end_reason"), "status": status, "reasons": why, "labels": sorted({x["tag"] for x in labels}),
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
    groups: dict = {}
    for r in runs:
        if r["status"] == "usable":
            k = (r["epoch"], r["surface"], r["volt_band"])
            groups.setdefault(k, [0, 0.0])
            groups[k][0] += 1
            groups[k][1] += r["metrics"].get("steady_s", 0.0)
    if groups:
        lines.append("usable by hardware epoch / floor / pack voltage:")
        lines += [f"  {e} / {s} / {b}: {n} runs, {sec:.0f} s" for (e, s, b), (n, sec) in sorted(groups.items(), key=lambda kv: str(kv[0]))]
    reasons: dict = {}
    for r in runs:
        for w in r["reasons"]:
            key = w.split(":")[0] if w.startswith("excluded") else w.split("(")[0].strip()
            key = "steady window under 2 s" if key.startswith("steady window") else "too few rows" if key.startswith("too few rows") else key
            reasons[key] = reasons.get(key, 0) + 1
    if reasons:
        lines.append("why runs are not usable (a run can have several reasons):")
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
