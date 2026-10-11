"""Reflection (docs/plan-detail/reflection-plan.md): the session recap (level 1), the notes (level 2) and the spoken answers (level 3)."""
import json
import time

from pi_pipeline.memory.consolidate import ConsolidationWatcher
from pi_pipeline.memory.store import Store
from pi_pipeline.reflection.recap import ExperienceLog, SessionTally, build_recap, recap_text
from pi_pipeline.reflection.reflect import ExperienceReflector, experience_notes, validate_notes
from pi_pipeline.voice.commands import match_local_command


def _wall_log(tmp_path, t0):
    lines = [{"t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0 + 5)), "state": "near", "nearest_in": 9.4, "calibrated": True},
             {"t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0 + 20)), "state": "clear", "nearest_in": None, "calibrated": True},
             {"t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0 + 30)), "state": "far", "nearest_in": 40.0, "calibrated": False},        # uncalibrated looks are not counted
             {"t": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0 - 500)), "state": "near", "nearest_in": 2.0, "calibrated": True}]       # before the session
    p = tmp_path / "wall.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return str(p)


def test_the_tally_counts_only_the_named_events_and_passes_the_rest_on():
    seen = []
    t = SessionTally()
    d = t.wrap(lambda n, r: seen.append(n))
    for n in ("wall.steer", "wall.steer", "wall.hit", "mode", "survey.start"):
        d(n, "why")
    t.note("fall")
    assert t.counts() == {"wall.steer": 2, "wall.hit": 1, "survey.start": 1, "fall": 1} and seen == ["wall.steer", "wall.steer", "wall.hit", "mode", "survey.start"]


def test_the_recap_joins_the_tally_the_stops_and_the_wall_looks_and_reads_in_plain_words(tmp_path):
    t0 = time.time() - 840
    tally = SessionTally()
    for n in ("wall.steer",) * 3 + ("wall.hit",):
        tally.note(n)
    stops = [{"detections": [{"label": "cat"}, {"label": "cat"}]}, {"detections": [{"label": "cat"}, {"label": "dog"}]}, {"detections": []}]
    r = build_recap(tally, started=t0, ended=t0 + 840, ended_by="stop command", stops=stops, wall_path=_wall_log(tmp_path, t0))
    assert r["duration_s"] == 840 and r["stops"] == 3 and r["seen"] == {"cat": 2, "dog": 1} and r["wall"] == {"looks": 2, "near": 1, "closest_in": 9.4}
    text = recap_text(r)
    assert text.startswith("I explored for about 14 minutes.") and "stopped 3 times" in text and "a cat at 2 stops" in text and "turned away from a wall 3 times" in text
    assert "bumped into something once" in text and "about 9 inches" in text and "Nothing went wrong" not in text
    assert "Nothing went wrong" in recap_text(build_recap(SessionTally(), started=t0, ended=t0 + 90))
    assert "nothing to tell" in recap_text({})


def test_recaps_are_numbered_and_read_back(tmp_path):
    log = ExperienceLog(str(tmp_path / "e.jsonl"))
    assert log.latest() is None and log.after(0) == []
    assert log.append({"duration_s": 60})["id"] == 1 and log.append({"duration_s": 120})["id"] == 2
    assert log.latest()["duration_s"] == 120 and [r["id"] for r in log.after(1)] == [2]
    assert ExperienceLog(str(tmp_path / "no" / "such")).append({"x": 1})["id"] == 1                 # the folder is created


def test_notes_must_be_first_person_short_timeless_and_new():
    plan = {"notes": [{"text": "I keep turning away from walls.", "importance": 2},
                      {"text": "The kitchen is where they cook dinner.", "importance": 2},          # not about himself
                      {"text": "I explored this morning.", "importance": 1},                         # a time of day
                      {"text": "I keep turning away from the walls.", "importance": 1},             # a near-duplicate of the first
                      {"text": "I rarely reach the foyer.", "importance": 9},
                      {"text": "I " + "x" * 200, "importance": 1}]}
    assert validate_notes(plan, ["I fell down once on the rug."]) == [{"text": "I keep turning away from walls.", "importance": 2}, {"text": "I rarely reach the foyer.", "importance": 2}]
    assert validate_notes(plan, ["I keep turning away from walls."]) == [{"text": "I rarely reach the foyer.", "importance": 2}]
    assert validate_notes(None, []) == [] and validate_notes({"notes": "nope"}, []) == []


def _reflector(tmp_path, notes, mode):
    st = Store(str(tmp_path / "m.db"))
    log = ExperienceLog(str(tmp_path / "e.jsonl"))
    log.append({"started": "2026-10-10 10:00:00", "duration_s": 600, "events": {"wall.steer": 4}, "stops": 2, "seen": {"cat": 2}})
    calls = []

    def llm(system, user):
        calls.append(json.loads(user))
        return json.dumps({"notes": notes}), None
    return st, log, ExperienceReflector(st, llm, log, mode=mode, dry_path=str(tmp_path / "dry.jsonl")), calls


def test_dry_mode_logs_what_it_would_save_and_waits_for_a_new_session(tmp_path):
    st, log, rf, calls = _reflector(tmp_path, [{"text": "I turned away from walls four times.", "importance": 2}], "dry")
    assert rf.has_enough_new()
    out = rf.run(apply=True)                                       # the idle watcher's call
    assert out["applied"] is False and out["would_save"] == ["I turned away from walls four times."] and experience_notes(st) == []
    assert json.loads((tmp_path / "dry.jsonl").read_text())["after_session"] == 1
    assert not rf.has_enough_new() and calls[0]["recaps"][0]["summary"].startswith("I explored for about 10 minutes")
    log.append({"duration_s": 60})
    assert rf.has_enough_new()


def test_on_mode_saves_notes_as_experience_facts_and_force_saves_in_dry_mode(tmp_path):
    st, log, rf, calls = _reflector(tmp_path, [{"text": "I turned away from walls four times.", "importance": 2}], "on")
    assert rf.run(apply=True) == {"ok": True, "applied": True, "saved": ["I turned away from walls four times."]}
    f = st.list_facts()[0]
    assert f["source"] == "experience" and not f["core"] and f["importance"] == 2 and experience_notes(st) == ["I turned away from walls four times."]
    other = tmp_path / "x"
    other.mkdir()
    st2, log2, rf2, _ = _reflector(other, [{"text": "I rarely reach the foyer.", "importance": 1}], "dry")
    assert rf2.run(apply=True, force=True)["applied"] is True


def test_an_unusable_reply_changes_nothing_and_the_watcher_runs_it_when_idle(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    log = ExperienceLog(str(tmp_path / "e.jsonl"))
    log.append({"duration_s": 60})
    rf = ExperienceReflector(st, lambda s, u: ("sorry, no json", None), log, mode="on", dry_path=str(tmp_path / "d.jsonl"))
    assert rf.run()["ok"] is False and rf.has_enough_new()
    ran = []
    w = ConsolidationWatcher(types_ns(rf, ran), lambda: 5000.0, idle_s=1200.0)
    assert w.tick() == {"ran": True} and ran == [True]


def types_ns(rf, ran):
    import types
    return types.SimpleNamespace(has_enough_new=rf.has_enough_new, run=lambda apply=True: ran.append(apply) or {"ran": True})


def test_the_questions_are_local_commands_and_do_not_catch_vision_or_other_questions():
    for q in ("what did you do today", "G2 how was your exploration", "tell me about your exploration", "what have you been up to"):
        assert match_local_command(q) == "recap_query", q
    for q in ("what have you learned", "what did you learn today", "what have you noticed lately"):
        assert match_local_command(q) == "learned_query", q
    for q in ("what do you see", "what did you do with the ball yesterday afternoon", "tell me about the weather", "how was the weather", "how was your day", "tell me about your day"):   # a day is an ordinary conversation, not a recap
        assert match_local_command(q) is None, q


def test_only_one_memory_call_per_session_across_the_tidy_up_and_the_reflection_and_every_attempt_is_logged(tmp_path, monkeypatch):
    import types
    from pi_pipeline.memory.call_log import MemoryCallGate, read_calls, summary
    monkeypatch.setenv("G2_MEMORY_CALL_LOG", str(tmp_path / "calls.jsonl"))
    idle = {"age": 5000.0}
    gate = MemoryCallGate(lambda: idle["age"])
    made = []

    def fake(name, out):
        return types.SimpleNamespace(has_enough_new=lambda: True, run=lambda apply=True: made.append(name) or out)
    tidy = ConsolidationWatcher(fake("consolidation", {"ok": True, "applied": True, "result": {"merged": [1], "dropped": [], "reflected": [2, 3]}}), lambda: idle["age"], idle_s=1200.0, gate=gate)
    refl = ConsolidationWatcher(fake("reflection", {"ok": True, "applied": False, "would_save": ["I x"]}), lambda: idle["age"], idle_s=1200.0, gate=gate, kind="reflection")
    assert tidy.tick() is not None and made == ["consolidation"]
    assert refl.tick() is None and refl.tick() is None and made == ["consolidation"]               # the second pass waits: the session's call is spent
    assert tidy.tick() is None                                                                   # (and so does a repeat of the first, by its own interval)
    idle["age"] = 30.0                                                                           # someone talked to G2: a new session
    refl._idle_s = 0.0
    assert refl.tick() is not None and made == ["consolidation", "reflection"]
    rows = read_calls()
    assert [(r["kind"], r["outcome"]) for r in rows] == [("consolidation", "called"), ("reflection", "skipped"), ("reflection", "called")]          # one skip line, not one per poll
    assert rows[0]["counts"] == {"merged": 1, "dropped": 0, "reflected": 2} and "already made it" in rows[1]["why"]
    text = summary(7)
    assert "consolidation: 1 called, 0 failed, 0 skipped" in text and "reflection: 1 called, 0 failed, 1 skipped" in text


def test_a_failing_call_is_logged_as_failed_and_never_raises(tmp_path, monkeypatch):
    import types
    from pi_pipeline.memory.call_log import read_calls, summary
    monkeypatch.setenv("G2_MEMORY_CALL_LOG", str(tmp_path / "calls.jsonl"))

    def boom(apply=True):
        raise RuntimeError("api down")
    w = ConsolidationWatcher(types.SimpleNamespace(has_enough_new=lambda: True, run=boom), lambda: 9999.0, idle_s=1.0, kind="reflection")
    assert w.tick() is None
    assert [(r["kind"], r["outcome"]) for r in read_calls()] == [("reflection", "failed")] and "RuntimeError" in read_calls()[0]["why"]
    assert summary(7).startswith("memory-processing calls in the last 7 days:")
