"""Memory review: delete moves a record to the trash, restore brings it back, only empty-trash is permanent. Temp databases only."""
import json

import pytest

from pi_pipeline.memory import review as R
from pi_pipeline.memory.store import Store


@pytest.fixture
def db(tmp_path):
    p = str(tmp_path / "m.db")
    st = Store(p)
    st.add_fact("Their favorite color is blue.")
    st.add_fact("The dog is named Rex.")
    st.log_exchange("what is the weather", "It is sunny.", [])
    st.log_exchange("remember the mug", "Okay.", [])
    st.add_observation("a red mug on the floor", "mug")
    st.close()
    return p


def test_list_and_search(db):
    assert [r["fact"] for r in R.list_records(db, "facts")] == ["The dog is named Rex.", "Their favorite color is blue."]
    assert [r["user_text"] for r in R.list_records(db, "exchanges", query="mug")] == ["remember the mug"]
    assert R.list_records(db, "observations")[0]["caption"] == "a red mug on the floor"
    with pytest.raises(ValueError):
        R.list_records(db, "nope")


def test_delete_goes_to_the_trash_and_restore_puts_it_back_with_the_same_id(db):
    fid = R.list_records(db, "facts", query="Rex")[0]["id"]
    tid = R.delete_record(db, "facts", fid)
    assert [r["fact"] for r in R.list_records(db, "facts")] == ["Their favorite color is blue."]
    t = R.list_trash(db)
    assert len(t) == 1 and t[0]["row"]["fact"] == "The dog is named Rex." and t[0]["row_id"] == fid
    assert R.restore_record(db, tid) == {"kind": "facts", "row_id": fid}
    assert any(r["id"] == fid and r["fact"] == "The dog is named Rex." for r in R.list_records(db, "facts")) and R.list_trash(db) == []


def test_deleting_an_exchange_keeps_the_search_index_consistent(db):
    eid = R.list_records(db, "exchanges", query="mug")[0]["id"]
    tid = R.delete_record(db, "exchanges", eid)
    st = Store(db)
    assert st.search_exchanges("mug", 5) == [] and st.exchange_count() == 1
    st.close()
    R.restore_record(db, tid)
    st = Store(db)
    assert [r["user_text"] for r in st.search_exchanges("mug", 5)] == ["remember the mug"]
    st.close()


def test_errors_and_the_only_permanent_delete(db):
    with pytest.raises(KeyError):
        R.delete_record(db, "facts", 9999)
    with pytest.raises(KeyError):
        R.restore_record(db, 9999)
    fid = R.list_records(db, "facts")[0]["id"]
    R.delete_record(db, "facts", fid)
    assert R.empty_trash(db) == 1 and R.list_trash(db) == []


def test_restore_refuses_when_the_text_exists_again(db):
    fid = R.list_records(db, "facts", query="Rex")[0]["id"]
    tid = R.delete_record(db, "facts", fid)
    Store(db).add_fact("The dog is named Rex.")                 # the same fact was learned again meanwhile
    with pytest.raises(ValueError):
        R.restore_record(db, tid)
    assert len(R.list_trash(db)) == 1                              # still in the trash, not lost


def test_backup_is_a_usable_copy_and_the_cli_prints_json(db, capsys):
    path = R.backup(db)
    assert [r["fact"] for r in R.list_records(path, "facts")][0] == "The dog is named Rex."
    assert R.main(["--db", db, "list", "facts", "--limit", "1"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["fact"] == "The dog is named Rex."
    assert R.main(["--db", db, "delete", "facts", "424242"]) == 1
    assert "error" in json.loads(capsys.readouterr().out)


def test_trash_commands_finds_only_short_command_turns_and_moves_them_reversibly(tmp_path):
    p = str(tmp_path / "c.db")
    st = Store(p)
    st.log_exchange("rest", "Okay.", ["d"])
    st.log_exchange("stand up", "Okay.", ["kup"])
    st.log_exchange("tell me a long story about the garden please", "Once upon a time there was a garden with many flowers.", [])
    st.log_exchange("walk forward for ten seconds near the couch please now", "Walking.", ["wkF"])     # long request: kept
    st.close()
    assert len(R.command_exchange_ids(p)) == 2
    assert R.main(["--db", p, "trash-commands"]) == 0 and len(R.list_records(p, "exchanges")) == 4          # dry run changes nothing
    assert R.main(["--db", p, "trash-commands", "--apply"]) == 0
    assert [r["user_text"] for r in R.list_records(p, "exchanges")] == ["walk forward for ten seconds near the couch please now", "tell me a long story about the garden please"]
    assert len(R.list_trash(p)) == 2


def test_add_and_edit_facts_and_observations_by_hand(tmp_path):
    import sqlite3
    from pi_pipeline.memory import review as R
    db = str(tmp_path / "m.db")
    st = Store(db)
    st.close()
    f = R.add_fact(db, "  The dishwasher is next to the fridge  ", importance=4, core=True)
    assert f["fact"] == "The dishwasher is next to the fridge"
    with pytest.raises(ValueError):
        R.add_fact(db, "The dishwasher is next to the fridge")                # identical fact
    with pytest.raises(ValueError):
        R.add_fact(db, "   ")
    R.edit_fact(db, f["id"], fact="The dishwasher is left of the fridge", importance=2, core=False)
    row = [r for r in R.list_records(db, "facts") if r["id"] == f["id"]][0]
    assert row["fact"] == "The dishwasher is left of the fridge" and row["importance"] == 2 and row["core"] == 0
    with pytest.raises(ValueError):
        R.edit_fact(db, 9999, fact="x")
    o = R.add_observation(db, "A steel door with a black handle", "dishwasher")
    R.edit_observation(db, o["id"], caption="A steel door with a black handle and a display", labels="dishwasher, kitchen")
    ob = [r for r in R.list_records(db, "observations") if r["id"] == o["id"]][0]
    assert ob["caption"].endswith("a display") and ob["labels"] == "dishwasher, kitchen"
    c = sqlite3.connect(db)                                                   # the search index follows the edit
    hits = c.execute("SELECT rowid FROM observations_fts WHERE observations_fts MATCH 'display'").fetchall()
    assert [h[0] for h in hits] == [o["id"]]
