import json
import types

from pi_pipeline.memory.consolidate import ConsolidationWatcher, Consolidator, parse_plan
from pi_pipeline.memory.store import Store
from pi_pipeline.voice.usage import UsageTracker


def make_store(tmp_path, n_exchanges=8):
    st = Store(str(tmp_path / "m.db"))
    for i in range(n_exchanges):
        st.log_exchange(f"question {i}", f"answer {i}", [])
    return st


def llm_returning(plan, usage=None):
    calls = []

    def llm(system, user):
        calls.append(json.loads(user))
        return ("```json\n" + json.dumps(plan) + "\n```"), usage
    llm.calls = calls
    return llm


def facts_by_text(st):
    return {r["fact"]: r for r in st.list_facts()}


def test_parse_plan_handles_code_fences_and_garbage():
    assert parse_plan('Here you go:\n```json\n{"merges": []}\n```') == {"merges": []}
    assert parse_plan("no json here") is None and parse_plan("{broken") is None and parse_plan("[1, 2]") is None


def test_merges_drops_and_reflections_are_applied_and_audited(tmp_path):
    st = make_store(tmp_path)
    st.add_fact("They like jazz music a lot.", importance=3)
    st.add_fact("They enjoy listening to jazz.", importance=3)
    st.add_fact("They had toast.", importance=1)
    st.add_fact("The dog is called Biscuit.", importance=5, core=True)
    ids = {r["fact"]: r["id"] for r in st.list_facts()}
    plan = {"merges": [{"keep_id": ids["They like jazz music a lot."], "drop_ids": [ids["They enjoy listening to jazz."]],
                        "text": "They love jazz.", "importance": 4}],
            "drop_ids": [ids["They had toast."], ids["The dog is called Biscuit."]],            # the core fact must survive
            "reflections": [{"text": "they seem to enjoy music in the evening", "importance": 5}]}   # temporal: rejected
    audit = tmp_path / "audit.jsonl"
    usage = UsageTracker(tmp_path / "u.json")
    con = Consolidator(st, llm_returning(plan, types.SimpleNamespace(input_tokens=500, output_tokens=60)), usage=usage,
                       audit_path=audit, min_new_exchanges=3)
    out = con.run(apply=True)
    assert out["ok"] and out["applied"]
    facts = facts_by_text(st)
    assert "They love jazz." in facts and facts["They love jazz."]["importance"] == 4
    assert "They enjoy listening to jazz." not in facts and "They had toast." not in facts
    assert "The dog is called Biscuit." in facts                                                 # core: never dropped
    assert not any(f["source"] == "reflection" for f in facts.values())                           # "in the evening" is a routine: rejected
    line = json.loads(audit.read_text().splitlines()[-1])
    assert line["merged"][0]["dropped"] == ["They enjoy listening to jazz."] and line["dropped"] == ["They had toast."]
    (day, d), = usage.days()
    assert d["consolidations"] == 1 and d["in_tokens"] == 500 and d["turns"] == 0


def test_reflections_are_marked_inferred_capped_at_three_and_free_of_schedules(tmp_path):
    st = make_store(tmp_path)
    plan = {"reflections": [{"text": "It seems they enjoy quiet jazz", "importance": 3},
                            {"text": "they like the dog", "importance": 9},                       # gets "It seems", importance clamped to 3
                            {"text": "It seems they walk the dog every morning", "importance": 2},   # schedule: rejected
                            {"text": "It seems they like tea", "importance": 2},
                            {"text": "It seems they like rain", "importance": 2}]}               # a 5th: beyond the cap of 3
    Consolidator(st, llm_returning(plan), min_new_exchanges=1).run(apply=True)
    refl = [r for r in st.list_facts() if r["source"] == "reflection"]
    texts = sorted(r["fact"] for r in refl)
    assert len(refl) == 2 and all(t.startswith("It seems") for t in texts)                         # 3 allowed, one was a schedule
    assert max(r["importance"] for r in refl) <= 3 and not any(r["core"] for r in refl)


def test_bad_ids_and_overlong_or_temporal_merges_are_ignored(tmp_path):
    st = make_store(tmp_path)
    st.add_fact("They like tea.")
    kid = st.list_facts()[0]["id"]
    plan = {"merges": [{"keep_id": 999, "drop_ids": [kid], "text": "x"},
                       {"keep_id": kid, "drop_ids": [888], "text": "They like tea."},
                       {"keep_id": kid, "drop_ids": [kid], "text": "bad: dropping itself"}],
            "drop_ids": ["abc", 777]}
    out = Consolidator(st, llm_returning(plan), min_new_exchanges=1).run(apply=True)
    assert out["result"] == {"merged": [], "dropped": [], "reflected": []} and len(st.list_facts()) == 1


