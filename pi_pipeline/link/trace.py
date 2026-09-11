"""Serial command trace + replay -- "what did we send the BiBoard, and when."

`TracingLink` wraps any link with a `send()` (a `SerialLink`, the app's
`LockedLink`, or a mock) and appends every outbound command to a timestamped
JSONL file, one line per send: `{"t": <seconds since trace start>, "cmd": ...,
"reply": ...}`. Everything else (`connect` / `read_line` / `close` /
`is_connected`) passes straight through -- this is a logging shim, not a new
link implementation.

    python -m pi_pipeline.app --trace ~/g2_trace.jsonl --serial   # capture
    python -m pi_pipeline.link.trace replay ~/g2_trace.jsonl --dry-run
    python -m pi_pipeline.link.trace replay ~/g2_trace.jsonl --serial

"It did something weird -- what did we actually send it?" becomes a file to
read instead of a memory to trust. Replay reproduces the same commands with
the same relative pacing (scaled by `--speed`), so a bug that only shows up
after a particular sequence can be reproduced without re-driving the robot by
hand.
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger("g2.link.trace")


class TracingLink:
    def __init__(self, link, path: str, *, clock=time.monotonic):
        self._link = link
        self._path = path
        self._clock = clock
        self._t0 = clock()
        self._fp = open(path, "a", buffering=1)   # line-buffered: nothing lost on a crash

    def send(self, command: str, **kw) -> str:
        reply = self._link.send(command, **kw)
        self._fp.write(json.dumps({
            "t": round(self._clock() - self._t0, 4),
            "cmd": command,
            "reply": reply,
        }) + "\n")
        return reply

    def read_line(self) -> str:
        return self._link.read_line()

    def connect(self) -> bool:
        return self._link.connect()

    @property
    def is_connected(self) -> bool:
        return getattr(self._link, "is_connected", False)

    def close(self) -> None:
        try:
            self._fp.close()
        except OSError:
            pass
        self._link.close()


def load_trace(path: str) -> list:
    """Parse a trace file into a list of {"t", "cmd", "reply"} dicts, oldest first."""
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def replay(path: str, link=None, *, speed: float = 1.0, dry_run: bool = False) -> int:
    """Re-send a trace's commands through `link`, in order, with the same
    relative pacing (scaled by `speed`). `dry_run` (or `link=None`) just prints
    what would happen -- no link needed. Returns the number of commands sent."""
    entries = load_trace(path)
    prev_t = 0.0
    n = 0
    for e in entries:
        gap = max(0.0, (e["t"] - prev_t) / max(speed, 1e-6))
        prev_t = e["t"]
        if gap and not dry_run:
            time.sleep(gap)
        print(f"  t={e['t']:8.3f}s  {'(dry) ' if dry_run else ''}-> {e['cmd']!r}")
        if not dry_run and link is not None:
            link.send(e["cmd"], read_reply=False)
        n += 1
    return n


def main() -> None:
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(name)s %(message)s")
    ap = argparse.ArgumentParser(prog="pi_pipeline.link.trace")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay")
    rp.add_argument("path")
    rp.add_argument("--speed", type=float, default=1.0, help="1.0 = original pacing")
    rp.add_argument("--dry-run", action="store_true", help="print only, send nothing")
    rp.add_argument("--serial", action="store_true", help="actually send over the configured port")
    args = ap.parse_args()

    if args.cmd == "replay":
        link = None
        if args.serial and not args.dry_run:
            from ..config import settings
            from .serial_link import SerialLink
            link = SerialLink(settings.serial_port, settings.serial_baud)
            if not link.connect():
                raise SystemExit(f"could not open {settings.serial_port}")
        n = replay(args.path, link, speed=args.speed, dry_run=args.dry_run or link is None)
        if link is not None:
            link.close()
        print(f"\n{n} command(s) replayed" + (" (dry run)" if args.dry_run or link is None else ""))


if __name__ == "__main__":
    main()
