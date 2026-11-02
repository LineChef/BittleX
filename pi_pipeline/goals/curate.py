"""Automatic curation of the goal data (user, 2026-11-01): what he learned never goes stale or stays unexamined.

  python -m pi_pipeline.goals curate [--dry] [--restore]      (g2goal curate)

Runs by itself after every goal session and every `g2goal pull`. It does four things and writes `curation_report.md` beside the journal:

  1. Retire old-scoring attempts. SCORING_EPOCH names the version of the scoring and the ball finder; an attempt from an earlier epoch is taken out of his records like a
     `verdict wrong` (note "retired: scoring epoch"). Bump the epoch (and add its start time to SCORING_BREAKS) in a commit that changes how attempts are scored or seen.
     An attempt you marked right is kept. The journal keeps every attempt.
  2. Check the lessons he saved to memory (facts with source goal_lesson) against their evidence (the decisions in the journal whose note is the lesson):
       - every attempt behind it retired or marked wrong: the lesson is deleted (to the trash, `--restore` brings it back)
       - newer attempts under the current scoring disagree (the value it kept succeeded under a third of 3 or more tries), or it is over 60 days old with nothing new behind it: FLAGGED only, in the report
  3. Rotate the logs: turn_log.jsonl keeps 30 days, the older lines go to the trash.
  4. Empty the trash of anything older than 30 days.

Nothing it never deletes: your goals, overrides, "right" verdicts, the journal, facts you told him. `--dry` lists what it would do and changes nothing.
"""
from __future__ import annotations

import json
import os
import time

SCORING_EPOCH = {"ball_punt": 2}                   # per goal; a goal not listed is epoch 1
SCORING_BREAKS = {"ball_punt": {2: "2026-11-01 01:20:00"}}   # epoch n starts at this time: attempts without a recorded epoch are placed by their time
# 2: the ball finder's close-up and dim passes, the one-picture-after-the-punch scoring, the claw camera's real turn per side (2026-11-01 night)
LESSON_STALE_DAYS = 60
LOG_DAYS = 30
TRASH_DAYS = 30
DISAGREE_MIN_TRIES = 3
DISAGREE_BELOW = 1 / 3


def epoch_now(goal: str) -> int:
    return SCORING_EPOCH.get(goal, 1)


def attempt_epoch(row: dict) -> int:
    """The scoring epoch an attempt was made under: recorded, else placed by its time."""
    if row.get("scoring_epoch"):
        return int(row["scoring_epoch"])
    best = 1
    for n, start in (SCORING_BREAKS.get(row.get("goal"), {})).items():
        if str(row.get("time", "")) >= start:
            best = max(best, int(n))
    return best


def curation_dir() -> str:
    from .journal import journal_path
    d = os.path.join(os.path.dirname(journal_path()), "goal_curation")
    os.makedirs(os.path.join(d, "trash"), exist_ok=True)
    return d


def _trash(d: str, kind: str, payload: dict) -> None:
    with open(os.path.join(d, "trash", f"{kind}.jsonl"), "a") as f:
        f.write(json.dumps({"trashed": time.strftime("%Y-%m-%d %H:%M:%S"), **payload}) + "\n")


def _latest_verdicts(rows: list[dict]) -> dict:
    out = {}
    for r in rows:
        if r.get("kind") == "verdict":
            out[(r.get("session"), r.get("index"))] = r
    return out


