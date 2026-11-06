"""Edits made in the review page's Facts, Observations, Conversations, Pictures and Wall tabs, queued on this Mac and sent to the Pi later (user, 2026-11-04).

The tabs read the copy of G2's data that is on this Mac (the newest memory snapshot, the pictures folder), so they work with the Pi off. An edit (add, change, delete, name, move, trash, restore)
is applied to that copy at once and ALSO queued here; the Pi gets the same command when it is reachable: at the start of every sync (tools/g2_sync.sh), with `python tools/g2_review_queue.py apply`,
or the page's Apply now button. A failed edit stays in the queue with the reason.

  ~/Desktop/G2Memory/review_edits.json            the queue (a JSON list, oldest first)
  ~/Desktop/G2Memory/review_edits_applied.jsonl   what was sent, with the Pi's answer

  python tools/g2_review_queue.py list | apply | cancel ID       (G2_PI = user@host is needed only to apply)

Standard library only.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid

DEFAULT_DIR = "~/Desktop/G2Memory"
ALLOWED = {                                   # module -> the sub-commands that may be queued (reads are never queued)
    "pi_pipeline.memory.review": {"delete", "restore", "add-fact", "edit-fact", "add-observation", "edit-observation", "empty-trash"},
    "pi_pipeline.vision.exploration_pictures": {"trash", "restore", "name", "label", "move", "empty-trash"},
    "pi_pipeline.vision.wall_pictures": {"trash", "restore", "empty-trash"},
}


def folder(d: str | None = None) -> str:
    return os.path.expanduser(d or os.environ.get("G2_REVIEW_DIR", DEFAULT_DIR))


def _path(d: str | None, name: str) -> str:
    return os.path.join(folder(d), name)


def check(module: str, args: list[str]) -> None:
    if module not in ALLOWED or not args or args[0] not in ALLOWED[module]:
        raise ValueError(f"not a queueable edit: {module} {' '.join(args[:1])}")
    if any((not isinstance(a, str)) or "\x00" in a for a in args):
        raise ValueError("bad argument")


def describe(e: dict) -> str:
    return e.get("text") or f"{e['module'].rsplit('.', 1)[-1]} {' '.join(e['args'])}"[:200]


def pending(d: str | None = None) -> list[dict]:
    try:
        rows = json.load(open(_path(d, "review_edits.json")))
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def save(rows: list[dict], d: str | None = None) -> None:
    p = _path(d, "review_edits.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(rows, indent=1) + "\n")
    os.replace(tmp, p)


def add(module: str, args: list[str], text: str = "", d: str | None = None, **extra) -> dict:
    check(module, args)
    row = {"id": uuid.uuid4().hex[:8], "added": time.strftime("%Y-%m-%d %H:%M:%S"), "module": module, "args": list(args), "text": text, **extra}
    rows = pending(d)
    rows.append(row)
    save(rows, d)
    return row


def remove(edit_id: str, d: str | None = None) -> dict | None:
    rows = pending(d)
    gone = next((r for r in rows if r.get("id") == edit_id), None)
    if gone is not None:
        save([r for r in rows if r is not gone], d)
    return gone


def history(d: str | None = None, n: int = 30) -> list[dict]:
    out = []
    try:
        for ln in open(_path(d, "review_edits_applied.jsonl")):
            if ln.strip():
                out.append(json.loads(ln))
    except (OSError, ValueError):
        pass
    return out[-n:][::-1]


def _ssh(host: str, remote: str, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", host, remote], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


GONE = re.compile(r"\bno \w+ record \d+\b")           # the Pi's answer to a delete of a record it no longer has


def apply(d: str | None = None, host: str | None = None, run=_ssh) -> dict:
    """Send every queued edit to the Pi, oldest first. {"applied", "failed", "left", "message"}; nothing is lost when the Pi cannot be reached.
    One send at a time (a sync and the page's button at once left deletes behind that the second one failed on: the record was already gone)."""
    os.makedirs(folder(d), exist_ok=True)
    with open(_path(d, "review_edits.lock"), "w") as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"applied": 0, "failed": 0, "left": len(pending(d)), "message": "another send is running: wait for it"}
        return _apply(d, host, run)


def _apply(d, host, run) -> dict:
    rows = pending(d)
    if not rows:
        return {"applied": 0, "failed": 0, "left": 0, "message": "nothing waiting"}
    host = host or os.environ.get("G2_PI", "")
    if not host:
        return {"applied": 0, "failed": 0, "left": len(rows), "message": "G2_PI is not set: the edits stay queued"}
    try:
        code, _ = run(host, "true", 20)
    except (OSError, subprocess.TimeoutExpired):
        code = 255
    if code != 0:
        return {"applied": 0, "failed": 0, "left": len(rows), "message": "the Pi does not answer: the edits stay queued"}
    done, keep = 0, []
    for i, r in enumerate(rows):
        try:
            check(r["module"], r["args"])
            cmd = "cd ~/bittleX && pi_pipeline/.venv/bin/python -m " + r["module"] + " " + " ".join(shlex.quote(a) for a in r["args"])
            code, out = run(host, cmd)
            last = out.strip().splitlines()[-1] if out.strip() else ""
            try:
                err = json.loads(last).get("error") if last.startswith("{") else None
            except ValueError:
                err = None
            if code not in (0, 1) or err or (code == 1 and not last):
                raise RuntimeError(err or out[-300:] or f"exit {code}")
        except (OSError, subprocess.TimeoutExpired) as e:
            keep.extend(rows[i:])
            save(keep, d)
            return {"applied": done, "failed": len(keep) - len(rows[i:]), "left": len(keep), "message": f"lost the Pi part way ({e}): the rest stay queued"}
        except (ValueError, RuntimeError) as e:
            if r["args"][0] == "delete" and GONE.search(str(e)):          # already deleted on the Pi (user, 2026-11-06): nothing left to send, so it leaves the queue
                with open(_path(d, "review_edits_applied.jsonl"), "a") as f:
                    f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": True, "text": describe(r), "answer": "already gone on the Pi"}) + "\n")
                done += 1
                continue
            keep.append({**r, "error": str(e)[-300:]})
            continue
        done += 1
        with open(_path(d, "review_edits_applied.jsonl"), "a") as f:
            f.write(json.dumps({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": True, "text": describe(r), "answer": out[-300:]}) + "\n")
    save(keep, d)
    return {"applied": done, "failed": len(keep), "left": len(keep), "message": f"sent {done}" + (f", {len(keep)} failed (they stay queued with the reason)" if keep else "")}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        print("\n".join(f"{r['id']}  {describe(r)}" + (f"   ERROR: {r['error']}" if r.get("error") else "") for r in pending()) or "no edits waiting")
    elif cmd == "apply":
        res = apply()
        if res["applied"] or res["failed"] or res["left"]:
            print("review edits:", res["message"])
    elif cmd == "cancel" and len(argv) > 1:
        print("cancelled" if remove(argv[1]) else "no such edit")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