def test_a_dry_run_changes_nothing_and_a_bad_reply_changes_nothing(tmp_path):
    st = make_store(tmp_path)
    st.add_fact("They had toast.", importance=1)
    tid = st.list_facts()[0]["id"]
    con = Consolidator(st, llm_returning({"drop_ids": [tid]}), min_new_exchanges=1)
    out = con.run(apply=False)
    assert out["ok"] and not out["applied"] and out["plan"]["drops"] == [tid] and len(st.list_facts()) == 1
    assert st.get_meta("consolidated_exchange_id", "0") == "0"
    bad = Consolidator(st, lambda s, u: ("I cannot do that", None), min_new_exchanges=1)
    assert bad.run()["ok"] is False and len(st.list_facts()) == 1


def test_the_model_sees_facts_with_ids_and_only_what_is_new_and_the_mark_advances(tmp_path):
    st = make_store(tmp_path, n_exchanges=5)
    st.add_fact("They like tea.")
    llm = llm_returning({})
    con = Consolidator(st, llm, min_new_exchanges=1)
    con.run(apply=True)
    assert len(llm.calls[0]["new_exchanges"]) == 5 and llm.calls[0]["facts"][0]["fact"] == "They like tea."
    for i in range(2):
        st.log_exchange(f"later {i}", "ok", [])
    con.run(apply=True)
    assert [e["user"] for e in llm.calls[1]["new_exchanges"]] == ["later 0", "later 1"]          # only what came after the last pass


# ---- when it runs

def watcher(st, plan=None, **kw):
    llm = llm_returning(plan or {})
    con = Consolidator(st, llm, min_new_exchanges=3)
    t = [0.0]
    idle = kw.pop("idle", [100.0])
    w = ConsolidationWatcher(con, lambda: idle[0], idle_s=1200, min_interval_s=21600, clock=lambda: t[0], **kw)
    return w, llm, t, idle


def test_it_waits_for_idle_enough_new_material_and_the_interval(tmp_path):
    st = make_store(tmp_path, n_exchanges=8)
    w, llm, t, idle = watcher(st)
    assert w.tick() is None and not llm.calls                                    # only 100 s idle
    idle[0] = 2000.0
    assert w.tick()["ok"] and len(llm.calls) == 1                                # idle for 33 minutes: runs
    for i in range(5):
        st.log_exchange(f"more {i}", "ok", [])
    t[0] = 3600.0
    assert w.tick() is None                                                      # within the 6 h interval
    t[0] = 22000.0
    assert w.tick() is not None and len(llm.calls) == 2


def test_not_enough_new_exchanges_means_no_call_and_sleep_skips_the_idle_wait(tmp_path):
    st = make_store(tmp_path, n_exchanges=2)
    w, llm, t, idle = watcher(st, idle=[5000.0])
    assert w.tick() is None and not llm.calls                                    # idle, but only 2 new exchanges
    for i in range(4):
        st.log_exchange(f"x{i}", "ok", [])
    idle[0] = 10.0
    w.nudge()                                                                    # "go to sleep": no idle wait needed
    assert w.tick() is not None and len(llm.calls) == 1


def test_a_failing_pass_never_raises_into_the_service(tmp_path):
    st = make_store(tmp_path, n_exchanges=8)
    def boom(system, user):
        raise RuntimeError("network down")
    con = Consolidator(st, boom, min_new_exchanges=3)
    w = ConsolidationWatcher(con, lambda: 9999.0, idle_s=10, clock=lambda: 0.0)
    assert w.tick() is None


def test_reflections_about_the_robot_himself_are_rejected(tmp_path):
    st = make_store(tmp_path)
    plan = {"reflections": [{"text": "It seems G2 tends to respond with curiosity.", "importance": 2},
                            {"text": "It seems they like showing G2 new things.", "importance": 2}]}
    Consolidator(st, llm_returning(plan), min_new_exchanges=1).run(apply=True)
    refl = [r["fact"] for r in st.list_facts() if r["source"] == "reflection"]
    assert refl == ["It seems they like showing G2 new things."]
