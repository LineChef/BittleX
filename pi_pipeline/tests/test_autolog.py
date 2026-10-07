"""Automatic run logs (telemetry/autolog.py), hardware epochs, and the hook in run_gait.run(): every policy walk without --log is captured with a sidecar that says why it ended."""
import importlib.util
import json
import os
import sys
from datetime import datetime

import pytest

from pi_pipeline.telemetry import autolog, epochs

_GAIT_DIR = os.path.join(os.path.dirname(__file__), "..", "gait")


@pytest.fixture
def on(monkeypatch, tmp_path):
    monkeypatch.setenv("G2_AUTOLOG", "on")
    monkeypatch.setenv("G2_AUTOLOG_DIR", str(tmp_path / "auto"))
    monkeypatch.setattr(autolog, "SURFACE_FILE", str(tmp_path / "surface"))
    return tmp_path / "auto"


@pytest.fixture(scope="module")
def rg():
    pytest.importorskip("onnxruntime")
    for p in (_GAIT_DIR, os.path.join(_GAIT_DIR, ".."), os.path.join(_GAIT_DIR, "..", "..")):
        sys.path.insert(0, os.path.abspath(p))
    spec = importlib.util.spec_from_file_location("run_gait_under_test_autolog", os.path.join(_GAIT_DIR, "run_gait.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_epochs_pick_the_one_in_force_and_flag_known_faulty_hardware():
    assert epochs.epoch_at(datetime(2026, 9, 1)) is None
    pre_swap = epochs.epoch_at(datetime(2026, 10, 6, 10, 0))
    post_swap = epochs.epoch_at(datetime(2026, 10, 6, 16, 0))
    now = epochs.epoch_at(datetime(2026, 10, 8, 9, 0))
    assert pre_swap["fit_ok"] is False and post_swap["fit_ok"] is True and now["id"] == "hw-2026-10-07"
    assert [e["start"] for e in epochs.load_epochs()] == sorted(e["start"] for e in epochs.load_epochs())


def test_a_new_run_writes_its_sidecar_at_once_and_finish_adds_the_ending(on):
    autolog.set_surface("Kitchen Tile")
    r = autolog.new_run("policy_walk", policy="x.onnx", cmd_fwd=0.1, hz=80.0, now=datetime(2026, 10, 7, 12, 0, 5).timestamp())
    assert r.csv_path.endswith("20261007/policy_walk_120005.csv")
    side = json.load(open(r.csv_path[:-4] + ".json"))
    assert side["surface"] == "kitchen-tile" and side["epoch"] == "hw-2026-10-07" and side["policy"] == "x.onnx" and side["ended"] is None
    r.finish("complete", last_volt_v=7.9)
    side = json.load(open(r.csv_path[:-4] + ".json"))
    assert side["end_reason"] == "complete" and side["ended"] and side["last_volt_v"] == 7.9 and side["duration_s"] >= 0
    again = autolog.new_run("policy_walk", now=datetime(2026, 10, 7, 12, 0, 5).timestamp())
    assert again.csv_path.endswith("policy_walk_120005_2.csv")                     # same second: never overwrites


def test_off_switch_and_failures_never_raise(monkeypatch, tmp_path):
    monkeypatch.setenv("G2_AUTOLOG", "off")
    assert autolog.new_run("policy_walk") is None
    monkeypatch.setenv("G2_AUTOLOG", "on")
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where the folder should be")
    monkeypatch.setenv("G2_AUTOLOG_DIR", str(blocker / "sub"))
    assert autolog.new_run("policy_walk") is None                                   # cannot make the folder: no log, no crash


def test_unfinished_runs_are_marked(on):
    r = autolog.new_run("policy_walk")
    done = autolog.new_run("policy_walk", now=datetime(2026, 10, 7, 13, 0, 0).timestamp())
    done.finish("complete")
    assert autolog.close_orphans(on) == 1
    assert json.load(open(r.csv_path[:-4] + ".json"))["end_reason"] == "unfinished"
    assert json.load(open(done.csv_path[:-4] + ".json"))["end_reason"] == "complete"


class _Link:
    def __init__(self, line):
        self.sent, self._line = [], line

    def send(self, cmd, **kw):
        self.sent.append(cmd)
        return ""

    def poll_imu(self):
        return [self._line]


def _only_run(root):
    csvs = sorted(root.rglob("*.csv"))
    assert len(csvs) == 1
    return csvs[0], json.load(open(str(csvs[0])[:-4] + ".json"))


def test_a_policy_walk_without_a_log_path_is_captured_with_the_extra_columns(rg, on, monkeypatch):
    monkeypatch.setattr(rg, "diag", None)
    rg.run(_Link("MCU:  0.00  0.00  1.00    0.0   0.0   0.0"), 0.10, 0.2, 80.0, "auto", disable_firmware_balance=True, thermal_guard=False, send_every=1)
    csv, side = _only_run(on)
    head = csv.read_text().splitlines()[1].split(",")
    assert head[-6:] == ["ax", "ay", "az", "imu_n", "imu_age_s", "volt"] and len(csv.read_text().splitlines()) > 5
    assert side["end_reason"] == "complete" and side["ended"] and side["cmd_fwd"] == 0.1 and side["in_service"] is False


def test_the_reason_a_walk_ended_is_recorded(rg, on, monkeypatch):
    monkeypatch.setattr(rg, "diag", None)
    rg.run(_Link("MCU:  0.00  0.00  1.00    0.0   0.0  90.0"), 0.10, 5.0, 80.0, "auto", disable_firmware_balance=True, thermal_guard=False, send_every=1)
    assert _only_run(on)[1]["end_reason"] == "fall"


def test_an_explicit_log_path_is_left_alone(rg, on, monkeypatch, tmp_path):
    monkeypatch.setattr(rg, "diag", None)
    rg.run(_Link("MCU:  0.00  0.00  1.00    0.0   0.0   0.0"), 0.10, 0.2, 80.0, "auto", disable_firmware_balance=True, thermal_guard=False, send_every=1,
           log_path=str(tmp_path / "mine.csv"))
    assert (tmp_path / "mine.csv").exists()
    assert not on.exists() or not list(on.rglob("*.csv"))                          # no second, automatic copy
