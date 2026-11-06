"""tools/g2_review_queue.py: a delete the Pi no longer has leaves the queue, and two sends never run at once (user, 2026-11-06: 70 deleted records stayed listed after Send)."""
import importlib.util
import json
import fcntl
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("g2_review_queue", Path(__file__).resolve().parents[2] / "tools" / "g2_review_queue.py")
Q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(Q)

MOD = "pi_pipeline.memory.review"


def _queue(tmp_path):
    for n in (19, 20, 21):
        Q.add(MOD, ["delete", "facts", str(n)], f"Delete fact #{n}", str(tmp_path))


def test_a_delete_of_a_record_the_pi_already_lost_leaves_the_queue_and_others_still_send(tmp_path):
    _queue(tmp_path)

    def run(host, cmd, timeout=120):
        if cmd == "true":
            return 0, ""
        if cmd.endswith("facts 20"):
            return 1, json.dumps({"error": "no facts record 20"})
        return 0, json.dumps({"trash_id": 5})
    res = Q.apply(str(tmp_path), "pi", run)
    assert res["applied"] == 3 and res["left"] == 0 and Q.pending(str(tmp_path)) == []              # 19 and 21 sent, 20 was already gone
    assert "already gone" in "".join(h.get("answer", "") for h in Q.history(str(tmp_path)))


def test_another_error_stays_queued_with_its_reason(tmp_path):
    _queue(tmp_path)

    def run(host, cmd, timeout=120):
        if cmd == "true":
            return 0, ""
        return (1, json.dumps({"error": "database is locked"})) if cmd.endswith("facts 20") else (0, "{}")
    res = Q.apply(str(tmp_path), "pi", run)
    left = Q.pending(str(tmp_path))
    assert res["left"] == 1 and len(left) == 1 and "locked" in left[0]["error"]


def test_a_second_send_while_one_runs_is_refused_and_loses_nothing(tmp_path):
    _queue(tmp_path)
    with open(tmp_path / "review_edits.lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        res = Q.apply(str(tmp_path), "pi", lambda *a, **k: (0, ""))
    assert "another send" in res["message"] and len(Q.pending(str(tmp_path))) == 3
