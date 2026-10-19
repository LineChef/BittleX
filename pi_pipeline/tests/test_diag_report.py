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


def _session(tmp_path, monkeypatch, kind="explore", surface="hardwood", late=2.0, fall=False, stop_timeout=False, cam=0):
    monkeypatch.setenv("G2_LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("G2_AUTOLOG_DIR", str(tmp_path / "auto"))
    monkeypatch.setenv("G2_WAKE_LOG", "off")
    monkeypatch.setenv("G2_API_LOG", str(tmp_path / "api.jsonl"))
    d = Diag()
    sid = d.start_session(kind)
    d.event("g2.behavior.narrator", "INFO", "log", msg="narration timing: queued 0.1 s, synthesis 3.0 s, play 2.0 s (incl. waiting for the speaker), 5.1 s from decision to end: Exploring.")
    if stop_timeout:
        d.event("g2.policy_walker", "WARNING", "log", msg="the policy walk did not stop within 5 s; the walker thread is at: x")
    for _ in range(cam):
        d.event("g2.vision", "WARNING", "log", msg="camera timed out")
    now = time.time()
    day = tmp_path / "auto" / datetime.fromtimestamp(now).strftime("%Y%m%d")
    day.mkdir(parents=True, exist_ok=True)
    (day / "w1.json").write_text(json.dumps({"started": datetime.fromtimestamp(now).strftime("%Y-%m-%dT%H:%M:%S"), "end_reason": "fall" if fall else "stopped", "late_ticks_pct": late, "surface": surface}))
    d.close()
    return sid, now


def _verdicts(rep):
    return {n: ok for n, ok, _d in rep["checks"]}


def test_a_good_roam_passes_every_check_and_a_bad_one_names_what_to_look_at(tmp_path, monkeypatch):
    sid, _ = _session(tmp_path, monkeypatch)
    good = report.build(sid)
    v = _verdicts(good)
    assert v["no falls"] and v["late walk ticks under 5%"] and v["camera answered every time"] and v["walks stop when told"] and v["every walk had a floor label"]
    assert v["no false wake triggers"]                                            # no wake log in this session: 0 triggers, none false
    assert report.headline(good).startswith("session report: ") and "CHECK" not in report.headline(good)
    assert "[ok] no falls" in report.to_text(good) and "<h2>Checks</h2>" in report.to_html(good)

    sid2, _ = _session(tmp_path / "b", monkeypatch, surface="unknown", late=31.0, fall=True, stop_timeout=True, cam=2)
    bad = report.build(sid2)
    v = _verdicts(bad)
    assert not any(v[k] for k in ("no falls", "late walk ticks under 5%", "camera answered every time", "walks stop when told", "every walk had a floor label"))
    h = report.headline(bad)
    assert "CHECK: " in h and "every walk had a floor label" in h and "[CHECK] camera answered every time: 2 timeouts" in report.to_text(bad)


def test_a_report_can_be_limited_to_part_of_a_long_session_and_saved_beside_it(tmp_path, monkeypatch):
    sid, now = _session(tmp_path, monkeypatch)
    assert report.build(sid, since=now + 3600)["speech"]["lines"] == 0            # a window after everything: no narration lines in it
    assert report.build(sid, since=now - 600, until=now + 600)["speech"]["lines"] == 1
    text = report.write_after(sid, now - 600, now + 600, name="explore_120000")
    d = tmp_path / "logs" / sid
    assert text and (d / "explore_120000.txt").read_text().startswith("session ") and (d / "explore_120000.html").read_text().startswith("<!doctype html>")
    assert report.write_after(str(tmp_path / "nowhere")) is None                  # nothing to report is not an error


def test_the_latest_session_of_a_kind(tmp_path, monkeypatch):
    sid_x, _ = _session(tmp_path, monkeypatch, kind="explore")
    sid_v, _ = _session(tmp_path / "v", monkeypatch, kind="voice")
    monkeypatch.setenv("G2_LOG_DIR", str(tmp_path / "logs"))
    assert report.latest_of_kind("explore").endswith(sid_x) and report.latest_of_kind("nothing") is None
