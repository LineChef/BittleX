"""The Facts tab of the review page: usage and source on each fact (memory/review.py), the tidy-up findings (tools/g2_review.py) and the page code that draws them."""
import importlib.util
from pathlib import Path

from pi_pipeline.memory import review
from pi_pipeline.memory.store import Store

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def _db(tmp_path):
    """A memory database like the Pi's: facts G2 saved himself (the memory refuses dates and near-duplicates), plus ones typed in the review page, which has no such filter."""
    db = str(tmp_path / "m.db")
    st = Store(db)
    st.add_fact("The dog is named Rex.", source="told")
    st.add_fact("The kitchen is next to the dining room.", source="hand")
    ids = {f["fact"]: f["id"] for f in st.list_facts()}
    st.record_fact_use([ids["The dog is named Rex."]], {ids["The dog is named Rex."]}, set())
    for _ in range(24):
        st.record_fact_use([ids["The kitchen is next to the dining room."]], set(), set())
    st._db.commit()
    st._db.close()
    for t in ("The dog is named Rex!", "Sam went to the store on Monday at 3pm.", "I look like a small black dog robot.", "I look like a robot dog with a claw."):
        review.add_fact(db, t)
    return db, ids


def test_facts_come_with_source_and_usage(tmp_path):
    db, ids = _db(tmp_path)
    rows = {r["fact"]: r for r in review.list_records(db, "facts", 100, "")}
    rex = rows["The dog is named Rex."]
    assert rex["source"] == "told" and rex["injected"] == 1 and rex["declared"] == 1 and rex["last_used"]
    kitchen = rows["The kitchen is next to the dining room."]
    assert kitchen["source"] == "hand" and kitchen["injected"] == 24 and kitchen["declared"] == 0 and kitchen["matched"] == 0
    assert rows["The dog is named Rex!"]["injected"] == 0                                           # never given: zeros, not missing
    assert [r["fact"] for r in review.list_records(db, "facts", 100, "kitchen")] == ["The kitchen is next to the dining room."]      # the search still works with the join


def test_a_database_without_the_usage_table_still_lists_facts(tmp_path):
    db, _ = _db(tmp_path)
    import sqlite3
    c = sqlite3.connect(db)
    c.execute("DROP TABLE fact_use")
    c.commit()
    c.close()
    rows = review.list_records(db, "facts", 100, "")
    assert len(rows) == 6 and "injected" not in rows[0]


def test_the_tidy_up_finds_duplicates_dated_facts_and_a_second_look_like(tmp_path, monkeypatch):
    db, ids = _db(tmp_path)
    monkeypatch.syspath_prepend(str(TOOLS))
    spec = importlib.util.spec_from_file_location("g2_review_t", TOOLS / "g2_review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)

    class Fixed(R.Remote):
        def memory(self, *a):
            return review.list_records(db, "facts", 2000, "")

    t = R.App(Fixed("u@h")).facts_tidy()
    pair = {p["a"]["fact"] for p in t["duplicates"]} | {p["b"]["fact"] for p in t["duplicates"]}
    assert {"The dog is named Rex.", "The dog is named Rex!"} <= pair
    assert [r["fact"] for r in t["dated"]] == ["Sam went to the store on Monday at 3pm."]
    assert len(t["look_like"]) == 2                                                                  # two "I look like" facts: one slot
    assert R.App(Fixed("u@h")).facts_info()["core_max"] >= 1


def test_the_page_carries_the_facts_tab_code():
    spec = importlib.util.spec_from_file_location("g2_review_p", TOOLS / "g2_review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    assert "/*MEMORY_UI*/" not in R.PAGE and "renderFacts" in R.PAGE and "renderTidy" in R.PAGE and "window.g2ask" in R.PAGE


def test_the_sync_button_reports_what_the_last_run_did(tmp_path, monkeypatch):
    """g2_sync.sh exits 0 even when the Pi does not answer, so the page reads sync_last.json instead of the exit code."""
    import json
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "Desktop" / "G2Memory").mkdir(parents=True)
    (tmp_path / "Desktop" / "G2Memory" / "sync_last.json").write_text(json.dumps({"time": "2026-11-04 20:44:02", "outcome": "offline", "message": "the Pi does not answer"}))
    spec = importlib.util.spec_from_file_location("g2_review_s", TOOLS / "g2_review.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    last = R.App.sync_last()
    assert last["outcome"] == "offline" and last["when"] == "Nov 4, 8:44 PM"
    (tmp_path / "Desktop" / "G2Memory" / "sync_last.json").unlink()
    assert R.App.sync_last() is None
