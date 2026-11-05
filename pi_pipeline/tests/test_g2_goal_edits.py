"""tools/g2_goal_edits.py (the Goals tab's edit queue) and the `g2goal lesson` command it drives. No ssh: a fake runner stands in for the Pi."""
import dataclasses
import importlib.util
import json
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
SPEC = importlib.util.spec_from_file_location("g2_goal_edits", TOOLS / "g2_goal_edits.py")
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


class FakePi:
    def __init__(self, running=False, fail_on=None, offline=False):
        self.calls, self.running, self.fail_on, self.offline = [], running, fail_on, offline

    def __call__(self, host, remote, timeout=40):
        self.calls.append(remote)
        if self.offline:
            return 255, ""
        if "pgrep" in remote:
            return 0, "running" if self.running else "idle"
        if self.fail_on and self.fail_on in remote:
            return 1, "no setting 'zzz'"
        return 0, "ok"


def test_argv_for_builds_the_g2goal_command():
    assert E.argv_for({"op": "pin", "goal": "ball_punt", "knob": "punt_max_in", "value": 4}) == ["pin", "ball_punt", "punt_max_in", "4"]
    assert E.argv_for({"op": "pin", "goal": "g", "knob": "k", "value": True, "scope": "attachment=arm|floor=tile"}) == ["pin", "g", "k", "true", "--scope", "attachment=arm|floor=tile"]
    assert E.argv_for({"op": "limit", "goal": "g", "knob": "k", "lo": 2, "hi": 6}) == ["limit", "g", "k", "2.0", "6.0"]
    assert E.argv_for({"op": "unpin", "goal": "g", "knob": "k", "scope": "all"}) == ["unpin", "g", "k"]
    assert E.argv_for({"op": "verdict", "goal": "g", "number": 22, "verdict": "wrong", "note": "ball moved"}) == ["verdict", "g", "22", "wrong", "--note", "ball moved"]
    assert E.argv_for({"op": "reset", "goal": "g"}) == ["reset", "g", "--yes"]
    assert E.argv_for({"op": "priority", "order": ["walls", "ball_punt"]}) == ["priority", "walls", "ball_punt"]
    assert E.argv_for({"op": "lesson_edit", "id": 5, "text": "Punt: x"}) == ["lesson", "edit", "5", "Punt: x"]
    s = E.argv_for({"op": "set", "goal": "g", "attempts": 8, "min_pack_pct": 40, "controls": {"punt_max_in": "ask"}, "start_words": ["ball goal"]})
    assert s == ["set", "g", "--attempts", "8", "--min-pack", "40", "--control", "punt_max_in=ask", "--start-words", "ball goal"]


BAD = [
    {"op": "pin", "goal": "g; rm -rf /", "knob": "k", "value": 1},
    {"op": "pin", "goal": "g", "knob": "k"},
    {"op": "pin", "goal": "g", "knob": "k", "value": 1, "scope": "a b"},
    {"op": "limit", "goal": "g", "knob": "k", "lo": "x", "hi": 3},
    {"op": "verdict", "goal": "g", "number": 2, "verdict": "maybe"},
    {"op": "set", "goal": "g"},
    {"op": "set", "goal": "g", "attempts": 0},
    {"op": "set", "goal": "g", "controls": {"k": "always"}},
    {"op": "lesson_add", "text": "  "},
    {"op": "lesson_delete", "id": "abc"},
    {"op": "format_disk"},
]


@pytest.mark.parametrize("op", BAD)
def test_bad_edits_are_refused_before_they_are_queued(op, tmp_path):
    with pytest.raises(ValueError):
        E.add(op, str(tmp_path))
    assert E.pending(str(tmp_path)) == []


def test_a_newer_edit_replaces_the_older_one_and_sets_merge(tmp_path):
    d = str(tmp_path)
    E.add({"op": "pin", "goal": "g", "knob": "k", "value": 1}, d)
    E.add({"op": "unpin", "goal": "g", "knob": "k"}, d)
    assert [r["op"] for r in E.pending(d)] == ["unpin"]
    E.add({"op": "set", "goal": "g", "attempts": 5, "controls": {"a": "ask"}}, d)
    E.add({"op": "set", "goal": "g", "minutes": 10, "controls": {"b": "fixed"}}, d)
    sets = [r for r in E.pending(d) if r["op"] == "set"]
    assert len(sets) == 1 and sets[0]["attempts"] == 5 and sets[0]["minutes"] == 10 and sets[0]["controls"] == {"a": "ask", "b": "fixed"}
    assert E.cancel(sets[0]["id"], d) and not E.cancel("nope", d)


