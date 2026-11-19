#!/usr/bin/env python3
"""One printout after a fall (read-only; moves nothing, needs G2_PI): the newest fall record, the lie-down and sag events around it, the board's own moves, and a class for the fall.

    python tools/g2_fall_report.py [--window 120]

The `fall-analysis` skill's steps 1 and 2 in one command: the newest fall record on the Pi (peak tilt, the roll and pitch in the seconds before, the last commands), the lie-down log
(`liedown_events.jsonl`: the tilt before and 1 s and 3 s after every `krest`, and whether it flipped), the sag log (`sag_events.jsonl`) for the `--window` seconds before the fall, and the
"BiBoard started a move" lines in the voice service's journal. The class is a rule-based first guess ("flipped in a lie-down", "board-initiated", "rolled before the move", "transition",
"mid-move with a clean tilt before"); the skill still asks the user for his posture and the Pi-to-BiBoard plug, and a guard that should have fired is read from the log by a person.
If the Pi does not answer it says "could not verify" and exits 3. The logic is in pure functions (`classify`, `report`) so it is tested without a Pi."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import g2_run_summary as rs  # noqa: E402

DIR = "~/.local/share/g2"
TRANSITION_COMMANDS = ("krest", "kcalib", "ksit", "d", "kzz")
ROLLED_MIN_DEG, ROLLED_MAX_DEG, ROLLED_SPREAD_DEG = 16.0, 25.0, 6.0      # the steady roll seen before the day's falls (docs/STATUS.md limitation 19)


def _when(text) -> float | None:
    try:
        return time.mktime(time.strptime(str(text)[:19], "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None


def parse_lines(text: str | None) -> list[dict]:
    """The JSON lines of a log file's text; junk lines are skipped."""
    out = []
    for ln in (text or "").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def near(rows: list[dict], t_fall: float | None, window_s: float) -> list[dict]:
    """The rows whose "at" lies within `window_s` before the fall (or up to 15 s after it)."""
    if t_fall is None:
        return rows[-5:]
    return [r for r in rows if (t := _when(r.get("at"))) is not None and -15.0 <= t_fall - t <= window_s]


def tilt_before(fall: dict) -> tuple | None:
    """(median roll, spread of the roll) of the record's frames from 6 s to 1 s before the trigger, or None."""
    roll = [r[1] for r in fall.get("trace") or [] if -6.0 <= r[0] <= -1.0]
    if len(roll) < 3:
        return None
    return statistics.median(roll), max(roll) - min(roll)


def classify(fall: dict | None, liedowns: list[dict], board_lines: list[str]) -> tuple[str, str]:
    """(class, why) for the fall, by the rules in the `fall-analysis` skill. `liedowns` are the lie-down events near the fall."""
    if not fall:
        return "unknown", "no fall record"
    if any(e.get("flipped") for e in liedowns):
        e = next(e for e in liedowns if e.get("flipped"))
        return "flipped in a lie-down", f"the lie-down at {e.get('at')} ({e.get('why')}) went to {e.get('peak_deg')} deg; the tilt before it was {e.get('before')}"
    if board_lines:
        return "board-initiated", f"{len(board_lines)} 'BiBoard started a move' line(s) in the journal in the last half hour (its voice module, a TV)"
    last = (fall.get("context") or {}).get("last_motion_command") or ""
    tb = tilt_before(fall)
    if tb and ROLLED_MIN_DEG <= abs(tb[0]) <= ROLLED_MAX_DEG and tb[1] <= ROLLED_SPREAD_DEG:
        return "rolled before the move", f"the roll sat near {tb[0]:+.0f} deg (spread {tb[1]:.1f}) for seconds before the trigger: was the move gate supposed to run?"
    if last in TRANSITION_COMMANDS:
        return "transition", f"the last motion command was {last} (a lie-down, the attention pose or a sit)"
    if tb is not None and abs(tb[0]) < 10.0:
        return "mid-move with a clean tilt before", f"the roll was {tb[0]:+.0f} deg before it; the last command {last or 'unknown'}"
    return "unclear", f"last command {last or 'unknown'}; tilt before {None if tb is None else round(tb[0], 1)}"


def _fmt_event(e: dict, kind: str) -> str:
    if kind == "liedown":
        after = " ".join(f"{k}:{v}" for k, v in (e.get("after") or {}).items())
        return f"  lie-down {str(e.get('at'))[11:]} ({e.get('why')}): before {e.get('before')}, after {after}, peak {e.get('peak_deg')}{' FLIPPED' if e.get('flipped') else ''}, pack {e.get('pack_v')}"
    return (f"  sag {str(e.get('at'))[11:]}: pitch {e.get('pitch')} roll {e.get('roll')}, {e.get('since_stand_s')} s since the stand-up, last move {e.get('last_move')}, "
            f"pack {e.get('pack_live_v') or e.get('pack_v')}")


def report(fall: dict | None, liedowns: list[dict], sags: list[dict], board_lines: list[str]) -> list[str]:
    """The printout, as lines."""
    out = rs.summarize_fall(fall)
    t_fall = _when((fall or {}).get("when"))
    out += ["lie-downs around it:" if liedowns else "no lie-down events near it (the lie-down log may be off, or the Pi runs older code)"]
    out += [_fmt_event(e, "liedown") for e in liedowns]
    out += ["sags before it:" if sags else "no sag events before it"]
    out += [_fmt_event(e, "sag") for e in sags]
    if board_lines:
        out += ["the board started moves of its own:"] + [f"  {ln[:160]}" for ln in board_lines[-5:]]
    klass, why = classify(fall, liedowns, board_lines)
    out += [f"class: {klass}: {why}", "next: ask the user for his posture and the Pi-to-BiBoard plug; was a guard supposed to fire (move gate, sag check)? Did the session stop? (fall-analysis steps 2 and 3)"]
    if t_fall is None and fall:
        out.append("(the fall record has no readable time, so the lie-down and sag events shown are only the newest)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="One printout after a fall (read-only).")
    ap.add_argument("--window", type=float, default=120.0, help="seconds before the fall to look for sag events")
    args = ap.parse_args()
    newest = rs._ssh(f"ls -t {rs.FALL_DIR}/*.json 2>/dev/null | head -1")
    if newest is None:
        print("could not verify: the Pi did not answer (it may be off, or the Mac may lack Local Network permission)")
        sys.exit(3)
    newest = newest.strip()
    fall = None
    if newest:
        try:
            fall = json.loads(rs._ssh(f"cat {newest}") or "")
        except ValueError:
            fall = None
    t_fall = _when((fall or {}).get("when"))
    liedowns = near(parse_lines(rs._ssh(f"tail -n 60 {DIR}/liedown_events.jsonl 2>/dev/null")), t_fall, args.window)
    sags = near(parse_lines(rs._ssh(f"tail -n 60 {DIR}/sag_events.jsonl 2>/dev/null")), t_fall, args.window)
    board = (rs._ssh("journalctl -u g2-voice --since '30 minutes ago' --no-pager 2>/dev/null | grep -E 'BiBoard started a move' | cut -c1-200 | tail -n 5") or "").splitlines()
    print("\n".join(report(fall, liedowns, sags, board)))


if __name__ == "__main__":
    main()
