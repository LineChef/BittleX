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


def write_run(raw, stem, *, seconds=8.0, hz=80.0, end="stopped", epoch="e1", surface="tile", roll_amp=0.08, yaw_drift=0.0, excluded=False, labels=None, age=1.0, late_every=0, volt=8.2,
              policy="p.onnx", extra=None, tail_nan=False):
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
        bad = tail_nan and t[i] > t[-1] - 0.5                  # the last half second is garbage (a fall, a crash)
        lines.append(f"{t[i]:.4f},{'nan' if bad else f'{roll:.5f}'},{pitch:.5f},{yaw_drift * t[i]:.5f},0,0,0,10,ok,0.1,0.2,9.8,{i // 16},0.05,{volt}")
    open(os.path.join(day, stem + ".csv"), "w").write("\n".join(lines) + "\n")
    side = {"kind": "policy_walk", "started": "2026-10-07T14:00:00", "epoch": epoch, "surface": surface, "policy": policy, "surface_age_h": age, "ended": "x", "end_reason": end, **(extra or {})}
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
    write_run(raw, "collided", labels=["collision"])
    write_run(raw, "oldhw", epoch="e0")
    write_run(raw, "tiny", seconds=2.0)              # a 0.5 s steady window: under even the timing fits' 1 s
    write_run(raw, "hand", excluded=True)
    write_run(raw, "testtrim", extra={"foot_trim": [["fl", -0.5]]})
    m = gi.ingest(raw, store, EPOCHS)
    r = by_run(m)
    assert r["good"]["status"] == "usable" and r["good"]["reasons"] == [] and r["good"]["uses"] == ["body", "timing"]
    assert r["hand"]["status"] == "excluded" and "fridge" in r["hand"]["reasons"][0] and r["hand"]["uses"] == []
    for name, word in (("collided", "collision"), ("oldhw", "fit_ok"), ("tiny", "steady window"), ("testtrim", "steering")):
        assert r[name]["status"] == "quarantined" and r[name]["uses"] == [] and any(word in w for w in r[name]["reasons"]), name
    assert len(os.listdir(os.path.join(store, "20261007"))) >= 6 * 2                           # every run is kept: a compressed log and its sidecar, nothing deleted
    assert os.path.isfile(os.path.join(store, "manifest.json"))


def test_each_fit_names_the_gates_it_needs_so_a_run_can_feed_the_timing_fits_alone(gi, tmp_path):
    """User, 2026-10-18: gate per fit, not per run. The floor, the 2 s window, the late-tick share and the outlier screen guard the body fits only."""
    raw, store = str(tmp_path / "raw"), str(tmp_path / "store")
    write_run(raw, "nofloor", surface="unknown")
    write_run(raw, "staleflor", age=100.0)           # the limit is 72 hours (user, 2026-10-08)
    write_run(raw, "oldish", age=30.0)               # 30 h old: fine
    write_run(raw, "short", seconds=2.6)             # a 1.1 s steady window: enough for timing, not for the body statistics
    write_run(raw, "late", late_every=5)
    r = by_run(gi.ingest(raw, store, EPOCHS))
    assert r["oldish"]["uses"] == ["body", "timing"]
    for name, word in (("nofloor", "floor not set"), ("staleflor", "old"), ("short", "steady window"), ("late", "late")):
        assert r[name]["status"] == "usable" and r[name]["uses"] == ["timing"] and any(word in w for w in r[name]["reasons"]), name
    assert gi.uses_for([]) == ["body", "timing"] and gi.uses_for(["floor", "late"]) == ["timing"] and gi.uses_for(["steering"]) == [] and gi.uses_for(["excluded"]) == []
    assert gi.uses_of({"status": "usable"}) == ["body", "timing"] and gi.uses_of({"status": "quarantined"}) == []         # a manifest written before the split


def test_a_run_that_ended_badly_loses_its_last_second_and_keeps_the_rest(gi, tmp_path):
    raw, store = str(tmp_path / "raw"), str(tmp_path / "store")
    write_run(raw, "fell", end="fall", tail_nan=True)
    write_run(raw, "crashed", end="unfinished", tail_nan=True)
    write_run(raw, "stoppedbad", end="stopped", tail_nan=True)         # a clean stop is not cut: the garbage counts
    r = by_run(gi.ingest(raw, store, EPOCHS))
    for name in ("fell", "crashed"):
        assert r[name]["status"] == "usable" and r[name]["uses"] == ["body", "timing"] and r[name]["metrics"]["cut_end_s"] == 1.0, name
        assert not any("end cleanly" in w for w in r[name]["reasons"])
    assert r["fell"]["end_reason"] == "fall"                        # still there for the event rates
    assert r["stoppedbad"]["status"] == "quarantined" and "missing values" in r["stoppedbad"]["reasons"]
    head, rows = gi.read_csv(os.path.join(raw, "20261007", "fell.csv"))
    t = gi.column(head, rows, "t")
    keep, steady = gi.window(t, "fall")
    assert t[keep][-1] == pytest.approx(t[-1] - 1.0, abs=0.02) and steady.sum() < gi.window(t, "stopped")[1].sum()


