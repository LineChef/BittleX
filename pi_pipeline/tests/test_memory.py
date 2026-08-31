import types

from pi_pipeline.memory.memory import Memory
from pi_pipeline.memory.store import Store


def _turn(speech, actions=(), facts=()):
    return types.SimpleNamespace(speech=speech, actions=list(actions), facts=list(facts))


def test_store_dedupes_facts(cfg):
    st = Store(cfg.memory_db_path)
    assert st.add_fact("Their name is Mark.") is True
    assert st.add_fact("Their name is Mark.") is False
    assert st.add_fact("  ") is False


def test_recall_injects_facts_and_fts_match(cfg):
    mem = Memory(cfg)
    mem.record("my name is Mark", _turn("Hi Mark.", facts=["Their name is Mark."]))
    mem.record("i have a cat named Biscuit", _turn("Cute!", facts=["They have a cat named Biscuit."]))
    mem.record("we went hiking", _turn("Fun."))
    mem.record("it rained later", _turn("Aw."))  # push the cat turn out of the recent window

    ctx = mem.recall("tell me about my cat Biscuit")
    assert "Their name is Mark." in ctx
    assert "cat named Biscuit" in ctx
    assert "earlier they said" in ctx  # FTS pulled the older exchange


def test_recall_no_fts_hit_still_injects_facts(cfg):
    mem = Memory(cfg)
    mem.record("my name is Mark", _turn("Hi.", facts=["Their name is Mark."]))
    ctx = mem.recall("completely unrelated zzz")
    assert "Their name is Mark." in ctx
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