def retire_old_attempts(journal, state, goals: dict, dry: bool) -> list[str]:
    """Take every counted attempt from an older scoring epoch out of his records (once; it is a `verdict wrong`)."""
    from . import overrides as ovr
    from .__main__ import _judge_for
    from .approach import Outcome
    from .journal import conditions_key
    rows = journal.read()
    verdicts = _latest_verdicts(rows)
    cond_of = {r["session"]: conditions_key(r.get("conditions") or {}) for r in rows if r.get("kind") == "session_start"}
    said = []
    for r in rows:
        if r.get("kind") != "attempt" or r.get("number") is None or (r.get("outcome") or {}).get("score") is None:
            continue
        g = goals.get(r.get("goal"))
        if g is None or attempt_epoch(r) >= epoch_now(g.id):
            continue
        v = verdicts.get((r.get("session"), r.get("index")))
        if v is not None:                                           # already judged by you (right) or already taken out (wrong)
            continue
        said.append(f"retired {g.id} attempt #{r['number']} ({r['time']}, scored {r['outcome']['code']}): made under scoring epoch {attempt_epoch(r)}, now {epoch_now(g.id)}")
        if dry:
            continue
        cond = cond_of.get(r["session"], "")
        o = r["outcome"]
        outcome = Outcome(o["code"], o["score"], o["success"], o.get("text", ""), stages=o.get("stages"))
        _a, _k, _b, _c, j, _ov = _judge_for(g, cond, state)
        live = state.for_goal(g.id, cond)
        if live:
            j.state = live
            for kk, vv in (("values", {}), ("pressure", {}), ("settled", []), ("banned", {}), ("current", {}), ("suggestions", {})):
                live.setdefault(kk, vv)
            live.setdefault("count", 0)
            j.retract(outcome, r["settings"])
        journal.write("verdict", goal=g.id, session=r["session"], index=r["index"], number=r["number"], conditions=cond, verdict="wrong", scored=o["code"], note="retired: scoring epoch")
    if said and not dry:
        state.save()
    return said


def check_lessons(journal, store, goals: dict, dry: bool, now: float | None = None) -> tuple[list[str], list[str]]:
    """(deleted, flagged) lesson descriptions."""
    from .journal import LESSON_SOURCE
    now = now or time.time()
    rows = journal.read()
    verdicts = _latest_verdicts(rows)

    def gone(sess, idx) -> bool:
        v = verdicts.get((sess, idx))
        return v is not None and v.get("verdict") == "wrong"
    attempts = {(r["session"], r["index"]): r for r in rows if r.get("kind") == "attempt"}
    decisions = [r for r in rows if r.get("kind") == "decision" and r.get("note")]
    deleted, flagged = [], []
    d = curation_dir()
    for f in store.list_facts():
        if f["source"] != LESSON_SOURCE:
            continue
        text = f["fact"]
        backing = [x for x in decisions if x["note"] and x["note"] in text]
        if not backing:
            continue                                                 # no evidence on record: left alone, not guessed at
        evid = set()
        for x in backing:
            if x.get("index") is None:                              # a note about the whole session (e.g. which search order works best): every counted attempt of that session is its evidence
                evid |= {k for k, a in attempts.items() if k[0] == x["session"] and a.get("number") is not None}
            else:
                evid.add((x["session"], x["index"]))
        if evid and all(gone(s, i) for s, i in evid):
            deleted.append(f"lesson #{f['id']} deleted: every attempt behind it was retracted or retired: {text}")
            if not dry:
                _trash(d, "lessons", {"id": f["id"], "fact": text, "importance": f["importance"], "reason": "evidence retracted"})
                store.delete_fact(f["id"])
            continue
        ts = time.mktime(time.strptime(max(x["time"] for x in backing), "%Y-%m-%d %H:%M:%S"))
        later = []
        for x in backing:
            g = goals.get(x["goal"])
            knob, val = x.get("knob"), x.get("new")
            if g is None or not knob:
                continue
            for (s, i), a in attempts.items():
                if a.get("goal") == x["goal"] and a["time"] > x["time"] and a.get("number") is not None and not gone(s, i) and attempt_epoch(a) >= epoch_now(g.id) \
                        and (a.get("settings") or {}).get(knob) == val:
                    later.append(bool((a.get("outcome") or {}).get("success")))
        if len(later) >= DISAGREE_MIN_TRIES and sum(later) / len(later) < DISAGREE_BELOW:
            flagged.append(f"lesson #{f['id']} flagged: later attempts disagree ({sum(later)} of {len(later)} good with it): {text}")
        elif (now - ts) / 86400.0 > LESSON_STALE_DAYS and not later:
            flagged.append(f"lesson #{f['id']} flagged: over {LESSON_STALE_DAYS} days old and nothing newer backs it: {text}")
    return deleted, flagged


def rotate_turn_log(dry: bool, now: float | None = None) -> int:
    """Old lines of the turn log and the decision log go to the trash files."""
    return (_rotate_log("G2_TURN_LOG", "~/.local/share/g2/turn_log.jsonl", "turn_log.jsonl", dry, now)
            + _rotate_log("G2_DECISION_LOG", "~/.local/share/g2/decision_log.jsonl", "decision_log.jsonl", dry, now))


