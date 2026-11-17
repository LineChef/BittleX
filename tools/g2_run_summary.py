#!/usr/bin/env python3
"""Summarize the goal runs on G2's Pi: sessions, attempts, the active look's numbers, and the newest fall (read-only; moves nothing).

    python tools/g2_run_summary.py [--since "2026-11-16 17:30"] [--last N] [--falls]

Reads the Pi's goal journal over ssh (needs G2_PI) and prints, for every session ended since `--since` (default: the last `--last` sessions, 1):
  * the session line: why it ended, attempts, successes, minutes
  * each attempt: time, outcome code, pack percent, the scorer's sentence
  * for an attempt with an active look: watch result, where the reading came from, good pictures, claw moves, stream sightings, whether "Got it." was said, and the per-picture log summary
    (pictures seen with the ball, bad ones, the brightness range, the biggest green blob in missed pictures)
  * with `--falls` (default on): the newest fall record (peak tilt, the roll and pitch in the seconds before, the last commands) and the goal / chase log lines around it.
Made from the snippets typed by hand in the 2026-11-15 and 11-16 hardware sessions. The logic is in pure functions (`summarize`, `format_watch`) so it is tested without a Pi.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

JOURNAL = "~/.local/share/g2/goal_journal.jsonl"
FALL_DIR = "~/.local/share/g2/falls"


def parse_journal(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def pick_sessions(rows: list[dict], since: str | None, last: int) -> list[dict]:
    ends = [r for r in rows if r.get("kind") == "session_end"]
    if since:
        return [e for e in ends if e.get("time", "") >= since]
    return ends[-last:] if last > 0 else []


def format_watch(w: dict) -> str:
    """One line for an attempt's active look, from its `after_punt` trace entry."""
    parts = [f"watch={w.get('watch')}", f"source={w.get('source') or '-'}", f"got_it={w.get('got_it')}", f"good={w.get('good_pictures')}", f"moves={w.get('claw_moves')}", f"sights={w.get('stream_sightings')}"]
    fr = w.get("frames") or []
    if fr:
        seen = sum(1 for f in fr if f.get("d"))
        bad = sum(1 for f in fr if f.get("bad"))
        means = [f["mean"] for f in fr if f.get("mean") is not None]
        blobs = [f["blob"] for f in fr if f.get("blob")][:3]
        parts.append(f"frames={len(fr)} seen={seen} bad={bad}" + (f" brightness={min(means)}..{max(means)}" if means else "") + (f" missed-blobs={blobs}" if blobs else ""))
    if w.get("still_diag"):
        parts.append(f"still_diag={w['still_diag']}")
    return "    " + " ".join(parts)


def summarize(rows: list[dict], sessions: list[dict]) -> list[str]:
    out = []
    ids = {s["session"] for s in sessions}
    for s in sessions:
        out.append(f"session {s['session']}: {s.get('why')}, {s.get('attempts')} attempts, {s.get('successes')} successes, {s.get('minutes')} min")
    for a in [r for r in rows if r.get("kind") == "attempt" and r.get("session") in ids]:
        o = a.get("outcome", {})
        out.append(f"{a.get('number')} {str(a.get('time', ''))[11:16]} {o.get('code')} pack={a.get('pack_pct')} | {str(o.get('text', ''))[:78]}")
        for w in (e for e in a.get("trace") or [] if e.get("kind") == "after_punt" and e.get("watch")):
            out.append(format_watch(w))
    if not sessions:
        out.append("no session ended in that range")
    return out


def summarize_fall(fall: dict | None) -> list[str]:
    if not fall:
        return ["no fall record"]
    s = fall.get("summary", {})
    out = [f"fall {fall.get('when')}: last command {fall.get('context', {}).get('last_motion_command')}, peak tilt {s.get('peak_tilt_deg')}, first over 20 deg at {s.get('first_over_20_s')} s"]
    tr = fall.get("trace") or []
    out.append("  roll/pitch before it: " + " ".join(f"{r[0]:.1f}:{r[1]:.0f}/{r[2]:.0f}" for r in tr if -5 <= r[0] <= 0.5)[:360])
    out.append("  last commands: " + ", ".join(f"{c['t'][11:]} {c['cmd'][:8]}" for c in (fall.get("commands") or [])[-8:]))
    return out


def _ssh(cmd: str, timeout: int = 60) -> str | None:
    """The command's output, or None when the Pi did not answer (ssh failed): never an empty answer that reads as "nothing happened"."""
    pi = os.environ.get("G2_PI")
    if not pi:
        sys.exit("set G2_PI to user@host of the Pi")
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", pi, cmd], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    return None if r.returncode == 255 else r.stdout


def main() -> None:
    ap = argparse.ArgumentParser(description="Summarize G2's goal runs from the Pi's journal (read-only).")
    ap.add_argument("--since", default=None, help='only sessions ended at or after this time, e.g. "2026-11-16 17:30"')
    ap.add_argument("--last", type=int, default=1, help="how many of the latest sessions when --since is not given")
    ap.add_argument("--no-falls", action="store_true")
    args = ap.parse_args()
    text = _ssh(f"tail -n 6000 {JOURNAL}")
    if text is None:
        print("could not verify: the Pi did not answer (it may be off, or the Mac may lack Local Network permission)")
        sys.exit(3)
    rows = parse_journal(text)
    print("\n".join(summarize(rows, pick_sessions(rows, args.since, args.last))))
    if not args.no_falls:
        newest = (_ssh(f"ls -t {FALL_DIR}/*.json 2>/dev/null | head -1") or "").strip()
        fall = None
        if newest:
            try:
                fall = json.loads(_ssh(f"cat {newest}") or "")
            except ValueError:
                fall = None
        print("\n".join(summarize_fall(fall)))


if __name__ == "__main__":
    main()
