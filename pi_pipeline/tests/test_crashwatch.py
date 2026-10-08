"""diag/crashwatch.py: a process that never marked itself clean is reported at the next start, with its stage and resources."""
import json
import logging

from pi_pipeline.diag import crashwatch
from pi_pipeline.diag.crashwatch import CrashWatch, StageTap


def test_an_unclean_previous_run_is_reported_with_its_stage_and_fault_trace(tmp_path, caplog):
    old = CrashWatch("voice", directory=tmp_path, extras=lambda: {"mic_peak": 321})
    old.set_stage("listening")
    old._write(clean=False)
    state = json.loads(old.state_path.read_text())
    state["pid"] = 999999                                   # a different (dead) process
    old.state_path.write_text(json.dumps(state))
    old.fault_path.write_text("Fatal Python error: Segmentation fault\n\nThread 0x1 (most recent call first):\n  File \"stt.py\", line 99 in listen\n")
    new = CrashWatch("voice", directory=tmp_path)
    with caplog.at_level(logging.WARNING):
        rec = new.report_previous()
    assert rec["stage"] == "listening" and rec["extras"] == {"mic_peak": 321} and rec["pid"] == 999999
    assert any("without a clean shutdown" in r.getMessage() and "listening" in r.getMessage() for r in caplog.records)
    assert any("Segmentation fault" in r.getMessage() for r in caplog.records)
    rows = crashwatch.history(5, tmp_path)
    assert len(rows) == 1 and "stt.py" in " ".join(rows[0]["fault"])
    assert not new.fault_path.exists()                     # the trace was moved aside, not reported twice


def test_a_clean_exit_and_a_first_run_report_nothing(tmp_path):
    assert CrashWatch("voice", directory=tmp_path).report_previous() is None      # no file yet
    w = CrashWatch("voice", directory=tmp_path)
    w._write(clean=False)
    w.stop()
    state = json.loads(w.state_path.read_text())
    assert state["clean"] is True
    state["pid"] = 999999
    w.state_path.write_text(json.dumps(state))
    assert CrashWatch("voice", directory=tmp_path).report_previous() is None
    assert crashwatch.history(5, tmp_path) == []


def test_stage_tap_records_the_stage_and_passes_it_on(tmp_path):
    seen = []

    class Inner:
        def set(self, stage): seen.append(stage)

    w = CrashWatch("voice", directory=tmp_path)
    StageTap(Inner(), w).set("listening")
    assert w.stage == "listening" and seen == ["listening"]
    assert json.loads(w.state_path.read_text())["stage"] == "listening"
