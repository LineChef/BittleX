"""tools/g2_calibrate.py: per-run estimates, the fit checks, the whitelist, snapshots, the harm check's verdict and the approval rules, on synthetic runs."""
import gzip
import importlib.util
import json
import os
import sys

import numpy as np
import pytest

_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "tools", "g2_calibrate.py")


@pytest.fixture()
def gc(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("g2_calibrate_under_test", _PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "STORE", str(tmp_path / "store"))
    monkeypatch.setattr(mod, "CAL", str(tmp_path / "cal"))
    monkeypatch.setattr(mod, "SNAPS", str(tmp_path / "cal" / "snapshots"))
    return mod


def write_run(store, stem, *, seconds=8.0, hz=80.0, imu_hz=5.0, jitter=0.0, day="20261007"):
    d = os.path.join(store, day)
    os.makedirs(d, exist_ok=True)
    n = int(seconds * hz)
    t = np.arange(n) / hz
    if jitter:
        t = t + (np.arange(n) % 50 == 0) * jitter                     # a late tick now and then
        t = np.maximum.accumulate(t)
    imu_n = np.floor(t * imu_hz).astype(int)
    rows = ["t,roll,pitch,yaw,imu_n"] + [f"{a:.4f},0.01,0.02,0.0,{b}" for a, b in zip(t, imu_n)]
    with gzip.open(os.path.join(d, stem + ".csv.gz"), "wt") as f:
        f.write("\n".join(rows) + "\n")


def manifest(names, epoch="e1", surface="tile", yaw=None):
    return {"runs": [{"run": n, "day": "20261007", "status": "usable", "epoch": epoch, "surface": surface, "roll_std_deg": 5.5, "pitch_std_deg": 2.7, "end_reason": "stopped",
                      "metrics": {"steady_s": 6.0, "duration_s": 8.0, "monitor": {"yaw_change_deg": (yaw[i] if yaw else 10.0)}}} for i, n in enumerate(names)]}


EPOCHS = {"e1": {"id": "e1", "fit_ok": True, "start": "2026-10-07T08:00"}}


def test_run_estimates_find_the_imu_rate_and_loop_jitter(gc, tmp_path):
    write_run(str(tmp_path), "a", seconds=10, imu_hz=5.0, jitter=0.02)
    est = gc.run_estimates(*gc.read_run(str(tmp_path / "20261007" / "a.csv.gz")))
    assert est["G2E_IMU_HOLD_STEPS"] == 16 and 4.5 < est["imu_hz"] < 5.5
    assert 10 < est["G2E_CMD_PATH_EXTRA_MS_MAX"] < 25                # the 20 ms late ticks


def test_a_fit_needs_enough_runs_seconds_and_agreement(gc):
    few = gc.fit_param("G2E_IMU_HOLD_STEPS", [16, 16, 16], 20.0)
    assert few["status"] == "insufficient" and "enough runs" in few["reason"]
    good = gc.fit_param("G2E_IMU_HOLD_STEPS", [16] * 12, 100.0, old=16.0)
    assert good["status"] == "ok" and good["value"] == 16 and good["changed"] is False
    split = gc.fit_param("G2E_IMU_HOLD_STEPS", [10, 30] * 8, 100.0)             # odd runs say 10, even runs say 30: not reproducible
    assert split["status"] == "insufficient" and "reproducible" in split["reason"]
    out = gc.fit_param("G2E_CMD_PATH_EXTRA_MS_MAX", [90.0] * 12, 100.0)
    assert out["status"] == "insufficient" and "bounds" in out["reason"]


def test_a_per_run_estimate_that_tracks_the_runs_heading_change_is_dropped(gc):
    vals = [float(i) for i in range(12)]
    p = gc.fit_param("G2E_CMD_PATH_EXTRA_MS_MAX", vals, 100.0, proxy=[v * 3 for v in vals])
    assert p["status"] == "insufficient" and "drift proxy" in p["reason"]
    q = gc.fit_param("G2E_CMD_PATH_EXTRA_MS_MAX", [5.0 + (i % 2) * 0.1 for i in range(12)], 100.0, proxy=[float((i * 7) % 5) for i in range(12)])
    assert "drift proxy" not in q.get("reason", "")


def test_the_whitelist_has_no_yaw_heading_or_drift_key_and_rejects_others(gc):
    for k in gc.WHITELIST:
        assert not any(w in k.upper() for w in gc.FORBIDDEN_WORDS), k
    gc.check_whitelist({"G2E_IMU_HOLD_STEPS": "16"})
    for bad in ("G2E_DRIFT_TORQUE", "G2E_FAC_HEADING", "G2E_MOTOR_FORCE", "G2E_TRAIN_YAW"):
        with pytest.raises(ValueError):
            gc.check_whitelist({bad: "1"})


def test_build_uses_only_usable_runs_of_the_current_fit_ok_epoch(gc, tmp_path):
    names = [f"r{i}" for i in range(12)]
    for n in names:
        write_run(gc.STORE, n, seconds=8, imu_hz=5.0)
    m = manifest(names)
    m["runs"].append(dict(m["runs"][0], run="old", epoch="e0", status="usable"))
    m["runs"].append(dict(m["runs"][0], run="bad", status="quarantined"))
    snap = gc.build(m, gc.STORE, EPOCHS, old_values=lambda k: 16.0 if k == "G2E_IMU_HOLD_STEPS" else 4.0)
    assert snap["epoch"] == "e1" and snap["runs_used"] == 12
    assert snap["env"]["G2E_IMU_HOLD_STEPS"] == "16"
    assert snap["monitor"]["tile"]["roll_std_deg"] == 5.5
    assert "yaw" not in json.dumps(snap["env"]).lower()


def test_snapshots_are_numbered_and_immutable(gc, tmp_path):
    base = {"env": {"G2E_IMU_HOLD_STEPS": "16"}, "params": {}, "epoch": "e1", "made": "t", "runs_used": 1, "seconds_used": 1.0}
    a, b = gc.save_snapshot(dict(base)), gc.save_snapshot(dict(base))
    assert (a, b) == (1, 2) and gc.list_ids() == [1, 2]
    with pytest.raises(PermissionError):
        open(os.path.join(gc.SNAPS, "0001.json"), "w")
    with pytest.raises(ValueError):
        gc.save_snapshot(dict(base, env={"G2E_DRIFT_TORQUE": "1"}))


def cells(fall=0.0, speed=0.09, n=40):
    return {"mirror_gap": 0.04, "cells": [{"id": "T1.1", "tag": "gate", "n": n, "fell_fraction": fall, "speed_mps": speed},
                                          {"id": "T3.1", "tag": "x", "n": n, "fell_fraction": 0.10, "speed_mps": speed}]}


def test_harm_check_blocks_more_flat_falls_a_worse_mirror_gap_or_a_slower_cell(gc):
    assert gc.evaluate_harm(cells(), cells())["status"] == "passed"
    assert gc.evaluate_harm(cells(), cells(fall=0.025))["status"] == "failed"                    # one more flat-ground fall
    worse = cells(); worse["mirror_gap"] = 0.10
    assert "mirror" in gc.evaluate_harm(cells(), worse)["problems"][0]
    assert gc.evaluate_harm(cells(), cells(speed=0.07))["status"] == "failed"
    assert gc.evaluate_harm(cells(), cells(speed=0.088))["status"] == "passed"                   # within noise


def snap_with(params, harm="passed", epoch="e1"):
    return {"params": params, "epoch": epoch, "env": {k: str(v["value"]) for k, v in params.items() if v.get("status") == "ok"}, "harm_check": {"status": harm}}


OK = {"status": "ok", "value": 16, "old": 16.0, "changed": False, "within_noise": True, "noise": 0.5}


def test_approval_rules(gc):
    human = {"epoch": "e1", "env": {"G2E_IMU_HOLD_STEPS": "16"}}
    assert gc.decide(snap_with({"G2E_IMU_HOLD_STEPS": OK}), human)[0] == "auto_approved"
    assert gc.decide(snap_with({"G2E_IMU_HOLD_STEPS": OK}), None)[0] == "needs_user"                 # the first snapshot is always reviewed
    assert gc.decide(snap_with({"G2E_IMU_HOLD_STEPS": OK}, epoch="e2"), human)[0] == "needs_user"
    moved = dict(OK, value=20, changed=True, within_noise=False)
    assert gc.decide(snap_with({"G2E_IMU_HOLD_STEPS": moved}), human)[0] == "needs_user"
    assert gc.decide(snap_with({"G2E_IMU_HOLD_STEPS": OK}, harm="failed"), human)[0] == "blocked"
    assert gc.decide(snap_with({"G2E_IMU_HOLD_STEPS": OK}, harm="not run"), human)[0] == "pending harm check"
    assert gc.decide(snap_with({"G2E_IMU_HOLD_STEPS": {"status": "insufficient", "reason": "x"}}), human)[0] == "empty"


def test_auto_waits_for_data_then_builds_checks_and_applies_the_rules(gc, tmp_path, monkeypatch):
    names = [f"r{i}" for i in range(12)]
    for n in names:
        write_run(gc.STORE, n, seconds=8, imu_hz=5.0)
    os.makedirs(gc.STORE, exist_ok=True)
    json.dump(manifest(names[:4]), open(os.path.join(gc.STORE, "manifest.json"), "w"))
    monkeypatch.setattr(gc.ingest, "load_epochs", lambda *a: EPOCHS)
    monkeypatch.setattr(gc, "profile_value", lambda k: 16.0 if k == "G2E_IMU_HOLD_STEPS" else 4.0)
    assert "waiting for data" in gc.auto(log=lambda *_: None)
    json.dump(manifest(names), open(os.path.join(gc.STORE, "manifest.json"), "w"))
    monkeypatch.setattr(gc, "run_harm_check", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("busy")))
    assert "idle Mac" in gc.auto(log=lambda *_: None)                      # built, waiting for its harm check
    assert gc.list_ids() == [1] and gc.read_current() is None
    monkeypatch.setattr(gc, "run_harm_check", lambda *a, **k: {"status": "passed", "problems": []})
    out = gc.auto(log=lambda *_: None)
    assert "needs_user" in out and gc.read_current() is None                # the first snapshot always waits for a person
    assert gc.list_ids() == [1]                                             # no second snapshot for the same data
    assert gc.main(["approve", "1"]) == 0 and gc.read_current() == 1
    assert gc.current_env() == {"G2E_IMU_HOLD_STEPS": "16", **{k: v for k, v in gc.load_snapshot(1)["env"].items()}}


def test_g2_profile_loads_only_the_approved_snapshot(tmp_path, monkeypatch):
    gym = os.path.join(os.path.dirname(__file__), "..", "..", "rl_training", "opencat-gym")
    monkeypatch.syspath_prepend(gym)
    monkeypatch.setenv("G2_DATA_DIR", str(tmp_path))
    import g2_profile
    assert g2_profile.calibration_snapshot() == ({}, None) and "G2_CAL_ID" not in g2_profile.env_for()
    cal = tmp_path / "calibration"
    (cal / "snapshots").mkdir(parents=True)
    (cal / "snapshots" / "0003.json").write_text(json.dumps({"env": {"G2E_IMU_HOLD_STEPS": "12", "G2E_DRIFT_TORQUE": "9"}}))
    (cal / "current.json").write_text(json.dumps({"id": 3}))
    env = g2_profile.env_for()
    assert env["G2E_IMU_HOLD_STEPS"] == "12" and env["G2_CAL_ID"] == "0003" and env.get("G2E_DRIFT_TORQUE") != "9"      # a key off the list is ignored
    monkeypatch.setenv("G2_CAL_SNAPSHOT", "off")
    assert g2_profile.env_for()["G2E_IMU_HOLD_STEPS"] == "16"
