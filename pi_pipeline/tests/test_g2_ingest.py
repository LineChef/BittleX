"""tools/g2_ingest.py on synthetic runs: gates, quarantine (never deletion), outlier screen, compression, labels, and drift kept out of the gates."""
import gzip
import importlib.util
import json
import os
import sys
import zlib

import numpy as np
import pytest

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "g2_ingest.py")
EPOCHS = {"e1": {"id": "e1", "fit_ok": True}, "e0": {"id": "e0", "fit_ok": False}}


@pytest.fixture(scope="module")
def gi():
    spec = importlib.util.spec_from_file_location("g2_ingest_under_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def write_run(raw, stem, *, seconds=8.0, hz=80.0, end="stopped", epoch="e1", surface="tile", roll_amp=0.08, yaw_drift=0.0, excluded=False, labels=None, age=1.0, late_every=0, volt=8.2):
    day = os.path.join(raw, "20261007")
    os.makedirs(day, exist_ok=True)
    n = int(seconds * hz)
    t = np.arange(n) / hz
    if late_every:
        t = t + (np.arange(n) // late_every) * 0.03
    rng = np.random.default_rng(zlib.crc32(stem.encode()))                     # a fixed seed per run name (the built-in hash() changes from process to process)
    lines = ["# run_gait log", "t,roll,pitch,yaw,gx,gy,gz,j0,guard_state,ax,ay,az,imu_n,imu_age_s,volt"]
    for i in range(n):
        roll = roll_amp * np.sin(2 * np.pi * 1.2 * t[i]) + rng.normal(0, 0.005)
        pitch = 0.04 * np.sin(2 * np.pi * 1.2 * t[i] + 1) + rng.normal(0, 0.003)
        lines.append(f"{t[i]:.4f},{roll:.5f},{pitch:.5f},{yaw_drift * t[i]:.5f},0,0,0,10,ok,0.1,0.2,9.8,{i // 16},0.05,{volt}")
    open(os.path.join(day, stem + ".csv"), "w").write("\n".join(lines) + "\n")
    side = {"kind": "policy_walk", "started": "2026-10-07T14:00:00", "epoch": epoch, "surface": surface, "policy": "p.onnx", "surface_age_h": age, "ended": "x", "end_reason": end}
    if excluded:
        side.update(excluded=True, excluded_reason="hit the fridge")
    json.dump(side, open(os.path.join(day, stem + ".json"), "w"))
    if labels:
        json.dump([{"tag": x} for x in labels], open(os.path.join(day, stem + ".labels.json"), "w"))


def by_run(m):
    return {r["run"]: r for r in m["runs"]}


def test_each_gate_quarantines_with_its_reason_and_keeps_the_log(gi, tmp_path):
    raw, store = str(tmp_path / "raw"), str(tmp_path / "store")
    write_run(raw, "good")
    write_run(raw, "fell", end="fall")
    write_run(raw, "collided", labels=["collision"])
    write_run(raw, "oldhw", epoch="e0")
    write_run(raw, "nofloor", surface="unknown")
    write_run(raw, "staleflor", age=100.0)           # the limit is 72 hours (user, 2026-10-08)
    write_run(raw, "oldish", age=30.0)               # 30 h old: fine now
    write_run(raw, "short", seconds=2.5)
    write_run(raw, "late", late_every=5)
    write_run(raw, "hand", excluded=True)
    m = gi.ingest(raw, store, EPOCHS)
    r = by_run(m)
    assert r["good"]["status"] == "usable" and r["good"]["reasons"] == []
    assert r["oldish"]["status"] == "usable"
    assert r["hand"]["status"] == "excluded" and "fridge" in r["hand"]["reasons"][0]
    for name, word in (("fell", "end cleanly"), ("collided", "collision"), ("oldhw", "fit_ok"), ("nofloor", "floor not set"), ("staleflor", "old"), ("short", "steady window"), ("late", "late")):
        assert r[name]["status"] == "quarantined" and any(word in w for w in r[name]["reasons"]), name
    assert len(os.listdir(os.path.join(store, "20261007"))) >= 9 * 2                           # every run is kept: a compressed log and its sidecar, nothing deleted
    assert os.path.isfile(os.path.join(store, "manifest.json"))


def test_the_store_is_a_lossless_gzip_of_the_raw_log(gi, tmp_path):
    raw, store = str(tmp_path / "raw"), str(tmp_path / "store")
    write_run(raw, "good")
    gi.ingest(raw, store, EPOCHS)
    assert gzip.open(os.path.join(store, "20261007", "good.csv.gz"), "rb").read() == open(os.path.join(raw, "20261007", "good.csv"), "rb").read()
    assert os.path.getsize(os.path.join(store, "20261007", "good.csv.gz")) < os.path.getsize(os.path.join(raw, "20261007", "good.csv"))


def test_drift_is_stored_for_audit_and_never_changes_a_gate(gi, tmp_path):
    raw, store = str(tmp_path / "raw"), str(tmp_path / "store")
    write_run(raw, "straight", yaw_drift=0.0)
    write_run(raw, "drifting", yaw_drift=0.8)                                                  # about 46 deg per second: huge drift
    m = by_run(gi.ingest(raw, store, EPOCHS))
    assert m["straight"]["status"] == m["drifting"]["status"] == "usable"                      # same verdict
    assert m["drifting"]["metrics"]["monitor"]["yaw_change_deg"] > 100 and "yaw_change_deg" not in {k for k in m["drifting"]["metrics"] if k != "monitor"}


def test_a_run_far_from_its_group_is_quarantined_for_review_not_dropped(gi, tmp_path):
    raw, store = str(tmp_path / "raw"), str(tmp_path / "store")
    for i in range(8):
        write_run(raw, f"n{i}", roll_amp=0.08 + 0.002 * i)
    write_run(raw, "wild", roll_amp=0.40)
    m = by_run(gi.ingest(raw, store, EPOCHS))
    assert m["wild"]["status"] == "quarantined" and "outlier on roll_std_deg" in m["wild"]["reasons"][0]
    assert sum(1 for x in m.values() if x["status"] == "usable") == 8
    assert "usable" in gi.status_text({"runs": list(m.values())})


def test_groups_are_never_mixed_across_voltage_bands(gi, tmp_path):
    raw, store = str(tmp_path / "raw"), str(tmp_path / "store")
    for i in range(7):
        write_run(raw, f"full{i}", roll_amp=0.08 + 0.001 * i, volt=8.3)
    for i in range(7):
        write_run(raw, f"low{i}", roll_amp=0.20 + 0.001 * i, volt=7.4)                         # a sagged pack swings more: a different group, so neither is an outlier
    m = by_run(gi.ingest(raw, store, EPOCHS))
    assert all(x["status"] == "usable" for x in m.values()) and {x["volt_band"] for x in m.values()} == {"full", "low"}


def test_a_floor_override_replaces_the_recorded_label_and_unknown_takes_runs_out_of_the_fits(gi, tmp_path):
    raw = str(tmp_path / "data" / "raw_auto")
    store = str(tmp_path / "data" / "store")
    write_run(raw, "a")
    write_run(raw, "b", surface="hardwood")
    write_run(raw, "c")
    side = json.load(open(os.path.join(raw, "20261007", "a.json")))
    start = side["started"]
    assert gi.floor_override({"started": start}, [{"from": start[:11] + "00:00", "to": start[:11] + "23:59", "surface": "unknown"}]) == "unknown"
    json.dump([{"from": start[:11] + "00:00", "to": start[:11] + "23:59", "surface": "unknown"}], open(str(tmp_path / "data" / "floor_overrides.json"), "w"))
    m = gi.ingest(raw, store, EPOCHS)
    r = {x["run"]: x for x in m["runs"]}
    assert all(x["status"] == "quarantined" and any("floor not confirmed" in w for w in x["reasons"]) for x in r.values())
    json.dump([{"from": start[:11] + "00:00", "to": start[:11] + "23:59", "surface": "tile"}], open(str(tmp_path / "data" / "floor_overrides.json"), "w"))
    m = gi.ingest(raw, store, EPOCHS)
    assert {x["run"]: x["surface"] for x in gi.ingest(raw, store, EPOCHS)["runs"]}["b"] == "tile"          # the person's word replaces the recorded label
