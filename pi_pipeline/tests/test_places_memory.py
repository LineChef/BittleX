"""Places memory, the goal self-knowledge note, log retention, and what the chat prompt no longer carries (user, 2026-11-06)."""
import json
import os
import time

import pytest

from pi_pipeline.goals import summary
from pi_pipeline.memory import places
from pi_pipeline.util import log_retention
from pi_pipeline.voice.commands import parse_place


@pytest.fixture(autouse=True)
def _paths(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_PLACES", str(tmp_path / "places.json"))
    monkeypatch.setenv("G2_CURRENT_PLACE", str(tmp_path / "current_place"))


def test_a_room_told_to_him_is_current_for_a_few_hours_only():
    assert places.current() is None
    assert places.set_current("The Kitchen") == "kitchen" and places.current() == "kitchen"
    assert places.current(now=time.time() + places.CURRENT_TTL_S + 10) is None            # a moved G2 is not filed under an old room
    assert places.set_current("one two three four") is None and places.set_current("") is None
    places.clear_current()
    assert places.current() is None


def test_what_a_session_saw_and_where_it_went_wrong_is_kept_as_counts():
    places.record_session("kitchen", {"stops": 5, "seen": {"cat": 3, "dishwasher": 2}, "events": {"fall": 1, "wall.hit": 4}})
    places.record_session("kitchen", {"stops": 2, "seen": {"cat": 1}, "events": {"wall.hit": 2}})
    places.record_goal("kitchen", "fell", floor="tile")
    e = places.load()["kitchen"]
    assert e["sessions"] == 2 and e["stops"] == 7 and e["items"] == {"cat": 4, "dishwasher": 2} and e["hazards"] == {"fall": 2, "bump": 6} and e["floor"] == "tile" and e["goal_sessions"] == 1
    text = places.summary("kitchen")
    assert "tile floor" in text and "cat" in text and "fallen here 2 times" in text
    assert "20" not in json.dumps(places.load()).replace("2026", "")


def test_places_reach_the_prompt_only_when_a_room_is_mentioned_or_asked_about():
    places.record_session("kitchen", {"stops": 3, "seen": {"cat": 2}, "events": {}})
    assert "cat" in places.recall_block("what is in the kitchen?")
    assert places.recall_block("tell me a joke") == ""
    assert "kitchen" in places.recall_block("which room have you been in most?")


def test_you_are_in_the_kitchen_names_a_room_but_not_an_object_or_a_phrase():
    assert parse_place("you're in the kitchen") == "kitchen"
    assert parse_place("we are in the living room") == "living room"
    assert parse_place("this room is the hallway") == "hallway"
    assert parse_place("you're in the way") is None
    assert parse_place("this is the dishwasher") is None and parse_place("this is the kitchen") is None      # the second is how an object is named
    places.set_current("sun nook")
    assert parse_place("we're in the sun nook") == "sun nook"                                  # a room already in his places memory counts


def test_the_goal_note_is_one_fact_that_replaces_the_last():
    state = {"values": {"walk_aim_in": {"3.5": {"v": 3.5, "n": 23, "hits": 17}, "4.0": {"v": 4.0, "n": 8, "hits": 2}}, "search_order": {"turn": {"v": "turn", "n": 4, "hits": 3}}}, "focus": "search_order"}
    note = summary.build_note("Punt the ball", {"floor": "hardwood"}, state)
    assert note.startswith("Punt the ball (hardwood): ") and "good so far" in note
    assert "walk aim in 3.5 (17 of 23 good)" in note and "Still testing: search order" in note

    class Store:
        def __init__(self): self.facts, self.n = [], 0
        def list_facts(self): return list(self.facts)
        def delete_fact(self, i): self.facts = [f for f in self.facts if f["id"] != i]
        def add_fact(self, text, importance, core, source): self.n += 1; self.facts.append({"id": self.n, "fact": text, "source": source}); return True
    st = Store()
    assert summary.save_note("Punt the ball", {"floor": "hardwood"}, state, st) and summary.save_note("Punt the ball", {"floor": "hardwood"}, state, st)
    assert len(st.facts) == 1 and st.facts[0]["source"] == "goal_summary"                 # the second replaced the first
    assert summary.build_note("Punt the ball", {}, {}) == ""


def test_old_debug_log_lines_go_and_recent_or_unreadable_ones_stay(tmp_path):
    now = time.mktime(time.strptime("2026-11-06 12:00:00", "%Y-%m-%d %H:%M:%S"))
    f = tmp_path / "log.jsonl"
    f.write_text("\n".join([json.dumps({"t": "2026-10-20 10:00:00"}), json.dumps({"t": "2026-11-05T10:00:00"}), json.dumps({"t": now - 9 * 86400}), json.dumps({"t": now - 3600}), "not json", json.dumps({"x": 1})]) + "\n")
    assert log_retention.trim_file(str(f), 7, now) == 2
    assert len(f.read_text().splitlines()) == 4
    assert log_retention.trim_file(str(tmp_path / "missing.jsonl"), 7, now) == 0


def test_goal_notes_stay_out_of_ordinary_chat(cfg, tmp_path):
    import dataclasses
    from pi_pipeline.memory.memory import Memory
    m = Memory(dataclasses.replace(cfg, memory_db_path=str(tmp_path / "m.db"), memory_max_facts=30))
    m.store.add_fact("Punt the ball: Searching by turn works best so far: 5 of 6 good.", importance=2, source="goal_lesson")
    m.store.add_fact("The piano stands against the lounge wall.", importance=3)
    assert "Searching by turn" not in m.recall("hello there")
    assert "piano" in m.recall("hello there")
    assert "Searching by turn" in m.recall("how is the ball practice going?")


def test_saying_you_are_in_a_room_files_it_and_gets_an_answer_without_claude():
    from pi_pipeline.tests.test_voice_loop import _loop, _run
    lp, w, stt, conv, tts = _loop(["you're in the kitchen"])
    _run(lp, 1)
    assert places.current() == "kitchen" and conv.sent == [] and any("kitchen" in x.lower() for x in tts.said)


def test_room_tags_from_the_mac_are_imported_as_counts_and_importing_twice_counts_nothing_twice():
    stats = {"Kitchen": {"views": 35, "items": {"dog bowl": 2, "cat": 1}}, "foyer": {"views": 4, "items": {}}}
    assert places.import_tagged(stats) == 2 and places.import_tagged(stats) == 2
    d = places.load()
    assert d["kitchen"]["tagged"] == {"views": 35, "items": {"dog bowl": 2, "cat": 1}} and d["foyer"]["tagged"]["views"] == 4
    places.record_session("kitchen", {"stops": 1, "seen": {"cat": 2}, "events": {}})
    text = places.summary("kitchen")
    assert "I know it from 35 pictures" in text and "cat" in text
    assert "kitchen" in places.recall_block("what do you know about the kitchen?")


def test_the_mac_tool_counts_a_tagged_picture_once_and_names_what_is_in_it(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("g2_places_sync", Path(__file__).resolve().parents[2] / "tools" / "g2_places_sync.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    (tmp_path / "named" / "dog-bowl").mkdir(parents=True)
    (tmp_path / "survey" / "20261011").mkdir(parents=True)
    (tmp_path / "named" / "dog-bowl" / "a.jpg").write_bytes(b"x")
    (tmp_path / "named" / "dog-bowl" / "a.json").write_text(json.dumps({"name": "dog-bowl", "detections": []}))
    (tmp_path / "survey" / "20261011" / "b.jpg").write_bytes(b"x")
    (tmp_path / "survey" / "20261011" / "b.json").write_text(json.dumps({"detections": [{"label": "cat"}, {"label": "cat"}]}))
    (tmp_path / "rooms.json").write_text(json.dumps({"a.jpg": "Kitchen", "b.jpg": "kitchen", "gone.jpg": "kitchen", "c.jpg": ""}))
    assert m.tagged_stats(tmp_path) == {"kitchen": {"views": 2, "items": {"dog bowl": 1, "cat": 1}}}
