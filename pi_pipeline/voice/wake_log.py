"""Wake-word trigger log: every trigger and what followed it, for counting false triggers (owner, 2026-10-18).

On 2026-10-18 four of seven wake triggers were people talking nearby; each sent junk to Claude. The journal keeps only the current boot, so this file
keeps the history: one line per trigger (phrase, what Kaldi heard, loudness, word confidence, seconds since G2 last made a sound, and whether the
confidence gate ignored it) and one per outcome (what was heard after it, how many words, and what became of it: a local command, a request for
Claude, ignored as talk meant for someone else, or nothing). Local only, on the Pi; never sent anywhere.

    ~/.local/share/g2/wake_triggers.jsonl          (`G2_WAKE_LOG`, `off` turns it off)
    python -m pi_pipeline.voice.wake_log [--days 7]  # how many triggers, how many look false, and the confidence of each kind

A trigger "looks false" when nothing was heard after it, it was ignored as talk for someone else, or Claude got two words or fewer that were not a
command. It is a heuristic for choosing `G2_WAKE_MIN_CONF`, not a verdict.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("g2.wake_log")

DEFAULT_PATH = "~/.local/share/g2/wake_triggers.jsonl"
MAX_BYTES = 2_000_000


def _path() -> Path | None:
    v = os.environ.get("G2_WAKE_LOG", DEFAULT_PATH).strip()
    if v.lower() in ("", "off", "0", "false", "no"):
        return None
    return Path(os.path.expanduser(v))


def _append(row: dict) -> None:
    p = _path()
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > MAX_BYTES:            # keep the newer half
            lines = p.read_text().splitlines()
            p.write_text("\n".join(lines[len(lines) // 2:]) + "\n")
        with p.open("a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        log.debug("wake log write failed", exc_info=True)


def record_trigger(phrase: str, text: str, *, level: float | None, confidence: float | None, since_own_sound_s: float | None, ignored: bool = False) -> None:
    _append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "type": "trigger", "phrase": phrase, "text": text,
             "level": None if level is None else round(float(level)), "confidence": None if confidence is None else round(float(confidence), 3),
             "since_own_sound_s": None if since_own_sound_s is None or since_own_sound_s < 0 else round(float(since_own_sound_s), 1), "ignored": bool(ignored)})


def record_outcome(heard: str, result: str, *, mic_peak=None) -> None:
    """`result`: "command" (a local command), "request" (went to Claude), "ignored" (talk meant for someone else), "empty" (nothing heard)."""
    _append({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "type": "outcome", "heard": heard, "words": len((heard or "").split()), "result": result, "mic_peak": mic_peak})


def looks_false(outcome: dict) -> bool:
    r = outcome.get("result")
    return r in ("empty", "ignored") or (r == "request" and outcome.get("words", 0) <= 2)


def read(days: float = 7.0, path: Path | None = None) -> list[dict]:
    p = path or _path()
    if p is None or not p.exists():
        return []
    cutoff = time.time() - days * 86400.0
    out = []
    for line in p.read_text().splitlines():
        try:
            row = json.loads(line)
            if time.mktime(time.strptime(row["t"], "%Y-%m-%dT%H:%M:%S")) >= cutoff:
                out.append(row)
        except (ValueError, KeyError):
            continue
    return out


def pairs(rows: list[dict]) -> list[tuple[dict, dict | None]]:
    """Each trigger that woke G2 with the outcome line that followed it (None if the next line was another trigger)."""
    out, pending = [], None
    for row in rows:
        if row.get("type") == "trigger":
            if pending is not None:
                out.append((pending, None))
            pending = None if row.get("ignored") else row
        elif row.get("type") == "outcome" and pending is not None:
            out.append((pending, row))
            pending = None
    if pending is not None:
        out.append((pending, None))
    return out


def summary(days: float = 7.0, path: Path | None = None) -> str:
    rows = read(days, path)
    triggers = [r for r in rows if r.get("type") == "trigger"]
    if not triggers:
        return f"no wake triggers logged in the last {days:g} days"
    gated = sum(1 for r in triggers if r.get("ignored"))
    ps = pairs(rows)
    false = [(t, o) for t, o in ps if o is not None and looks_false(o)]
    real = [(t, o) for t, o in ps if o is not None and not looks_false(o)]

    def conf(group):
        c = sorted(t["confidence"] for t, _o in group if t.get("confidence") is not None)
        return "none logged" if not c else f"min {c[0]:.2f}, median {c[len(c) // 2]:.2f}, max {c[-1]:.2f} ({len(c)})"
    lines = [f"wake triggers, last {days:g} days: {len(triggers)} ({gated} ignored by the confidence gate)",
             f"  woke him: {len(ps)}; looked real: {len(real)}; looked false: {len(false)}" + (f" ({100.0 * len(false) / max(1, len(real) + len(false)):.0f}%)" if real or false else ""),
             f"  confidence when real:  {conf(real)}",
             f"  confidence when false: {conf(false)}"]
    for t, o in false[-8:]:
        lines.append(f"    false? {t['t']}  {t['phrase']!r} conf {t.get('confidence')} level {t.get('level')}  then {o.get('result')}: {o.get('heard')!r}")
    return "\n".join(lines)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="pi_pipeline.voice.wake_log")
    ap.add_argument("--days", type=float, default=7.0)
    print(summary(ap.parse_args(argv).days))


if __name__ == "__main__":
    main()
