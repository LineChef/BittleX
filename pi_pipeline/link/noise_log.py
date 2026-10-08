"""A record of every command that makes the BiBoard make a noise (2026-10-07: the behaviour chirps had never been heard on G2, and nothing said whether they were sent).

`record(command, source)` is called by `SerialLink.send` for every command it writes; a command that makes a noise is logged at INFO ("BiBoard noise: ...") and appended as a JSON line to
`~/.local/share/g2/noise.jsonl` (override with G2_NOISE_LOG; `G2_NOISE_LOG=off` turns the file off). Read it with:

    python -m pi_pipeline.link.noise_log [N]       # the last N noises (default 30) and a count per kind and source

Noisy commands: `b<note> <duration> ...` (buzzer melodies: chirps, cues, shutter clicks), `X...` (the voice module's commands, which can play its sounds). The board's OWN sounds (its start-up melody, a
low-battery alarm, the voice module answering on its own) are not commands and cannot be seen from here; lines the board sends back unprompted are logged by `record_board_line`.
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

log = logging.getLogger("g2.noise")

_BEEP = re.compile(r"^b-?\d")
_lock = threading.Lock()


def classify(command: str) -> str | None:
    """'beep' for a buzzer melody, 'voice-module' for an X... command, None for everything quiet."""
    c = (command or "").strip()
    if _BEEP.match(c):
        return "beep"
    if c[:1] == "X" and len(c) > 1:
        return "voice-module"
    return None


def _path() -> Path | None:
    v = os.environ.get("G2_NOISE_LOG", "")
    if v.lower() == "off":
        return None
    return Path(v) if v else Path.home() / ".local" / "share" / "g2" / "noise.jsonl"


def _caller() -> str:
    """The first calling frame outside the link package: 'module.function'."""
    f = sys._getframe(2)
    while f is not None:
        mod = f.f_globals.get("__name__", "")
        if not mod.startswith("pi_pipeline.link"):
            return f"{mod.replace('pi_pipeline.', '')}.{f.f_code.co_name}"
        f = f.f_back
    return "?"


def _is_stream(command: str) -> bool:
    """The joint / head streams (`i8 36 12 ...`, `m0 10`): sent many times a second, never a noise."""
    c = command.lstrip()
    return c[:1] in ("i", "m") and (len(c) == 1 or c[1].isdigit() or c[1] == " ")


def record(command: str, source: str | None = None, *, sent: bool = True) -> None:
    kind = classify(command)
    if kind is None:
        # G2_NOISE_LOG_ALL=1: also write the quiet commands (not the joint / head streams `i ...` and `m...`) so a sound the board makes on its own can be matched to what was sent just before it
        if os.environ.get("G2_NOISE_LOG_ALL") == "1" and command.strip() and not _is_stream(command):
            _append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": "quiet", "command": command.strip(), "source": source or _caller(), "sent": sent})
        return
    source = source or _caller()
    log.info("BiBoard noise: %s %r from %s%s", kind, command.strip(), source, "" if sent else " (NOT sent)")
    _append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, "command": command.strip(), "source": source, "sent": sent})


def _append(row: dict) -> None:
    p = _path()
    if p is None:
        return
    try:
        with _lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a") as f:
                f.write(json.dumps(row) + "\n")
    except OSError:
        log.debug("noise log not written", exc_info=True)


def record_board_line(line: str) -> None:
    """A line the board sent on its own (not a reply to a command): it may announce a sound (a low-battery alarm, a start-up banner)."""
    line = (line or "").strip()
    if line and not re.match(r"^[-\d.,\s]+$", line):           # IMU-style numeric lines are not news
        log.info("BiBoard said: %r", line[:120])


def main(argv=None) -> int:
    n = int((argv or sys.argv[1:] or ["30"])[0])
    p = _path()
    if p is None or not p.exists():
        print("no noise log yet")
        return 0
    rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
    print(f"{len(rows)} noises logged in {p}")
    from collections import Counter
    print("by kind:", dict(Counter(r["kind"] for r in rows)))
    print("by source:", dict(Counter(r["source"] for r in rows).most_common(8)))
    for r in rows[-n:]:
        print(f"{r['t']}  {r['kind']:12s} {r['command']:28s} {r['source']}{'' if r['sent'] else '  (NOT sent)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