def _rotate_log(env: str, default: str, trash_name: str, dry: bool, now: float | None = None) -> int:
    path = os.path.expanduser(os.environ.get(env, default))
    if not os.path.exists(path):
        return 0
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((now or time.time()) - LOG_DAYS * 86400))
    keep, old = [], []
    for ln in open(path):
        try:
            (old if json.loads(ln).get("time", "9") < cutoff else keep).append(ln)
        except ValueError:
            keep.append(ln)
    if old and not dry:
        with open(os.path.join(curation_dir(), "trash", trash_name), "a") as f:
            f.writelines(old)
        with open(path, "w") as f:
            f.writelines(keep)
    return len(old)


def empty_trash(dry: bool, now: float | None = None) -> int:
    """Lines in the trash files older than TRASH_DAYS go for good."""
    cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime((now or time.time()) - TRASH_DAYS * 86400))
    n = 0
    tdir = os.path.join(curation_dir(), "trash")
    for name in os.listdir(tdir):
        p = os.path.join(tdir, name)
        keep, gone = [], 0
        for ln in open(p):
            try:
                stamp = json.loads(ln).get("trashed") or json.loads(ln).get("time") or "9"
            except ValueError:
                stamp = "9"
            if stamp < cutoff:
                gone += 1
            else:
                keep.append(ln)
        n += gone
        if gone and not dry:
            with open(p, "w") as f:
                f.writelines(keep)
    return n


def prune_mac_history(folder: str, dry: bool = False, now: float | None = None) -> list[str]:
    """In the Mac copy's history/: the last 14 days daily, older ones only the Sunday copies."""
    out = []
    hist = os.path.join(os.path.expanduser(folder), "history")
    if not os.path.isdir(hist):
        return out
    today = time.strftime("%Y%m%d", time.localtime(now or time.time()))
    for name in sorted(os.listdir(hist)):
        try:
            t = time.strptime(name, "%Y%m%d")
        except ValueError:
            continue
        age = (time.mktime(time.strptime(today, "%Y%m%d")) - time.mktime(t)) / 86400.0
        if age > 14 and t.tm_wday != 6:
            out.append(f"history copy {name} removed (older than 14 days, not a Sunday)")
            if not dry:
                import shutil
                shutil.rmtree(os.path.join(hist, name), ignore_errors=True)
    return out


def restore(store, dry: bool = False) -> list[str]:
    """Put back every lesson in the trash (once; they leave the trash file)."""
    p = os.path.join(curation_dir(), "trash", "lessons.jsonl")
    if not os.path.exists(p):
        return []
    out = []
    for ln in open(p):
        r = json.loads(ln)
        out.append(f"lesson restored: {r['fact']}")
        if not dry:
            store.add_fact(r["fact"], importance=int(r.get("importance", 2)), core=False, source="goal_lesson")
    if not dry:
        os.remove(p)
    return out


def curate(*, dry: bool = False, journal=None, state=None, store=None, goals: dict | None = None, now: float | None = None) -> list[str]:
    from .journal import Journal, State
    from .spec import load
    journal = journal or Journal()
    state = state or State()
    goals = goals if goals is not None else load()[0]
    if store is None:
        try:
            from ..config import settings
            from ..memory.store import Store
            store = Store(settings.memory_db_path)
        except Exception:  # noqa: BLE001
            store = None
    lines = retire_old_attempts(journal, state, goals, dry)
    flagged = []
    if store is not None:
        deleted, flagged = check_lessons(journal, store, goals, dry, now)
        lines += deleted + flagged
    n = rotate_turn_log(dry, now)
    if n:
        lines.append(f"{n} turn log line(s) older than {LOG_DAYS} days moved to the trash")
    n = empty_trash(dry, now)
    if n:
        lines.append(f"{n} trash entr(ies) older than {TRASH_DAYS} days removed for good")
    if not dry:
        stamp = time.strftime("%Y-%m-%d %I:%M %p")
        path = os.path.join(curation_dir(), "curation_report.md")
        with open(path, "w") as f:
            f.write(f"# Curation report ({stamp})\n\n" + ("\n".join(f"- {x}" for x in lines) if lines else "Nothing to do.") + "\n")
    return lines
