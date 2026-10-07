"""Review G2's memory records and delete the ones you do not want, with an undo. JSON in, JSON out, so a review page can drive it (tools/g2_review.py).

    python -m pi_pipeline.memory.review list facts|exchanges|observations [--limit N] [--query TEXT]
    python -m pi_pipeline.memory.review delete facts|exchanges|observations ID      # moves the record to the trash table, prints the trash id
    python -m pi_pipeline.memory.review restore TRASH_ID
    python -m pi_pipeline.memory.review trash                                       # what is in the trash
    python -m pi_pipeline.memory.review empty-trash                                 # the only permanent delete
    python -m pi_pipeline.memory.review trash-commands [--apply]                   # the logged exchanges that were only a short command (dry run unless --apply)
    python -m pi_pipeline.memory.review backup                                      # a safe copy of the database (done before the first delete of a review session)

A delete never destroys a record: the row is copied (as JSON) into `review_trash` and then removed from its table (the full-text index follows through the
database's own triggers). `restore` puts it back with the same id. Only `empty-trash` removes records for good, and nothing calls it automatically.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

KINDS = {"facts": ("facts", ("fact",)), "exchanges": ("exchanges", ("user_text", "assistant_text")), "observations": ("observations", ("caption", "labels"))}

_TRASH = """CREATE TABLE IF NOT EXISTS review_trash (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, row_id INTEGER NOT NULL, row_json TEXT NOT NULL, deleted_at TEXT NOT NULL)"""


def _conn(db: str) -> sqlite3.Connection:
    c = sqlite3.connect(db, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute(_TRASH)
    return c


def _check(kind: str) -> tuple:
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; use one of {sorted(KINDS)}")
    return KINDS[kind]


def list_records(db: str, kind: str, limit: int = 200, query: str = "") -> list[dict]:
    table, text_cols = _check(kind)
    c = _conn(db)
    try:
        where, params = "", []
        if query:
            where = " WHERE " + " OR ".join(f"{col} LIKE ?" for col in text_cols)
            params = [f"%{query}%"] * len(text_cols)
        rows = c.execute(f"SELECT * FROM {table}{where} ORDER BY id DESC LIMIT ?", (*params, int(limit))).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def delete_record(db: str, kind: str, row_id: int) -> int:
    """Move one record to the trash; returns the trash id. Raises KeyError if there is no such record."""
    table, _ = _check(kind)
    c = _conn(db)
    try:
        row = c.execute(f"SELECT * FROM {table} WHERE id = ?", (int(row_id),)).fetchone()
        if row is None:
            raise KeyError(f"no {kind} record {row_id}")
        cur = c.execute("INSERT INTO review_trash (kind, row_id, row_json, deleted_at) VALUES (?, ?, ?, ?)",
                        (kind, int(row_id), json.dumps(dict(row)), time.strftime("%Y-%m-%d %H:%M:%S")))
        c.execute(f"DELETE FROM {table} WHERE id = ?", (int(row_id),))
        c.commit()
        return int(cur.lastrowid)
    finally:
        c.close()


def restore_record(db: str, trash_id: int) -> dict:
    """Put a trashed record back with its original id. Raises KeyError for an unknown trash id, ValueError if the id is taken again."""
    c = _conn(db)
    try:
        t = c.execute("SELECT * FROM review_trash WHERE id = ?", (int(trash_id),)).fetchone()
        if t is None:
            raise KeyError(f"no trash item {trash_id}")
        table, _ = _check(t["kind"])
        row = json.loads(t["row_json"])
        cols = list(row)
        try:
            c.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [row[k] for k in cols])
        except sqlite3.IntegrityError as e:
            raise ValueError(f"cannot restore: {e} (a record with that id or text exists again)") from e
        c.execute("DELETE FROM review_trash WHERE id = ?", (int(trash_id),))
        c.commit()
        return {"kind": t["kind"], "row_id": t["row_id"]}
    finally:
        c.close()


def list_trash(db: str) -> list[dict]:
    c = _conn(db)
    try:
        return [{"trash_id": r["id"], "kind": r["kind"], "row_id": r["row_id"], "deleted_at": r["deleted_at"], "row": json.loads(r["row_json"])}
                for r in c.execute("SELECT * FROM review_trash ORDER BY id DESC")]
    finally:
        c.close()


def empty_trash(db: str) -> int:
    c = _conn(db)
    try:
        n = c.execute("SELECT COUNT(*) FROM review_trash").fetchone()[0]
        c.execute("DELETE FROM review_trash")
        c.commit()
        return int(n)
    finally:
        c.close()


def command_exchange_ids(db: str) -> list[int]:
    """Ids of logged exchanges that were only a command: an action, a request of 5 words or fewer, a reply of 10 or fewer (memory.is_command_turn's rule,
    from before 2026-10-07 when such turns were still logged)."""
    c = _conn(db)
    try:
        rows = c.execute("SELECT id, user_text, assistant_text, actions FROM exchanges").fetchall()
        return [r["id"] for r in rows if (r["actions"] or "").strip() and len(r["user_text"].split()) <= 5 and len((r["assistant_text"] or "").split()) <= 10]
    finally:
        c.close()


def backup(db: str) -> str:
    """A consistent copy of the database next to it (sqlite's own backup, safe while G2 is running). Returns the path."""
    dest = str(Path(db).with_name(Path(db).stem + time.strftime("-review-backup-%Y%m%d-%H%M%S") + ".db"))
    src = sqlite3.connect(db, timeout=10)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    return dest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pi_pipeline.memory.review")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("kind"); p.add_argument("--limit", type=int, default=200); p.add_argument("--query", default="")
    p = sub.add_parser("delete"); p.add_argument("kind"); p.add_argument("id", type=int)
    p = sub.add_parser("restore"); p.add_argument("trash_id", type=int)
    p = sub.add_parser("trash-commands"); p.add_argument("--apply", action="store_true")
    sub.add_parser("trash"); sub.add_parser("empty-trash"); sub.add_parser("backup")
    ap.add_argument("--db", default=None)
    args = ap.parse_args(argv)
    if args.db is None:
        from ..config import settings
        args.db = settings.memory_db_path
    try:
        if args.cmd == "list":
            out = list_records(args.db, args.kind, args.limit, args.query)
        elif args.cmd == "delete":
            out = {"trash_id": delete_record(args.db, args.kind, args.id)}
        elif args.cmd == "restore":
            out = restore_record(args.db, args.trash_id)
        elif args.cmd == "trash":
            out = list_trash(args.db)
        elif args.cmd == "trash-commands":
            ids = command_exchange_ids(args.db)
            if args.apply:
                backup(args.db)
                for i in ids:
                    delete_record(args.db, "exchanges", i)
            out = {"command_only_exchanges": len(ids), "moved_to_trash": len(ids) if args.apply else 0}
        elif args.cmd == "empty-trash":
            out = {"removed": empty_trash(args.db)}
        else:
            out = {"backup": backup(args.db)}
    except (KeyError, ValueError) as e:
        print(json.dumps({"error": str(e)}))
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
