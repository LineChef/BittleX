"""Post-hoc diagnostics tooling.

    python -m pi_pipeline.diag list
    python -m pi_pipeline.diag summarize [SESSION]      # SESSION = id, dir, or omitted = latest
    python -m pi_pipeline.diag last-failure [SESSION]   # most recent failure-taxonomy event
    python -m pi_pipeline.diag tail [SESSION]
    python -m pi_pipeline.diag replay SESSION [--around HH:MM:SS] [--window 5]
    python -m pi_pipeline.diag sync SESSION DEST

`summarize`/`last-failure`'s actual logic lives in `core.py` as
`summarize_session()`/`last_failure()` (plain functions returning text) --
this CLI just resolves a session and prints. `voice/conversation.py`'s
`diagnostics_query` tool calls the same two functions directly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .core import _LEVELS, _log_root, _read_events, _resolve_session, _sessions
from .core import last_failure as _last_failure
from .core import summarize_session as _summarize_session


def _resolve(session: str | None) -> Path:
    d = _resolve_session(session)
    if d is None:
        sys.exit(f"no sessions under {_log_root()}" if not session else f"session not found: {session}")
    return d


def cmd_list(_):
    for d in _sessions():
        evs = list(_read_events(d))
        n_warn = sum(1 for e in evs if _LEVELS.get(e.get("lvl", "INFO"), 20) >= 30)
        bb = len(list(d.glob("blackbox_*.csv")))
        dur = (evs[-1]["mono_t"] - evs[0]["mono_t"]) if len(evs) > 1 else 0.0
        print(f"{d.name}   {len(evs):5d} events  {n_warn:3d} warn+  {bb} blackbox  {dur:6.0f}s")


def cmd_summarize(a):
    d = _resolve(a.session)  # validate + friendly exit before handing off
    print(_summarize_session(str(d)))


def cmd_last_failure(a):
    d = _resolve(a.session)
    print(_last_failure(str(d)))


def cmd_tail(a):
    d = _resolve(a.session)
    p = d / "events.jsonl"
    print(f"tailing {p}  (Ctrl-C to stop)")
    with open(p) as f:
        f.seek(0, os.SEEK_END)
        try:
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.2); continue
                try:
                    e = json.loads(line)
                    t = time.strftime("%H:%M:%S", time.localtime(e["wall_ts"]))
                    kv = " ".join(f"{k}={v}" for k, v in e.items()
                                  if k not in ("wall_ts", "mono_t", "sid", "sub", "lvl", "name"))
                    print(f"[{t}] {e['lvl']:5} {e['sub']}/{e['name']}  {kv}")
                except json.JSONDecodeError:
                    print(line.rstrip())
        except KeyboardInterrupt:
            pass


def cmd_replay(a):
    d = _resolve(a.session)
    bbs = sorted(d.glob("blackbox_*.csv"))
    if not bbs:
        sys.exit("no black-box dumps in this session")
    for p in bbs:
        print(f"=== {p.name} ===")
        lines = p.read_text().splitlines()
        print(lines[0])
        body = lines[1:]
        show = body if not a.window else body[: int(a.window * 80)]
        for ln in show[-2000:]:
            print(ln)


def cmd_sync(a):
    d = _resolve(a.session)
    import subprocess
    subprocess.run(["rsync", "-av", str(d) + "/", a.dest], check=False)


def main():
    ap = argparse.ArgumentParser(prog="python -m pi_pipeline.diag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    for name, fn in (("summarize", cmd_summarize), ("last-failure", cmd_last_failure), ("tail", cmd_tail)):
        sp = sub.add_parser(name); sp.add_argument("session", nargs="?"); sp.set_defaults(fn=fn)
    rp = sub.add_parser("replay"); rp.add_argument("session")
    rp.add_argument("--around"); rp.add_argument("--window", type=float, default=0.0)
    rp.set_defaults(fn=cmd_replay)
    yp = sub.add_parser("sync"); yp.add_argument("session"); yp.add_argument("dest")
    yp.set_defaults(fn=cmd_sync)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
