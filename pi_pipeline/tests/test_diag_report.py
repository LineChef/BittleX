"""diag/report.py: one session's walks, speech timing, wake triggers, API calls and problems gathered from their separate logs."""
import json
import time
from datetime import datetime

from pi_pipeline.diag import report
from pi_pipeline.diag.core import Diag


def test_report_gathers_every_log_for_the_session_window(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("G2_AUTOLOG_DIR", str(tmp_path / "auto"))
    monkeypatch.setenv("G2_WAKE_LOG", str(tmp_path / "wake.jsonl"))
    monkeypatch.setenv("G2_API_LOG", str(tmp_path / "api.jsonl"))
    d = Diag()
    sid = d.start_session("explore")
    now = time.time()
    d.event("g2.behavior.narrator", "INFO", "log", msg="narration timing: queued 0.1 s, synthesis 4.0 s, play 2.0 s (incl. waiting for the speaker), 6.1 s from decision to end: Exploring.")
    d.event("g2.behavior.narrator", "INFO", "log", msg="narration dropped (late): Looking around. (queued 0.2 s, synthesis 9.0 s)")
    d.event("g2.policy_walker", "WARNING", "log", msg="the policy walk did not stop within 5 s; the walker thread is at: x")
    d.event("behavior", "WARN", "cliff.reflex", reason="edge")
    d.event("worker", "WARN", "worker.restart", worker="microphone", reason="no heartbeat")
    day = tmp_path / "auto" / datetime.fromtimestamp(now).strftime("%Y%m%d")
    day.mkdir(parents=True)
    started = datetime.fromtimestamp(now).strftime("%Y-%m-%dT%H:%M:%S")
    (day / "policy_walk_1.json").write_text(json.dumps({"started": started, "end_reason": "fall", "late_ticks_pct": 30.0, "worst_tick_gap_ms": 90.0, "surface": "hardwood"}))
    (day / "policy_walk_2.json").write_text(json.dumps({"started": started, "end_reason": "stopped", "late_ticks_pct": 10.0, "surface": "hardwood"}))
    (day / "old.json").write_text(json.dumps({"started": "2020-01-01T00:00:00", "end_reason": "stopped"}))
    t = time.strftime("%Y-%m-%dT%H:%M:%S")
    (tmp_path / "wake.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"t": t, "type": "trigger", "phrase": "gee two", "ignored": False}, {"t": t, "type": "outcome", "heard": "", "words": 0, "result": "empty"},
        {"t": t, "type": "trigger", "phrase": "gee two", "ignored": True}]) + "\n")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    (tmp_path / "api.jsonl").write_text(json.dumps({"ts": ts, "event": "start", "source": "voice", "api": "messages.create"}) + "\n")
    d.close()
    rep = report.build(sid)
    assert rep["walks"]["count"] == 2 and rep["walks"]["falls"] == 1 and rep["walks"]["late_ticks_pct_max"] == 30.0
    assert rep["speech"]["lines"] == 1 and rep["speech"]["dropped"] == 1 and rep["speech"]["decision_to_end_max_s"] == 6.1 and rep["speech"]["walk_stop_timeouts"] == 1
    assert rep["wake"] == {"triggers": 2, "ignored_by_gates": 1, "looked_false": 1, "looked_real": 0}
    assert rep["api"]["billed_calls"] == 1
    assert rep["camera"]["worker_restarts"] == {"microphone": 1}
    assert any("cliff.reflex" in p for p in rep["problems"])
    text = report.to_text(rep)
    assert "walks: 2" in text and "falls 1" in text
    page = report.to_html(rep)
    assert page.startswith("<!doctype html>") and "prefers-color-scheme:dark" in page and "<td class=bad>fall</td>" in page


def test_no_session_gives_none(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_LOG_DIR", str(tmp_path))
    assert report.build() is None
