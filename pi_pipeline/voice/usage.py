"""Counts G2's Claude API use per day, and how much of it is the "words-only" retry, so retries can't quietly inflate the bill.

Each Claude call is recorded as a `turn` (the normal reply to the person), a `retry` (the automatic follow-up when a reply came back
with no speech) or a `consolidation` (the idle-time memory tidy-up), with the input/output tokens the API reported. Stored as small JSON, one bucket per day:
    ~/.local/share/g2/api_usage.json      (G2_USAGE_FILE)
Read it with:   python -m pi_pipeline.voice.usage [--days 7]
Set G2_PRICE_IN_PER_MTOK / G2_PRICE_OUT_PER_MTOK (dollars per million tokens) to also see an estimated cost."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("g2.usage")

_FIELDS = ("turns", "retries", "in_tokens", "out_tokens", "retry_in_tokens", "retry_out_tokens", "consolidations")


class UsageTracker:
    def __init__(self, path, *, today=lambda: time.strftime("%Y-%m-%d")):
        self.path = Path(path).expanduser()
        self._today = today
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            if isinstance(data, dict) and isinstance(data.get("days"), dict):
                return data
        except (OSError, ValueError):
            pass
        return {"days": {}}

    def record(self, kind: str, usage=None) -> None:
        """`kind` is "turn" or "retry"; `usage` is the API response's usage object (or None). Never raises."""
        try:
            tin = int(getattr(usage, "input_tokens", 0) or 0) + int(getattr(usage, "cache_read_input_tokens", 0) or 0) \
                + int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
            tout = int(getattr(usage, "output_tokens", 0) or 0)
            with self._lock:
                data = self._load()
                day = data["days"].setdefault(self._today(), {k: 0 for k in _FIELDS})
                for k in _FIELDS:
                    day.setdefault(k, 0)
                if kind == "retry":
                    day["retries"] += 1; day["retry_in_tokens"] += tin; day["retry_out_tokens"] += tout
                elif kind == "consolidation":
                    day["consolidations"] += 1                       # the memory tidy-up pass (its tokens are in the totals)
                else:
                    day["turns"] += 1
                day["in_tokens"] += tin; day["out_tokens"] += tout
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data))
                os.replace(tmp, self.path)
        except Exception:  # noqa: BLE001 -- counting must never break a conversation
            log.debug("usage record failed", exc_info=True)

    def days(self, n: int = 7) -> list[tuple[str, dict]]:
        items = sorted(self._load()["days"].items())
        return items[-n:]


def summarize(tracker: UsageTracker, days: int = 7, price_in: float = 0.0, price_out: float = 0.0) -> str:
    rows = tracker.days(days)
    if not rows:
        return "no API usage recorded yet"
    lines = ["day         turns retries  retry%   in-tok   out-tok  retry-tok(share)  consol" + ("   est.$" if price_in or price_out else "")]
    tot = {k: 0 for k in _FIELDS}
    for day, d in rows:
        calls = d.get("turns", 0) + d.get("retries", 0)
        rtok = d.get("retry_in_tokens", 0) + d.get("retry_out_tokens", 0)
        alltok = d.get("in_tokens", 0) + d.get("out_tokens", 0)
        cost = (d.get("in_tokens", 0) * price_in + d.get("out_tokens", 0) * price_out) / 1e6
        lines.append(f"{day}  {d.get('turns', 0):>5} {d.get('retries', 0):>7}  {100 * d.get('retries', 0) / max(1, calls):5.1f}%  "
                     f"{d.get('in_tokens', 0):>7} {d.get('out_tokens', 0):>8}  {rtok:>7} ({100 * rtok / max(1, alltok):4.1f}%)"
                     f"  {d.get('consolidations', 0):>6}" + (f"  {cost:6.3f}" if price_in or price_out else ""))
        for k in _FIELDS:
            tot[k] += d.get(k, 0)
    calls = tot["turns"] + tot["retries"]
    rtok = tot["retry_in_tokens"] + tot["retry_out_tokens"]
    alltok = tot["in_tokens"] + tot["out_tokens"]
    lines.append(f"total       {tot['turns']:>5} {tot['retries']:>7}  {100 * tot['retries'] / max(1, calls):5.1f}%  "
                 f"{tot['in_tokens']:>7} {tot['out_tokens']:>8}  {rtok:>7} ({100 * rtok / max(1, alltok):4.1f}%)  {tot['consolidations']:>6}")
    return "\n".join(lines)


def main() -> None:
    import argparse

    from ..config import settings

    ap = argparse.ArgumentParser(description="G2's Claude API usage and retry share")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    print(summarize(UsageTracker(settings.usage_path), args.days,
                    float(os.environ.get("G2_PRICE_IN_PER_MTOK", 0) or 0), float(os.environ.get("G2_PRICE_OUT_PER_MTOK", 0) or 0)))


if __name__ == "__main__":
    main()
