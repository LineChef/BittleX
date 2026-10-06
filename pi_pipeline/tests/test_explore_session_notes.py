import queue
import sqlite3
import threading


def test_a_note_queued_from_another_thread_is_written_from_the_owner_thread(tmp_path):
    """The failure this guards: a sqlite connection made in one thread cannot be used from another."""
    db = sqlite3.connect(str(tmp_path / "m.db"))
    db.execute("create table f (t text)")
    q: "queue.Queue[str]" = queue.Queue()
    t = threading.Thread(target=lambda: q.put("The dog is often to the left of where I usually sit."))
    t.start(); t.join()
    while not q.empty():                       # what the session's main loop does
        db.execute("insert into f values (?)", (q.get_nowait(),))
    assert db.execute("select count(*) from f").fetchone()[0] == 1
