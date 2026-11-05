"""A daily ceiling on what G2 spends on Claude (user, 2026-11-04), worked out from the API call log (voice/api_log.py): no new setting to keep in step with the bill.

    G2_API_DAILY_USD=2.0     dollars per calendar day (local time); 0 = no ceiling. Prices come from G2_API_PRICE (default $2 in / $10 out per million tokens, Sonnet 5.5).

At 80% of the ceiling one warning goes into the log; at the ceiling `Conversation` makes no more Claude calls and G2 says so (a `ConversationError` the voice loop already speaks), until
midnight. Stop words, moves and every local command are not affected: they never call Claude. `python -m pi_pipeline.voice.api_log --hours 24` ends with today's figure.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger("g2.api_budget")

WARN_AT = 0.8
_cache: dict = {"t": 0.0, "day": "", "path": None, "spent": 0.0}
_warned_day = ""


def limit_usd() -> float:
    try:
        return max(0.0, float(os.environ.get("G2_API_DAILY_USD", "2.0")))
    except ValueError:
        return 2.0


def spent_today(now: float | None = None, max_age_s: float = 30.0) -> float:
    """Estimated dollars spent on Claude since local midnight (the log is read at most every `max_age_s` seconds)."""
    from . import api_log
    now = time.time() if now is None else now
    day = time.strftime("%Y-%m-%d", time.localtime(now))
    path = api_log.log_path()
    if _cache["path"] == str(path) and _cache["day"] == day and now - _cache["t"] < max_age_s:
        return _cache["spent"]
    spent = 0.0
    if path is not None and path.exists():
        pi, po = api_log._price()
        try:
            for line in path.read_text().splitlines():
                if day not in line[:32]:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("event") == "done" and r.get("api") != "models.list" and str(r.get("ts", "")).startswith(day):
                    spent += api_log.cost_of(r, pi, po)
        except OSError:
            pass
    _cache.update(t=now, day=day, path=str(path), spent=spent)
    return spent


def state(now: float | None = None) -> tuple[str, float, float]:
    """("ok" | "warn" | "over", dollars spent today, the ceiling). With no ceiling the state is always "ok"."""
    lim, spent = limit_usd(), spent_today(now)
    if lim <= 0:
        return "ok", spent, lim
    return ("over" if spent >= lim else "warn" if spent >= WARN_AT * lim else "ok"), spent, lim


def check(now: float | None = None) -> tuple[str, float, float]:
    """`state()`, plus one warning in the log per day when 80% is reached."""
    global _warned_day
    st, spent, lim = state(now)
    day = time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))
    if st != "ok" and _warned_day != day:
        _warned_day = day
        log.warning("Claude spend today is about $%.2f of the $%.2f daily ceiling (G2_API_DAILY_USD)", spent, lim)
    return st, spent, lim


def status_line() -> str:
    st, spent, lim = state()
    if lim <= 0:
        return f"today ~${spent:.2f}; no daily ceiling (G2_API_DAILY_USD=0)"
    return f"today ~${spent:.2f} of the ${lim:.2f} daily ceiling ({100 * spent / lim:.0f}%)" + (" - NO MORE CLAUDE CALLS UNTIL MIDNIGHT" if st == "over" else "")


def reset_cache() -> None:
    """For tests."""
    global _warned_day
    _cache.update(t=0.0, day="", path=None, spent=0.0)
    _warned_day = ""
