"""Debug logs keep a week, not forever (user, 2026-11-06). The command, noise, power, memory and wall logs are for finding out what went wrong; a week back is enough, and they were most of the Pi's stored data.

`trim_all()` drops the lines older than RETENTION_DAYS from each file; it runs when the voice service starts and once a day after. A line's time is its "t" field: "2026-11-05 14:00:00",
"2026-11-05T14:00:00" or seconds since 1970. Lines it cannot read stay. `G2_LOG_DAYS=0` turns it off. Never raises.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time

log = logging.getLogger("g2.log_retention")

RETENTION_DAYS = 7.0
FILES = ("~/.local/share/g2/command_log.jsonl", "~/.local/share/g2/noise.jsonl", "~/.local/share/g2/memory_log.jsonl", "~/.local/share/g2/power_log.jsonl", "~/.local/share/g2/wall_dryrun.jsonl")


def days() -> float:
    try:
        return float(os.environ.get("G2_LOG_DAYS", RETENTION_DAYS))
    except ValueError:
        return RETENTION_DAYS


def _stamp(v) -> float | None:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return time.mktime(time.strptime(v[:19], fmt))
            except ValueError:
                continue
    return None


def trim_file(path: str, keep_days: float, now: float | None = None) -> int:
    """Remove the lines older than `keep_days`; returns how many went."""
    p = os.path.expanduser(path)
    if not os.path.exists(p) or keep_days <= 0:
        return 0
    cutoff = (now or time.time()) - keep_days * 86400.0
    keep, gone = [], 0
    with open(p) as f:
        for ln in f:
            try:
                t = _stamp(json.loads(ln).get("t"))
            except (ValueError, AttributeError):
                t = None
            if t is not None and t < cutoff:
                gone += 1
            else:
                keep.append(ln)
    if gone:
        tmp = p + ".tmp"
        with open(tmp, "w") as f:
            f.writelines(keep)
        os.replace(tmp, p)
    return gone


def trim_all(now: float | None = None) -> int:
    d = days()
    n = 0
    for f in FILES:
        try:
            n += trim_file(f, d, now)
        except Exception:  # noqa: BLE001
            log.debug("trim failed for %s", f, exc_info=True)
    if n:
        log.info("log retention: %d old line(s) dropped (keeping %.0f days)", n, d)
    return n


def start_daily() -> threading.Thread | None:
    if days() <= 0:
        return None

    def loop():
        while True:
            trim_all()
            time.sleep(86400.0)
    t = threading.Thread(target=loop, name="log-retention", daemon=True)
    t.start()
    return t
