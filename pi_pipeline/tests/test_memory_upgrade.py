import dataclasses
import sqlite3
import types
from datetime import datetime, timedelta, timezone

from pi_pipeline.memory.memory import Memory
from pi_pipeline.memory.store import Store, fact_score
from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.voice.conversation import Conversation


def old_db(path):
    """A database as it was before importance / core / source / observations existed."""
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE exchanges (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, user_text TEXT NOT NULL,
                                assistant_text TEXT NOT NULL DEFAULT '', actions TEXT NOT NULL DEFAULT '');
        CREATE TABLE facts (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, last_recalled TEXT, fact TEXT NOT NULL UNIQUE);
        INSERT INTO facts (ts, fact) VALUES ('2026-10-01T00:00:00+00:00', 'They like strong coffee.');
        INSERT INTO facts (ts, fact) VALUES ('2026-10-02T00:00:00+00:00', 'I look like a small white robot with wires on top.');
    """)
    db.commit(); db.close()


def test_an_old_database_is_migrated_in_place_and_the_self_description_becomes_core(tmp_path):
    p = str(tmp_path / "m.db"); old_db(p)
    st = Store(p)
    rows = {r["fact"]: r for r in st.list_facts()}
    assert rows["They like strong coffee."]["importance"] == 3 and rows["They like strong coffee."]["core"] == 0
    assert rows["They like strong coffee."]["source"] == "told"
    look = rows["I look like a small white robot with wires on top."]
    assert look["core"] == 1 and look["importance"] == 5
    assert st.observation_count() == 0 and st.get_meta("x", "d") == "d"                  # the new tables exist and work


def test_importance_beats_recency_until_the_recency_bonus_is_big_enough(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    st.add_fact("Their name is Sam.", importance=5)
    st.add_fact("They had toast.", importance=1)
    st.add_fact("They like jazz.", importance=3)
    assert [r["fact"] for r in st.list_ranked(3)] == ["Their name is Sam.", "They like jazz.", "They had toast."]
    now = datetime.now(timezone.utc)
    old, new = (now - timedelta(days=60)).isoformat(), now.isoformat()
    assert fact_score(3, new) > fact_score(3, old)                                        # same importance: newer wins
    assert fact_score(5, old) > fact_score(3, new) - 1.0                                  # an old important fact is not buried by a fresh ordinary one
    assert fact_score(1, new) < fact_score(5, old)


def test_core_facts_are_listed_separately_and_the_self_description_is_forced_core(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    st.add_fact("The dog is called Biscuit.", importance=5, core=True)
    st.add_fact("They like jazz.")
    st.add_fact("I look like a small white robot.", importance=1, core=False)           # forced to core, importance 5
    assert {r["fact"] for r in st.list_core()} == {"The dog is called Biscuit.", "I look like a small white robot."}
    assert [r["fact"] for r in st.list_ranked(10)] == ["They like jazz."]                # ranked list excludes core
    look = [r for r in st.list_core() if r["fact"].startswith("I look")][0]
    assert look["importance"] == 5


def test_recall_puts_core_facts_first_and_never_lets_them_rotate_out(cfg, tmp_path):
    c = dataclasses.replace(cfg, memory_max_facts=2, memory_db_path=str(tmp_path / "m.db"), memory_core_max=12)
    m = Memory(c)
    m.store.add_fact("The dog is called Biscuit.", importance=5, core=True)
    for i, t in enumerate(["They like jazz.", "They like tea.", "They like rain.", "They like hiking."]):
        m.store.add_fact(t, importance=2)
    ctx = m.recall("hello")
    assert ctx.index("About you and your people") < ctx.index("What you know")
    assert "The dog is called Biscuit." in ctx and ctx.count("- They like") == 2           # core is extra to the 2-fact cap


# ---- observations

def test_observations_are_searchable_date_only_and_scrubbed(tmp_path):
    st = Store(str(tmp_path / "m.db"))
    st.add_observation("I saw a bright lamp on the desk at 6:30 pm.", "person_a")
    st.add_observation("I saw a cat asleep on a blue chair.", "cat")
    got = st.search_observations("where was the lamp", 3)
    assert len(got) == 1 and "[when]" in got[0]["caption"] and "6:30" not in got[0]["caption"]
    assert len(got[0]["ts"]) == 10                                                      # a date, never a clock time
    assert [r["caption"] for r in st.recent_observations(1)] == ["I saw a cat asleep on a blue chair."]
    assert st.add_observation("   ") == 0


def test_old_observations_are_pruned_and_forget_that_removes_a_sessions_sightings(cfg, tmp_path):
    c = dataclasses.replace(cfg, memory_db_path=str(tmp_path / "m.db"), observation_days=30.0)
    m = Memory(c)
    m.store.add_observation("An old sighting.")
    m.store._db.execute("UPDATE observations SET ts = ?", ((datetime.now(timezone.utc).date() - timedelta(days=40)).isoformat(),))
    m.store._db.commit()
    assert m.store.prune_observations(30.0) == 1 and m.store.observation_count() == 0
    m.mark_session_start()
    m.record_observation("I saw a desk.", "")
    m.store.add_fact("They like jazz.")
    m.forget_session()
    assert m.store.observation_count() == 0 and m.store.list_facts() == []


def test_recall_brings_in_sightings_only_when_asked_about_the_past(cfg, tmp_path):
    c = dataclasses.replace(cfg, memory_db_path=str(tmp_path / "m.db"))
    m = Memory(c)
    m.record_observation("I saw a very bright lamp and a blue sign.", "")
    assert "Things you saw earlier" not in m.recall("tell me a joke")
    ctx = m.recall("what did you see earlier")
    assert "Things you saw earlier" in ctx and "(today)" in ctx and "bright lamp" in ctx
    assert "bright lamp" in m.recall("did you notice a lamp before")


# ---- the remember tool carries importance and core all the way to the store

def test_remember_tool_schema_has_importance_and_core(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("text", text="ok")))
    Conversation(cfg).send("hi")
    tool = [t for t in fake_anthropic.calls[-1]["tools"] if t["name"] == "remember"][0]
    props = tool["input_schema"]["properties"]
    assert props["importance"]["maximum"] == 5 and props["core"]["type"] == "boolean"


def test_a_remember_call_reaches_memory_with_its_importance_and_core_flag(cfg, fake_anthropic, tmp_path):
    fake_anthropic.set_reply(Resp(
        Block("text", text="Nice to meet you, Sam!"),
        Block("tool_use", name="remember", id="r1", input={"fact": "Their name is Sam.", "importance": 5, "core": True}),
        Block("tool_use", name="remember", id="r2", input={"fact": "They like jazz.", "importance": "high"})))      # a bad value falls back
    turn = Conversation(cfg).send("I'm Sam and I like jazz")
    assert turn.fact_details == [("Their name is Sam.", 5, True), ("They like jazz.", 3, False)]
    m = Memory(dataclasses.replace(cfg, memory_db_path=str(tmp_path / "m.db")))
    m.record("I'm Sam", turn)
    rows = {r["fact"]: r for r in m.store.list_facts()}
    assert rows["Their name is Sam."]["core"] == 1 and rows["Their name is Sam."]["importance"] == 5
    assert rows["They like jazz."]["core"] == 0 and rows["They like jazz."]["importance"] == 3


def test_memory_record_still_accepts_a_plain_turn_with_only_facts(cfg, tmp_path):
    m = Memory(dataclasses.replace(cfg, memory_db_path=str(tmp_path / "m.db")))
    m.record("hi", types.SimpleNamespace(speech="hello", actions=[], facts=["They like tea."]))
    assert [r["fact"] for r in m.store.list_facts()] == ["They like tea."]