def test_the_everyday_foot_trim_is_his_normal_gait_and_a_test_trim_is_not(gi, tmp_path):
    raw, store = str(tmp_path / "raw"), str(tmp_path / "store")
    v7 = "Release_CandidateV7_ppo.onnx"
    write_run(raw, "daily", policy=v7, extra={"foot_trim": [["fl", -0.3]]})                 # DEFAULT_TRIMS for V7
    write_run(raw, "daily_marked", policy="other.onnx", extra={"foot_trim": [["fl", -0.3]], "foot_trim_source": "everyday"})
    write_run(raw, "test_amount", policy=v7, extra={"foot_trim": [["fl", -0.5]]})
    write_run(raw, "test_foot", policy=v7, extra={"foot_trim": [["bl", -0.3]]})
    write_run(raw, "unknown_policy", policy="other.onnx", extra={"foot_trim": [["fl", -0.3]]})
    write_run(raw, "hold", policy=v7, extra={"heading_hold": True})
    write_run(raw, "const", policy=v7, extra={"steer_const": 0.2})
    write_run(raw, "scripted", policy=v7, extra={"scripted": True})
    write_run(raw, "hold_and_daily_trim", policy=v7, extra={"foot_trim": [["fl", -0.3]], "scripted": True})
    r = by_run(gi.ingest(raw, store, EPOCHS))
    assert r["daily"]["status"] == r["daily_marked"]["status"] == "usable"
    for name in ("test_amount", "test_foot", "unknown_policy", "hold", "const", "scripted", "hold_and_daily_trim"):
        assert r[name]["status"] == "quarantined" and r[name]["uses"] == [] and "steering test run" in r[name]["reasons"][0], name
    assert "foot_trim" in r["test_amount"]["reasons"][0] and "foot_trim" not in r["hold_and_daily_trim"]["reasons"][0]


def test_everyday_trims_come_from_the_default_table_the_attachment_gait_and_its_per_floor_trims(gi, tmp_path):
    prof = tmp_path / "gait_profiles.json"
    json.dump({"head": {"current": {"policy": "pod.onnx", "trim": "fl=-0.2", "trim_by_floor": {"tile": "fl=-0.4/fr=0.1"}},
                        "history": [{"policy": "pod.onnx", "trim": "fl=-0.1"}]}, "none": {"current": None, "history": []}}, open(prof, "w"))
    t = gi.everyday_trims("pod.onnx", "tile", str(prof))
    assert t == {(("fl", -0.2),), (("fl", -0.1),), (("fl", -0.4), ("fr", 0.1))}
    assert gi.everyday_trims("pod.onnx", "hardwood", str(prof)) == {(("fl", -0.2),), (("fl", -0.1),)}       # the tile trim is not the hardwood one
    assert gi.everyday_trims("Release_CandidateV7_ppo.onnx", None, str(prof)) == {(("fl", -0.3),)}
    assert gi.everyday_trims("nobody.onnx", None, str(tmp_path / "missing.json")) == set()
    assert gi.trim_key(None) is None and gi.trim_key("off") is None and gi.trim_key([["FL", -0.30001]]) == (("fl", -0.3),) and gi.trim_key("fl=-0.3/fr=+0.1") == (("fl", -0.3), ("fr", 0.1))


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
    assert m["wild"]["uses"] == ["timing"] and "outlier on roll_std_deg" in m["wild"]["reasons"][0]          # a body-statistics outlier: still good for the loop-timing fits
    assert sum(1 for x in m.values() if "body" in x["uses"]) == 8
    text = gi.status_text({"runs": list(m.values())})
    assert "usable" in text and "usable for: body fits 8, timing fits 9" in text and "outlier [body fits only]" in text


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
    assert all(x["uses"] == ["timing"] and any("floor not confirmed" in w for w in x["reasons"]) for x in r.values())            # out of the body fits until a person says what floor
    json.dump([{"from": start[:11] + "00:00", "to": start[:11] + "23:59", "surface": "tile"}], open(str(tmp_path / "data" / "floor_overrides.json"), "w"))
    m = gi.ingest(raw, store, EPOCHS)
    assert {x["run"]: x["surface"] for x in gi.ingest(raw, store, EPOCHS)["runs"]}["b"] == "tile"          # the person's word replaces the recorded label


def test_a_run_is_re_tagged_with_the_epoch_in_force_when_it_started():
    import importlib.util, os
    spec = importlib.util.spec_from_file_location("g2_ingest_t", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "g2_ingest.py"))
    G = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(G)
    eps = {e["id"]: e for e in [{"id": "a", "start": "2026-10-07T08:00"}, {"id": "b", "start": "2026-10-17T00:00"}, {"id": "c", "start": "2026-10-18T00:00"}]}
    assert G.epoch_at("2026-10-18T08:30:40", eps) == "c" and G.epoch_at("2026-10-17T12:00:00", eps) == "b"
    assert G.epoch_at("2026-10-10T09:00:00", eps) == "a" and G.epoch_at("2026-10-01T09:00:00", eps) is None and G.epoch_at(None, eps) is None
