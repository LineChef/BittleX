"""Edits made in the Goals tab, queued on this Mac and applied to the Pi later (user, 2026-11-04: option B, "queue the edits").

The goal data on the Pi is the real copy; the Mac holds a pulled copy. An edit made in the tab never touches the Pi at once: it is written to a queue here, shown in the tab as
"will apply on the next sync", and applied by running the Pi's own `g2goal` command for it (so every check the command does still runs). Nothing is applied while a goal session is
running, and an edit that fails stays in the queue with the reason.

  ~/Desktop/G2Memory/goals/pending_edits.json     the queue (a JSON list, oldest first)
  ~/Desktop/G2Memory/goals/applied_edits.jsonl    what was applied (or refused), with the Pi's answer

  python tools/g2_goal_edits.py list | apply | cancel ID       (`g2goal apply`; also runs at the start of every `g2goal pull` and `g2goal run`)

Needs G2_PI (user@host) only to apply. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid

DEFAULT_DIR = "~/Desktop/G2Memory/goals"
SLUG = re.compile(r"^[A-Za-z0-9_]{1,64}$")
SCOPE = re.compile(r"^[A-Za-z0-9_=|:.\-]{1,200}$")
CONTROLS = ("free", "ask", "fixed")
MAX_TEXT = 600


def folder(d: str | None = None) -> str:
    return os.path.expanduser(d or os.environ.get("G2_GOALS_DIR", DEFAULT_DIR))


def _slug(v, what: str) -> str:
    if not isinstance(v, str) or not SLUG.match(v):
        raise ValueError(f"{what} must be letters, digits and underscores")
    return v


def _text(v, what: str) -> str:
    if not isinstance(v, str) or not v.strip() or "\x00" in v or len(v) > MAX_TEXT:
        raise ValueError(f"{what} must be 1 to {MAX_TEXT} characters")
    return v.strip()


def _num(v, what: str, lo=None, hi=None, whole=False) -> float | int:
    if isinstance(v, bool):
        raise ValueError(f"{what} must be a number")
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{what} must be a number") from None
    if x != x or (lo is not None and x < lo) or (hi is not None and x > hi):
        raise ValueError(f"{what} must be between {lo} and {hi}")
    if whole:
        if x != int(x):
            raise ValueError(f"{what} must be a whole number")
        return int(x)
    return x


def _value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.strip() and "\x00" not in v and len(v) <= 100):
        return str(v).strip()
    raise ValueError("the value is missing or too long")


def _scope_args(op: dict) -> list[str]:
    s = op.get("scope")
    if not s or s == "all":
        return []
    if not isinstance(s, str) or not SCOPE.match(s):
        raise ValueError("bad scope (for example attachment=arm|floor=tile)")
    return ["--scope", s]


def argv_for(op: dict) -> list[str]:
    """The `g2goal` arguments for one queued edit; ValueError says what is wrong with it (nothing is built from unchecked text)."""
    kind = op.get("op")
    if kind == "set":
        a = ["set", _slug(op.get("goal"), "goal")]
        if op.get("approach"):
            a += ["--approach", _slug(op["approach"], "approach")]
        if op.get("title") is not None:
            a += ["--title", _text(op["title"], "title")]
        for key, flag, lo, hi, whole in (("attempts", "--attempts", 1, 100, True), ("minutes", "--minutes", 0.5, 240, False), ("min_pack_pct", "--min-pack", 0, 100, True),
                                         ("target_successes", "--target", 0, 100, True), ("rest_between_s", "--rest", 0, 600, False)):
            if op.get(key) is not None:
                a += [flag, str(_num(op[key], key, lo, hi, whole))]
        for knob, c in (op.get("controls") or {}).items():
            if c not in CONTROLS:
                raise ValueError(f"{knob}: control must be free, ask or fixed")
            a += ["--control", f"{_slug(knob, 'setting')}={c}"]
        words = op.get("start_words")
        if words:
            if not isinstance(words, list):
                raise ValueError("start words must be a list")
            a += ["--start-words", *[_text(w, "start phrase") for w in words]]
        if len(a) == 2:
            raise ValueError("nothing to change")
        return a
    if kind in ("pin", "unpin", "limit", "unlimit", "undo", "unban", "forget"):
        a = [kind, _slug(op.get("goal"), "goal"), _slug(op.get("knob"), "setting")]
        if kind in ("pin", "unban"):
            a.append(_value(op.get("value")))
        elif kind == "limit":
            lo, hi = _num(op.get("lo"), "low limit"), _num(op.get("hi"), "high limit")
            a += [str(lo), str(hi)]
        return a + _scope_args(op)
    if kind == "verdict":
        v = op.get("verdict")
        if v not in ("right", "wrong"):
            raise ValueError("verdict must be right or wrong")
        a = ["verdict", _slug(op.get("goal"), "goal"), str(_num(op.get("number"), "attempt number", 1, 100000, True)), v]
        if op.get("note"):
            a += ["--note", _text(op["note"], "note")]
        return a + _scope_args(op)
    if kind in ("confirm", "cancel"):
        return [kind, _slug(op.get("goal"), "goal"), _slug(op.get("knob"), "setting")]
    if kind == "priority":
        order = op.get("order")
        if not isinstance(order, list) or not order:
            raise ValueError("the order must be a list of goals")
        return ["priority", *[_slug(x, "goal") for x in order]]
    if kind == "reset":
        return ["reset", _slug(op.get("goal"), "goal"), "--yes"]
    if kind == "lesson_add":
        return ["lesson", "add", _text(op.get("text"), "lesson")]
    if kind == "lesson_edit":
        return ["lesson", "edit", str(_num(op.get("id"), "lesson id", 1, 10**9, True)), _text(op.get("text"), "lesson")]
    if kind == "lesson_delete":
        return ["lesson", "delete", str(_num(op.get("id"), "lesson id", 1, 10**9, True))]
    raise ValueError(f"unknown edit {kind!r}")


def describe(op: dict) -> str:
    """One plain sentence for the tab."""
    k, g = op.get("op"), op.get("goal")
    sc = "" if not op.get("scope") or op.get("scope") == "all" else f" ({op['scope']})"
    if k == "set":
        parts = [f"{key.replace('_', ' ')} = {op[key]}" for key in ("title", "attempts", "minutes", "min_pack_pct", "target_successes", "rest_between_s") if op.get(key) is not None]
        parts += [f"{n}: {c}" for n, c in (op.get("controls") or {}).items()]
        if op.get("start_words"):
            parts.append("start phrases: " + ", ".join(op["start_words"]))
        return f"{g}: change " + "; ".join(parts)
    if k == "pin":
        return f"{g}: pin {op.get('knob')} = {op.get('value')}{sc}"
    if k == "limit":
        return f"{g}: limit {op.get('knob')} to {op.get('lo')} .. {op.get('hi')}{sc}"
    if k in ("unpin", "unlimit", "undo", "forget"):
        return f"{g}: {k} {op.get('knob')}{sc}"
    if k == "unban":
        return f"{g}: allow {op.get('knob')} = {op.get('value')} again{sc}"
    if k == "verdict":
        return f"{g}: attempt #{op.get('number')} was scored {'right' if op.get('verdict') == 'right' else 'wrong'}"
    if k in ("confirm", "cancel"):
        return f"{g}: {k} the suggestion for {op.get('knob')}"
    if k == "priority":
        return "goal order: " + " > ".join(op.get("order") or [])
    if k == "reset":
        return f"{g}: forget everything it learned (the journal is kept)"
    if k == "lesson_add":
        return f"add lesson: {op.get('text')}"
    if k == "lesson_edit":
        return f"rewrite lesson #{op.get('id')}: {op.get('text')}"
    if k == "lesson_delete":
        return f"delete lesson #{op.get('id')}"
    return str(op)


def _key(op: dict):
    """Edits with the same key replace each other (the newest wins), so a pin followed by an unpin leaves the unpin only."""
    k, g = op.get("op"), op.get("goal")
    if k in ("pin", "unpin"):
        return ("pin", g, op.get("knob"), op.get("scope") or "all")
    if k in ("limit", "unlimit"):
        return ("limit", g, op.get("knob"), op.get("scope") or "all")
    if k == "verdict":
        return ("verdict", g, op.get("number"), op.get("scope") or "all")
    if k == "priority":
        return ("priority",)
    if k in ("confirm", "cancel"):
        return ("suggestion", g, op.get("knob"))
    if k in ("lesson_edit", "lesson_delete"):
        return ("lesson", op.get("id"))
    return None


def _path(d: str | None, name: str) -> str:
    return os.path.join(folder(d), name)


def pending(d: str | None = None) -> list[dict]:
    try:
        rows = json.load(open(_path(d, "pending_edits.json")))
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError):
        return []


def _save(rows: list[dict], d: str | None) -> None:
    p = _path(d, "pending_edits.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        f.write(json.dumps(rows, indent=1) + "\n")
    os.replace(tmp, p)


def add(op: dict, d: str | None = None) -> dict:
    """Queue one edit (checked now, so the tab can say what is wrong at once). A newer edit of the same thing replaces the older one; two `set`s of one goal are merged."""
    argv_for(op)
    op = {k: v for k, v in op.items() if k not in ("id", "added", "error")}
    rows = pending(d)
    key = _key(op)
    if key is not None:
        rows = [r for r in rows if _key(r) != key]
    if op.get("op") == "set":
        for r in rows:
            if r.get("op") == "set" and r.get("goal") == op.get("goal"):
                rows.remove(r)
                merged = {**r, **{k: v for k, v in op.items() if k != "controls"}}
                merged["controls"] = {**(r.get("controls") or {}), **(op.get("controls") or {})}
                op = {k: v for k, v in merged.items() if k not in ("id", "added", "error")}
                break
    op["id"] = uuid.uuid4().hex[:8]
    op["added"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rows.append(op)
    _save(rows, d)
    return op


def cancel(edit_id: str, d: str | None = None) -> bool:
    rows = pending(d)
    left = [r for r in rows if r.get("id") != edit_id]
    if len(left) == len(rows):
        return False
    _save(left, d)
    return True


def with_text(rows: list[dict]) -> list[dict]:
    return [{**r, "text": describe(r)} for r in rows]


def history(d: str | None = None, n: int = 30) -> list[dict]:
    out = []
    try:
        for ln in open(_path(d, "applied_edits.jsonl")):
            if ln.strip():
                out.append(json.loads(ln))
    except (OSError, ValueError):
        pass
    return out[-n:][::-1]


def _log(row: dict, d: str | None) -> None:
    with open(_path(d, "applied_edits.jsonl"), "a") as f:
        f.write(json.dumps(row) + "\n")


def _ssh(host: str, remote: str, timeout: int = 40) -> tuple[int, str]:
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", host, remote], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


GOALS_CMD = "cd ~/bittleX && PYTHONPATH=. pi_pipeline/.venv/bin/python -m pi_pipeline.goals "
SESSION_RUNNING = "pgrep -f '[p]i_pipeline.goals run' >/dev/null && echo running || echo idle"


def apply(d: str | None = None, host: str | None = None, run=_ssh) -> dict:
    """Run every queued edit on the Pi, oldest first. {"applied": n, "failed": n, "left": n, "message": text}. Nothing is run when the Pi cannot be reached or a goal session is running."""
    rows = pending(d)
    if not rows:
        return {"applied": 0, "failed": 0, "left": 0, "message": "nothing waiting"}
    host = host or os.environ.get("G2_PI", "")
    if not host:
        return {"applied": 0, "failed": 0, "left": len(rows), "message": "G2_PI is not set: the edits stay queued"}
    try:
        code, out = run(host, SESSION_RUNNING)
    except (OSError, subprocess.TimeoutExpired):
        code, out = 255, ""
    if code != 0:
        return {"applied": 0, "failed": 0, "left": len(rows), "message": "G2 is offline: the edits stay queued and apply on the next sync"}
    if out.strip().endswith("running"):
        return {"applied": 0, "failed": 0, "left": len(rows), "message": "a goal session is running: the edits stay queued until it ends"}
    done, failed, keep = 0, 0, []
    for i, r in enumerate(rows):
        try:
            argv = argv_for(r)
            code, out = run(host, GOALS_CMD + " ".join(shlex.quote(x) for x in argv))
        except ValueError as e:
            code, out = 2, str(e)
        except (OSError, subprocess.TimeoutExpired) as e:
            keep.extend(rows[i:])                                         # this one and the rest stay queued
            _save(keep, d)
            return {"applied": done, "failed": failed, "left": len(keep), "message": f"lost the Pi part way ({e}): the rest stay queued"}
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        if code == 0:
            done += 1
            _log({"time": stamp, "ok": True, "edit": {k: v for k, v in r.items() if k != "error"}, "text": describe(r), "answer": out[-400:]}, d)
        else:
            failed += 1
            keep.append({**r, "error": (out or f"exit {code}")[-300:]})
    _save(keep, d)
    for r in keep:
        _log({"time": time.strftime("%Y-%m-%d %H:%M:%S"), "ok": False, "edit": r, "text": describe(r), "answer": r["error"]}, d)
    msg = f"applied {done}" + (f", {failed} failed (they stay queued with the reason)" if failed else "")
    return {"applied": done, "failed": failed, "left": len(keep), "message": msg}


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        rows = pending()
        print("\n".join(f"{r['id']}  {describe(r)}" + (f"   ERROR: {r['error']}" if r.get("error") else "") for r in rows) or "no edits waiting")
    elif cmd == "apply":
        res = apply()
        if res["applied"] or res["failed"] or res["left"]:
            print("goal edits:", res["message"])
    elif cmd == "cancel" and len(argv) > 1:
        print("cancelled" if cancel(argv[1]) else "no such edit")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