def test_apply_runs_each_edit_on_the_pi_and_logs_it(tmp_path):
    d = str(tmp_path)
    E.add({"op": "pin", "goal": "ball_punt", "knob": "punt_max_in", "value": 4}, d)
    E.add({"op": "lesson_add", "text": "Punt the ball: it's a note with $HOME"}, d)
    pi = FakePi()
    res = E.apply(d, "u@h", pi)
    assert res["applied"] == 2 and res["left"] == 0 and E.pending(d) == []
    assert "pgrep" in pi.calls[0] and pi.calls[1].endswith("pin ball_punt punt_max_in 4")
    assert "'Punt the ball: it'\"'\"'s a note with $HOME'" in pi.calls[2]                           # one shell word, nothing expanded
    assert len(E.history(d)) == 2 and E.history(d)[0]["ok"]


def test_apply_waits_for_a_running_session_and_for_the_pi(tmp_path):
    d = str(tmp_path)
    E.add({"op": "unpin", "goal": "g", "knob": "k"}, d)
    assert "session is running" in E.apply(d, "u@h", FakePi(running=True))["message"]
    assert "offline" in E.apply(d, "u@h", FakePi(offline=True))["message"]
    assert len(E.pending(d)) == 1                                                                   # nothing was lost


def test_a_failed_edit_stays_queued_with_the_reason_and_the_others_still_run(tmp_path):
    d = str(tmp_path)
    E.add({"op": "unpin", "goal": "g", "knob": "zzz"}, d)
    E.add({"op": "unpin", "goal": "g", "knob": "good"}, d)
    res = E.apply(d, "u@h", FakePi(fail_on="zzz"))
    assert res["applied"] == 1 and res["failed"] == 1
    left = E.pending(d)
    assert len(left) == 1 and left[0]["knob"] == "zzz" and "no setting" in left[0]["error"]
    assert "unpin zzz" in E.with_text(left)[0]["text"]


def test_lesson_command_adds_edits_and_trashes_only_goal_lessons(tmp_path, monkeypatch, capsys):
    from pi_pipeline import config
    from pi_pipeline.goals import __main__ as cli
    from pi_pipeline.memory.store import Store
    db = str(tmp_path / "m.db")
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, memory_db_path=db))
    cli.main(["lesson", "add", "Punt the ball:", "back up before searching"])
    store = Store(db)
    row = next(f for f in store.list_facts() if f["source"] == "goal_lesson")
    cli.main(["lesson", "edit", str(row["id"]), "Punt the ball: back up, then search"])
    assert any(f["fact"] == "Punt the ball: back up, then search" for f in Store(db).list_facts())
    store.add_fact("The dog is named Rex.", source="told")
    other = next(f for f in store.list_facts() if f["source"] == "told")
    with pytest.raises(SystemExit):
        cli.main(["lesson", "delete", str(other["id"])])                                              # not a goal lesson: refused
    cli.main(["lesson", "delete", str(row["id"])])
    assert all(f["source"] != "goal_lesson" for f in Store(db).list_facts())
    assert "Trash" in capsys.readouterr().out


def test_goals_view_carries_definitions_overrides_and_the_queue(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(TOOLS))
    import g2_goals_view as v
    ov = {"ball_punt": {"all": {"pins": {"punt_max_in": 4.0}, "limits": {"nudge_max_in": [3, 6]}, "banned": {}}}}
    (tmp_path / "goal_overrides.json").write_text(json.dumps(ov))
    E.add({"op": "unpin", "goal": "ball_punt", "knob": "punt_max_in"}, str(tmp_path))
    d = v.build(str(tmp_path))
    g = next(x for x in d["goals"] if x["id"] == "ball_punt")
    assert g["definition"]["attempts"] == 10 and any(k["name"] == "punt_max_in" for k in g["definition"]["knobs"])
    assert {r["kind"] for r in g["override_rows"]} == {"pin", "limit"}
    assert d["pending"][0]["text"] == "ball_punt: unpin punt_max_in" and d["priority"][0] == "walls"


