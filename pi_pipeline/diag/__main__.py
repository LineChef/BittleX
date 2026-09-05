"""Post-hoc diagnostics tooling.

    python -m pi_pipeline.diag list
    python -m pi_pipeline.diag summarize [SESSION]      # SESSION = id, dir, or omitted = latest
    python -m pi_pipeline.diag tail [SESSION]
    python -m pi_pipeline.diag replay SESSION [--around HH:MM:SS] [--window 5]
    python -m pi_pipeline.diag sync SESSION DEST
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .core import _LEVELS, _log_root


def _sessions() -> list[Path]:
    root = _log_root()
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and (p / "events.jsonl").exists()),
                  key=lambda p: p.stat().st_mtime)


def _resolve(session: str | None) -> Path:
    if not session:
        s = _sessions()
        if not s:
            sys.exit(f"no sessions under {_log_root()}")
        return s[-1]
    p = Path(session)
    if p.is_dir():
        return p
    cand = _log_root() / session
    if cand.is_dir():
        return cand
    sys.exit(f"session not found: {session}")


def _read_events(d: Path):
    with open(d / "events.jsonl") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    pass


def cmd_list(_):
    for d in _sessions():
        evs = list(_read_events(d))
        n_warn = sum(1 for e in evs if _LEVELS.get(e.get("lvl", "INFO"), 20) >= 30)
        bb = len(list(d.glob("blackbox_*.csv")))
        dur = (evs[-1]["mono_t"] - evs[0]["mono_t"]) if len(evs) > 1 else 0.0
        print(f"{d.name}   {len(evs):5d} events  {n_warn:3d} warn+  {bb} blackbox  {dur:6.0f}s")


def _thermal_summary(evs):
    warn = [e for e in evs if e.get("name") == "servo.thermal_warn"]
    soft = [e for e in evs if e.get("name") == "servo.soft_cutback"]
    cool = [e for e in evs if e.get("name") == "servo.thermal_cooldown"]
    rec = [e for e in evs if e.get("name") == "servo.thermal_recover"]
    peak = max((e.get("hottest_frac", 0.0) for e in evs if "hottest_frac" in e), default=0.0)
    if not (warn or soft or cool or peak):
        print("  thermal: nothing logged (guard off, or never warmed)")
        return
    print(f"  thermal: peak heat estimate {peak:.0%} of danger line")
    print(f"           WARN x{len(warn)}   soft-cutback x{len(soft)}   COOLDOWN x{len(cool)}   recover x{len(rec)}")
    joints = {}
    for e in evs:
        j = e.get("hottest_j")
        if j is not None:
            joints[j] = joints.get(j, 0) + 1
    if joints:
        hot = sorted(joints.items(), key=lambda kv: -kv[1])[:3]
        print("           hottest joint (ticks): " + ", ".join(f"j{j}:{n}" for j, n in hot))
    for e in cool:
        t = time.strftime("%H:%M:%S", time.localtime(e["wall_ts"]))
        print(f"           [{t}] COOLDOWN -- {e.get('reason', '')}")


def cmd_summarize(a):
    d = _resolve(a.session)
    evs = list(_read_events(d))
    man = json.loads((d / "manifest.json").read_text()) if (d / "manifest.json").exists() else {}
    print(f"session {d.name}")
    git = man.get("git", {})
    print(f"  git {str(git.get('sha'))[:12]}{' (dirty)' if git.get('dirty') else ''}   "
          f"host {man.get('host')}   argv {' '.join(man.get('argv', [])[:4])}")
    if man.get("policy", {}).get("path"):
        print(f"  policy {man['policy']['path']}  sha16 {man['policy'].get('sha256_16')}")
    if not evs:
        print("  (no events)"); return
    dur = evs[-1]["mono_t"] - evs[0]["mono_t"]
    by_lvl = {}
    for e in evs:
        by_lvl[e.get("lvl", "?")] = by_lvl.get(e.get("lvl", "?"), 0) + 1
    print(f"  {len(evs)} events over {dur:.0f}s   " + "  ".join(f"{k}:{v}" for k, v in sorted(by_lvl.items())))
    _thermal_summary(evs)
    print("  timeline (WARN and above):")
    for e in evs:
        if _LEVELS.get(e.get("lvl", "INFO"), 20) >= 30:
            t = time.strftime("%H:%M:%S", time.localtime(e["wall_ts"]))
            kv = " ".join(f"{k}={v}" for k, v in e.items()
                          if k not in ("wall_ts", "mono_t", "sid", "sub", "lvl", "name"))
            print(f"    [{t}] {e['lvl']:5} {e['sub']}/{e['name']}  {kv}")
    bb = sorted(d.glob("blackbox_*.csv"))
    if bb:
        print("  black-box dumps: " + ", ".join(p.name for p in bb))


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
    for name, fn in (("summarize", cmd_summarize), ("tail", cmd_tail)):
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
