import types

import pytest

from pi_pipeline.memory.memory import Memory
from pi_pipeline.memory.store import Store, has_temporal_detail, scrub_text


def _turn(speech, actions=(), facts=()):
    return types.SimpleNamespace(speech=speech, actions=list(actions), facts=list(facts))


def test_store_dedupes_facts(cfg):
    st = Store(cfg.memory_db_path)
    assert st.add_fact("Their name is Sam.") is True
    assert st.add_fact("Their name is Sam.") is False
    assert st.add_fact("  ") is False


@pytest.mark.parametrize("fact", [
    "They get home around 6pm.",
    "They go to the gym every Monday.",
    "They were away last week.",
    "Their trip is 2026-09-10.",
    "They said this tonight.",
    "They walk the dog daily.",
    "Their birthday is June 3.",
    "See you on Friday.",
    "They left 2 hours ago.",
])
def test_facts_with_dates_times_schedules_are_rejected(cfg, fact):
    st = Store(cfg.memory_db_path)
    assert has_temporal_detail(fact)
    assert st.add_fact(fact) is False
    assert st.list_facts() == []


@pytest.mark.parametrize("fact", [
    "Their name is Sam.",
    "They have a cat named Biscuit.",
    "They work in software.",
    "They prefer tea to coffee.",
    "Their friend June visits often.",
    "They may want to learn guitar.",
])
def test_stable_facts_still_stored(cfg, fact):
    st = Store(cfg.memory_db_path)
    assert not has_temporal_detail(fact)
    assert st.add_fact(fact) is True


def test_exchange_ts_is_date_only(cfg):
    st = Store(cfg.memory_db_path)
    st.log_exchange("hi", "hello", [])
    ts = st.recent_exchanges(1)[0]["ts"]
    assert len(ts) == 10 and ts.count("-") == 2   # YYYY-MM-DD, no clock time


def test_scrub_text_redacts_times_and_named_terms():
    s = scrub_text("Alex gets home at 6pm on Friday", extra_terms=["Alex"])
    assert "Alex" not in s and "6pm" not in s and "Friday" not in s
    assert "[name]" in s and "[when]" in s


def test_recall_injects_facts_and_fts_match(cfg):
    mem = Memory(cfg)
    mem.record("my name is Sam", _turn("Hi Sam.", facts=["Their name is Sam."]))
    mem.record("i have a cat named Biscuit", _turn("Cute!", facts=["They have a cat named Biscuit."]))
    mem.record("we went hiking", _turn("Fun."))
    mem.record("it rained later", _turn("Aw."))  # push the cat turn out of the recent window

    ctx = mem.recall("tell me about my cat Biscuit")
    assert "Their name is Sam." in ctx
    assert "cat named Biscuit" in ctx
    assert "earlier they said" in ctx  # FTS pulled the older exchange


def test_recall_no_fts_hit_still_injects_facts(cfg):
    mem = Memory(cfg)
    mem.record("my name is Sam", _turn("Hi.", facts=["Their name is Sam."]))
    ctx = mem.recall("completely unrelated zzz")
    assert "Their name is Sam." in ctx
    assert "Relevant past moments" not in ctx


def test_fact_cap_and_decay_ordering(cfg):
    st = Store(cfg.memory_db_path)  # cfg.memory_max_facts == 5
    for i in range(7):
        st.add_fact(f"fact {i}")
    top = [r["fact"] for r in st.list_facts(limit=cfg.memory_max_facts)]
    assert len(top) == 5
    # touching an old fact brings it back into the injected set
    old_id = st.list_facts()[-1]["id"]
    st.touch_facts([old_id])
    assert any(r["id"] == old_id for r in st.list_facts(limit=cfg.memory_max_facts))


def test_wipe(cfg):
    mem = Memory(cfg)
    mem.record("hi", _turn("hey", facts=["A fact."]))
    mem.store.wipe()
    assert mem.store.exchange_count() == 0
    assert mem.store.list_facts() == []