def test_the_review_page_queues_cancels_and_reports_edits(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_GOALS_DIR", str(tmp_path))
    monkeypatch.delenv("G2_PI", raising=False)
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location("g2_review", TOOLS / "g2_review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    assert "renderGoals" in R.PAGE and "/*GOALS_UI*/" not in R.PAGE                              # the tab's drawing code is in the page
    app = R.App.__new__(R.App)
    r = app.goal_edit({"op": "pin", "goal": "ball_punt", "knob": "punt_max_in", "value": 4})
    assert r["ok"] and r["pending"][0]["text"] == "ball_punt: pin punt_max_in = 4"
    with pytest.raises(ValueError):
        app.goal_edit({"op": "pin", "goal": "ball_punt", "knob": "punt_max_in"})
    res = app.goal_edits_apply()
    assert res["applied"] == 0 and "G2_PI" in res["message"] and len(res["pending"]) == 1       # no Pi named: kept
    assert app.goal_edit_cancel(r["id"])["pending"] == []


def _mirror(tmp_path, monkeypatch):
    """A MirrorRemote over a temp folder holding a copy of a real-shaped snapshot (and a 0-byte one that must be ignored)."""
    from pi_pipeline.memory.store import Store
    (tmp_path / "memory-backups").mkdir()
    st = Store(str(tmp_path / "memory-backups" / "g2_memory-20261102-192616.db"))
    for t in ("The dog is named Rex.", "The kitchen is next to the dining room.", "Sam likes tea in the morning."):
        st.add_fact(t, source="told")
    st._db.commit()
    st._db.close()
    (tmp_path / "memory-backups" / "g2_memory-20261104-101752.db").write_bytes(b"")
    monkeypatch.setenv("G2_REVIEW_DIR", str(tmp_path))
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location("g2_review_m", TOOLS / "g2_review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    return R, R.MirrorRemote("u@h", root=str(tmp_path), pictures_root=str(tmp_path / "pics"))


def test_the_tabs_read_the_mac_copy_and_queue_edits_for_the_pi(tmp_path, monkeypatch):
    R, m = _mirror(tmp_path, monkeypatch)
    facts = m.memory("list", "facts", "--limit", "100", "--query", "")
    assert facts and m.copy_info()["has_memory"]                                                  # the empty newer file is skipped
    old_id = facts[0]["id"]
    r = m.memory("delete", "facts", str(old_id))
    assert all(f["id"] != old_id for f in m.memory("list", "facts", "--limit", "100", "--query", ""))
    q = m.q.pending(str(tmp_path))
    assert [e["args"] for e in q] == [["delete", "facts", str(old_id)]]
    m.memory("restore", str(r["trash_id"]))                                                       # undo before the Pi was told: the waiting delete is cancelled
    assert m.q.pending(str(tmp_path)) == []
    assert any(f["id"] == old_id for f in m.memory("list", "facts", "--limit", "100", "--query", ""))


def test_a_fact_added_here_is_one_waiting_edit_that_later_changes_fold_into(tmp_path, monkeypatch):
    R, m = _mirror(tmp_path, monkeypatch)
    new = m.memory("add-fact", "The garage door sticks.", "--importance", "3")
    m.memory("edit-fact", str(new["id"]), "--fact", "The garage door sticks in winter.", "--importance", "4")
    q = m.q.pending(str(tmp_path))
    assert len(q) == 1 and q[0]["args"] == ["add-fact", "The garage door sticks in winter.", "--importance", "4"]    # the Pi never sees a change to a row it does not have
    m.memory("delete", "facts", str(new["id"]))
    assert m.q.pending(str(tmp_path)) == []                                                      # deleted before it was sent: nothing to send
    app = R.App(m)
    st = app.review_state()
    assert st["mirror"] and st["pending"] == [] and st["copy"]["memory_from"]


def test_cancelling_a_waiting_memory_edit_restores_the_copy_and_a_new_snapshot_keeps_the_waiting_edits(tmp_path, monkeypatch):
    import shutil
    R, m = _mirror(tmp_path, monkeypatch)
    app = R.App(m)
    first = m.memory("list", "facts", "--limit", "100", "--query", "")[0]["id"]
    m.memory("delete", "facts", str(first))
    eid = m.q.pending(str(tmp_path))[0]["id"]
    app.review_cancel(eid)
    assert any(f["id"] == first for f in m.memory("list", "facts", "--limit", "100", "--query", ""))
    m.memory("delete", "facts", str(first))
    shutil.copyfile(tmp_path / "memory-backups" / "g2_memory-20261102-192616.db", tmp_path / "memory-backups" / "g2_memory-20261103-090000.db")     # a newer snapshot arrives
    assert all(f["id"] != first for f in m.memory("list", "facts", "--limit", "100", "--query", ""))        # the waiting delete is laid on top of it
    assert len(m.q.pending(str(tmp_path))) == 1


def test_picture_edits_run_on_the_copy_and_queue(tmp_path, monkeypatch):
    R, m = _mirror(tmp_path, monkeypatch)
    pics = tmp_path / "pics" / "survey" / "20261101"
    pics.mkdir(parents=True)
    (pics / "a.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    items = m.pictures("list")
    rel = items[0]["path"]
    m.pictures("trash", rel)
    assert m.pictures("list") == [] and len(m.q.pending(str(tmp_path))) == 1
    m.pictures("restore", rel)                                                                   # undo while the trash is still waiting: cancelled
    assert len(m.pictures("list")) == 1 and m.q.pending(str(tmp_path)) == []
