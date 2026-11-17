"""tools/g2_run_summary.py (the goal journal's run summary) and tools/pi_read.sh (fixed read-only Pi questions)."""
import importlib.util
import os
import subprocess

_TOOLS = os.path.join(os.path.dirname(__file__), "..", "..", "tools")
_spec = importlib.util.spec_from_file_location("g2_run_summary_under_test", os.path.join(_TOOLS, "g2_run_summary.py"))
rs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rs)

JOURNAL = "\n".join([
    '{"kind": "session_end", "time": "2026-11-16 17:20:01", "session": "s1", "why": "fell", "attempts": 2, "successes": 1, "minutes": 3.5}',
    '{"kind": "attempt", "session": "s1", "number": 10, "time": "2026-11-16 17:18:30", "pack_pct": 44, "outcome": {"code": "hit_unseen", "text": "I punched from 2.9 in and the ball went out of sight"}, '
    '"trace": [{"kind": "after_punt", "watch": "lost", "source": "", "got_it": true, "good_pictures": 18, "claw_moves": 3, "stream_sightings": 3, '
    '"frames": [{"t": 0.0, "d": 1, "mean": 54}, {"t": 0.4, "d": 0, "mean": 117, "blob": [77, 218, 123]}, {"t": 0.8, "bad": 1}]}]}',
    "not json at all",
    '{"kind": "session_end", "time": "2026-11-16 18:00:00", "session": "s2", "why": "battery", "attempts": 3, "successes": 0, "minutes": 4.8}',
    '{"kind": "attempt", "session": "s2", "number": 11, "time": "2026-11-16 17:59:00", "pack_pct": 30, "outcome": {"code": "never_found", "text": "I never saw the ball"}}',
])


def test_the_journal_text_is_parsed_and_junk_lines_are_skipped():
    rows = rs.parse_journal(JOURNAL)
    assert len(rows) == 4 and rows[0]["session"] == "s1"


def test_sessions_are_picked_by_time_or_as_the_latest_ones():
    rows = rs.parse_journal(JOURNAL)
    assert [s["session"] for s in rs.pick_sessions(rows, None, 1)] == ["s2"]
    assert [s["session"] for s in rs.pick_sessions(rows, None, 2)] == ["s1", "s2"]
    assert [s["session"] for s in rs.pick_sessions(rows, "2026-11-16 17:30", 1)] == ["s2"]
    assert rs.pick_sessions(rows, "2026-11-17 00:00", 1) == []


def test_the_summary_lists_sessions_attempts_and_the_active_look_numbers():
    rows = rs.parse_journal(JOURNAL)
    text = "\n".join(rs.summarize(rows, rs.pick_sessions(rows, None, 2)))
    assert "session s1: fell, 2 attempts, 1 successes" in text and "session s2: battery" in text
    assert "10 17:18 hit_unseen pack=44" in text and "11 17:59 never_found pack=30" in text
    assert "watch=lost" in text and "got_it=True" in text and "frames=3 seen=1 bad=1 brightness=54..117" in text and "missed-blobs=[[77, 218, 123]]" in text
    assert "no session ended" in "\n".join(rs.summarize(rows, []))


def test_the_fall_summary_shows_the_tilt_before_it_and_the_last_commands():
    fall = {"when": "2026-11-16 17:19:55", "context": {"last_motion_command": "krest"}, "summary": {"peak_tilt_deg": 179.9, "first_over_20_s": -9.0},
            "trace": [[-1.0, 23.0, 0.0], [-0.4, 84.0, 90.0], [3.0, 1.0, 1.0]], "commands": [{"t": "2026-11-16T17:19:56", "cmd": "gP"}, {"t": "2026-11-16T17:19:57", "cmd": "krest"}]}
    out = "\n".join(rs.summarize_fall(fall))
    assert "last command krest" in out and "-1.0:23/0" in out and "-0.4:84/90" in out and "3.0:1/1" not in out and "17:19:57 krest" in out
    assert rs.summarize_fall(None) == ["no fall record"]


def test_pi_read_only_runs_fixed_subcommands_and_refuses_anything_else():
    env = {**os.environ, "G2_PI": "nobody@invalid.example"}
    sh = os.path.join(_TOOLS, "pi_read.sh")
    bad = subprocess.run(["bash", sh, "journal", "x; rm -rf /"], env=env, capture_output=True, text=True)
    assert bad.returncode == 2 and "refused" in bad.stderr                                   # a pattern with shell characters never reaches ssh
    assert subprocess.run(["bash", sh, "goal-log", "5; id"], env=env, capture_output=True, text=True).returncode == 2
    assert subprocess.run(["bash", sh, "rm"], env=env, capture_output=True, text=True).returncode == 2
    assert subprocess.run(["bash", sh, "journal", "g2.goal|watch:", "10 minutes ago"], env={**env, "PATH": "/nonexistent:/usr/bin:/bin"}, capture_output=True, text=True).returncode != 2   # a good pattern is allowed through (ssh then fails: no such host)


def test_an_unreachable_pi_is_reported_as_could_not_verify_and_never_as_an_empty_answer(monkeypatch, capsys):
    import pytest
    monkeypatch.setenv("G2_PI", "nobody@invalid.example")
    monkeypatch.setattr(rs.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 255, "stdout": ""})())
    assert rs._ssh("true") is None
    monkeypatch.setattr(rs, "_ssh", lambda cmd, timeout=60: None)
    monkeypatch.setattr(rs.sys, "argv", ["g2_run_summary.py"])
    with pytest.raises(SystemExit) as e:
        rs.main()
    assert e.value.code == 3 and "could not verify" in capsys.readouterr().out
