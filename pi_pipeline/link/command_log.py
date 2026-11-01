"""Every command the Pi sends to the BiBoard, and every line the BiBoard sends back that nobody asked for (user, 2026-11-01: "so you will know when I used a voice command").

The BiBoard's own voice module ("sit", "stand up", "attention" said WITHOUT "G2") runs its command inside the firmware; the Pi never sends anything for it. What the Pi can see is what the
board prints on the serial line when it does it. So this log keeps two kinds of line, in `~/.local/share/g2/command_log.jsonl` (G2_COMMAND_LOG moves it, `off` turns it off):

  {"t": "...", "dir": "pi",    "cmd": "kbalance", "source": "behavior.ball_chase._skill", "origin": "voice-service" | "script" | <G2_ORIGIN>}
  {"t": "...", "dir": "board", "line": "...", "after_pi_s": 7.3, "unprompted": true}

A board line more than UNPROMPTED_S after the Pi's last command is marked `unprompted`: the board did something on its own, most likely one of your voice commands (or its own
start-up, a low-battery alarm). The joint streams (`i8 ...`, `m0 ...`, many a second while walking) are left out. `origin` is the G2_ORIGIN environment variable when set (an alias can
say `user`, a check run for you can say `assistant`), else `voice-service` inside the systemd service, else `script`.

Read it with:

    python -m pi_pipeline.link.command_log [--hours N] [--board] [--last N]      (g2cmds)

NOT yet checked on G2: what exactly the board prints for a voice command. Say a voice command to the board, then run `g2cmds --board`.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("g2.cmdlog")
UNPROMPTED_S = 1.5
MAX_BYTES = 4 * 1024 * 1024
_lock = threading.Lock()
_NUMERIC = re.compile(r"^[-\d.,\s\t]+$")


def path() -> Path | None:
    v = os.environ.get("G2_COMMAND_LOG", "")
    if v.lower() == "off":
        return None
    return Path(v) if v else Path.home() / ".local" / "share" / "g2" / "command_log.jsonl"


def origin() -> str:
    o = os.environ.get("G2_ORIGIN", "").strip()
    if o:
        return o
    return "voice-service" if os.environ.get("INVOCATION_ID") else "script"


def _caller() -> str:
    """The first calling frame outside the link package: 'module.function'."""
    f = sys._getframe(1)
    while f is not None:
        mod = f.f_globals.get("__name__", "")
        if not mod.startswith("pi_pipeline.link"):
            return f"{mod.replace('pi_pipeline.', '')}.{f.f_code.co_name}"
        f = f.f_back
    return "?"


def _is_stream(command: str) -> bool:
    c = command.lstrip()
    return c[:1] in ("i", "m") and (len(c) == 1 or c[1].isdigit() or c[1] == " ")


def _append(row: dict) -> None:
    p = path()
    if p is None:
        return
    try:
        with _lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            try:
                if p.stat().st_size > MAX_BYTES:                                  # keep the newest half
                    data = p.read_bytes()[-MAX_BYTES // 2:]
                    p.write_bytes(data[data.find(b"\n") + 1:])
            except OSError:
                pass
            with p.open("a") as f:
                f.write(json.dumps(row) + "\n")
    except OSError:
        log.debug("command log not written", exc_info=True)


def sent(command: str, source: str | None = None) -> None:
    """A command the Pi wrote to the board. Never raises."""
    c = (command or "").strip()
    if not c or _is_stream(c):
        return
    try:
        _append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "dir": "pi", "cmd": c[:80], "source": source or _caller(), "origin": origin()})
    except Exception:  # noqa: BLE001
        pass


def heard(line: str, after_pi_s: float | None) -> None:
    """A line the board sent that was not read as a reply (seen by `poll_imu`). Numeric lines (IMU-style, joint dumps) are left out. Never raises."""
    s = (line or "").strip()
    if not s or _NUMERIC.match(s):
        return
    try:
        unprompted = after_pi_s is None or after_pi_s > UNPROMPTED_S
        if unprompted:
            log.info("BiBoard did something on its own (%.0f s after the Pi's last command): %r", after_pi_s or -1, s[:120])
        _append({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "dir": "board", "line": s[:160], "after_pi_s": None if after_pi_s is None else round(after_pi_s, 1),
                 "unprompted": unprompted})
    except Exception:  # noqa: BLE001
        pass


def read(hours: float | None = None, p: Path | None = None) -> list[dict]:
    p = p or path()
    rows = []
    try:
        for ln in p.read_text().splitlines():
            try:
                rows.append(json.loads(ln))
            except ValueError:
                pass
    except (OSError, AttributeError):
        return []
    if hours is not None:
        cutoff = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - hours * 3600))
        rows = [r for r in rows if r.get("t", "") >= cutoff]
    return rows


def _clock(t: str) -> str:
    try:
        return time.strftime("%b %-d %-I:%M:%S %p", time.strptime(t, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return t


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="What the Pi sent to the BiBoard and what the board did on its own.")
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--board", action="store_true", help="only the board's own lines (your voice commands to it show here)")
    ap.add_argument("--last", type=int, default=60)
    a = ap.parse_args(argv)
    rows = read(a.hours)
    if a.board:
        rows = [r for r in rows if r.get("dir") == "board"]
    if not rows:
        print(f"nothing logged in the last {a.hours:g} h ({path()})")
        return 0
    for r in rows[-a.last:]:
        if r.get("dir") == "board":
            print(f"{_clock(r['t'])}  BOARD {'(on its own) ' if r.get('unprompted') else ''}{r.get('line')}")
        else:
            print(f"{_clock(r['t'])}  pi    {r.get('cmd'):24s} {r.get('origin')}: {r.get('source')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
