"""A log of every call G2 makes to the Claude API: one JSON line per event, so a bill can be matched to what happened and when.

    ~/.local/share/g2/api_calls.jsonl      (G2_API_LOG; "off" turns it off)
    python -m pi_pipeline.voice.api_log [--last 40]     # print the most recent lines
    python -m pi_pipeline.voice.api_log --hours 2       # calls, tokens and approximate cost in the last 2 h, by source

`instrument(client, source)` wraps the Anthropic client's `messages.create`, `messages.stream` and `models.list` in place, so any code that uses the client is
covered, including the free wake-word warm-up ping. Each call writes a "start" line (before the request leaves) and a "done" or "error" line (with the token
counts, stop reason and seconds when the API returned them). `source` names the part of G2 that owns the client ("voice", "consolidate", ...); `caller` is the function
that made the call. Lines also go to the `g2.api` logger (the service journal). Writing never raises into the caller. The file is rotated to `.1` at 5 MB.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("g2.api")
_LOCK = threading.Lock()
_MAX_BYTES = 5 * 1024 * 1024
_counter = 0
_call_hook = None        # called as hook(api, source) just before a billed call (messages.create / messages.stream); never for the free models.list ping


def set_call_hook(fn) -> None:
    """Register what happens when G2 is about to call the Claude API (the voice service plays `api_tone` here). `None` removes it."""
    global _call_hook
    _call_hook = fn


def _notify(api: str, source: str) -> None:
    fn = _call_hook
    if fn is None:
        return
    try:
        fn(api, source)
    except Exception:  # noqa: BLE001 -- a signal must never break a call
        log.debug("api call hook failed", exc_info=True)


def log_path() -> Path | None:
    v = os.environ.get("G2_API_LOG", "~/.local/share/g2/api_calls.jsonl").strip()
    return None if v.lower() in ("", "off", "0", "false", "no") else Path(v).expanduser()


def log_event(event: str, source: str, **fields) -> None:
    """Append one event line; never raises."""
    try:
        rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "event": event, "source": source, "pid": os.getpid(), **fields}
        log.info("API %s source=%s %s", event, source, " ".join(f"{k}={v}" for k, v in fields.items() if v is not None))
        p = log_path()
        if p is None:
            return
        with _LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            if p.exists() and p.stat().st_size > _MAX_BYTES:
                os.replace(p, p.with_suffix(p.suffix + ".1"))
            with open(p, "a") as f:
                f.write(json.dumps(rec) + "\n")
    except Exception:  # noqa: BLE001 -- logging must never break a conversation
        log.debug("api log failed", exc_info=True)


def _caller() -> str:
    """The function that called the wrapper (the frame that called the wrapper), for the 'caller' field."""
    try:
        f = sys._getframe(2)
        return f"{Path(f.f_code.co_filename).name}:{f.f_code.co_name}"
    except Exception:  # noqa: BLE001
        return "?"


def _request_fields(api: str, kw: dict) -> dict:
    msgs = kw.get("messages") or []
    has_image = any(isinstance(m, dict) and isinstance(m.get("content"), list)
                    and any(isinstance(b, dict) and b.get("type") == "image" for b in m["content"]) for m in msgs)
    return {"api": api, "model": kw.get("model"), "max_tokens": kw.get("max_tokens"), "n_messages": len(msgs), "has_image": has_image or None,
            "tools": len(kw.get("tools") or []) or None}


def _next_id() -> int:
    global _counter
    with _LOCK:
        _counter += 1
        return _counter


class _StreamManager:
    """Wraps the SDK's stream context manager: logs when the request starts (on enter) and ends (on exit)."""

    def __init__(self, inner, source: str, fields: dict, caller: str):
        self._inner, self._source, self._fields, self._caller = inner, source, fields, caller
        self._id, self._t0, self._stream = _next_id(), 0.0, None

    def __enter__(self):
        self._t0 = time.monotonic()
        log_event("start", self._source, id=self._id, caller=self._caller, **self._fields)
        _notify(self._fields["api"], self._source)
        self._stream = self._inner.__enter__()
        return self._stream

    def __exit__(self, exc_type, exc, tb):
        usage = None
        if not exc_type:
            try:
                usage = self._stream.get_final_message().usage      # the streamed reply's token counts, for the cost summary
            except Exception:  # noqa: BLE001
                usage = None
        try:
            return self._inner.__exit__(exc_type, exc, tb)
        finally:
            log_event("error" if exc_type else "done", self._source, id=self._id, api=self._fields["api"], seconds=round(time.monotonic() - self._t0, 2),
                      error=exc_type.__name__ if exc_type else None,
                      input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None),
                      cache_read_tokens=getattr(usage, "cache_read_input_tokens", None))

    def __getattr__(self, name):
        return getattr(self._inner, name)


def instrument(client, source: str):
    """Wrap `client.messages.create`, `client.messages.stream` and `client.models.list` so each call is logged. Safe to call twice. Returns the client."""
    if getattr(client, "_g2_api_logged", False):
        return client
    msgs, models = getattr(client, "messages", None), getattr(client, "models", None)

    if msgs is not None and hasattr(msgs, "create"):
        orig_create = msgs.create

        def create(*a, **kw):
            i, t0, fields = _next_id(), time.monotonic(), _request_fields("messages.create", kw)
            log_event("start", source, id=i, caller=_caller(), **fields)
            _notify("messages.create", source)
            try:
                resp = orig_create(*a, **kw)
            except Exception as e:
                log_event("error", source, id=i, api="messages.create", seconds=round(time.monotonic() - t0, 2), error=type(e).__name__)
                raise
            u = getattr(resp, "usage", None)
            log_event("done", source, id=i, api="messages.create", seconds=round(time.monotonic() - t0, 2), stop_reason=getattr(resp, "stop_reason", None),
                      input_tokens=getattr(u, "input_tokens", None), output_tokens=getattr(u, "output_tokens", None),
                      cache_read_tokens=getattr(u, "cache_read_input_tokens", None))
            return resp

        msgs.create = create

    if msgs is not None and hasattr(msgs, "stream"):
        orig_stream = msgs.stream

        def stream(*a, **kw):
            return _StreamManager(orig_stream(*a, **kw), source, _request_fields("messages.stream", kw), _caller())

        msgs.stream = stream

    if models is not None and hasattr(models, "list"):
        orig_list = models.list

        def list_models(*a, **kw):
            i, t0 = _next_id(), time.monotonic()
            log_event("start", source, id=i, caller=_caller(), api="models.list", note="free ping; no tokens")
            try:
                return orig_list(*a, **kw)
            except Exception as e:
                log_event("error", source, id=i, api="models.list", error=type(e).__name__)
                raise
            finally:
                log_event("done", source, id=i, api="models.list", seconds=round(time.monotonic() - t0, 2))

        models.list = list_models

    try:
        client._g2_api_logged = True
    except Exception:  # noqa: BLE001
        pass
    log_event("client", source, note="API client created")
    return client


def _price() -> tuple[float, float]:
    """(input, output) dollars per million tokens used for the estimate. ASSUMED Sonnet-class rates; set G2_API_PRICE="in,out" to match the real price list."""
    try:
        i, o = os.environ.get("G2_API_PRICE", "3,15").split(",")
        return float(i), float(o)
    except ValueError:
        return 3.0, 15.0


def summarize(lines: list[str], hours: float, now: float | None = None) -> str:
    """Calls, tokens and an approximate cost in the last `hours`, by source. Cached-input tokens are priced as normal input (a slight over-estimate)."""
    cutoff = (now if now is not None else time.time()) - hours * 3600
    by: dict[str, dict] = {}
    for line in lines:
        try:
            r = json.loads(line)
            t = time.mktime(time.strptime(r["ts"], "%Y-%m-%d %H:%M:%S"))
        except (ValueError, KeyError):
            continue
        if t < cutoff or r.get("event") not in ("start", "done", "error"):
            continue
        d = by.setdefault(r.get("source", "?"), {"billed": 0, "free": 0, "errors": 0, "in": 0, "out": 0, "unknown": 0, "last": ""})
        if r["event"] == "start":
            d["free" if r.get("api") == "models.list" else "billed"] += 1
            d["last"] = r["ts"]
        elif r["event"] == "error":
            d["errors"] += 1
        elif r.get("api") != "models.list":
            if r.get("input_tokens") is None and r.get("output_tokens") is None:
                d["unknown"] += 1
            d["in"] += (r.get("input_tokens") or 0) + (r.get("cache_read_tokens") or 0)
            d["out"] += r.get("output_tokens") or 0
    pi, po = _price()
    out = [f"API calls in the last {hours:g} h (cost assumes ${pi:g} in / ${po:g} out per million tokens; set G2_API_PRICE=in,out to change)"]
    if not by:
        return out[0] + "\nnone logged"
    tot = 0.0
    for src, d in sorted(by.items()):
        cost = d["in"] / 1e6 * pi + d["out"] / 1e6 * po
        tot += cost
        note = f", {d['unknown']} without token counts (cost understated)" if d["unknown"] else ""
        out.append(f"  {src:<12} {d['billed']} billed + {d['free']} free pings, {d['errors']} errors, {d['in']} in / {d['out']} out tokens, ~${cost:.3f}, last {d['last']}{note}")
    out.append(f"  total ~${tot:.3f}  ({sum(d['billed'] for d in by.values())} billed calls)")
    return "\n".join(out)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Print the most recent Claude API call log lines")
    ap.add_argument("--last", type=int, default=40)
    ap.add_argument("--hours", type=float, help="instead of the raw lines: calls, tokens and approximate cost in the last N hours, by source")
    args = ap.parse_args()
    n = args.last
    p = log_path()
    if p is None or not p.exists():
        print("no API call log yet" + ("" if p is None else f" ({p})"))
        return
    if args.hours:
        print(summarize(p.read_text().splitlines(), args.hours))
        return
    for line in p.read_text().splitlines()[-n:]:
        try:
            r = json.loads(line)
        except ValueError:
            continue
        rest = " ".join(f"{k}={v}" for k, v in r.items() if k not in ("ts", "event", "source", "pid") and v is not None)
        print(f"{r['ts']}  {r['event']:<6} {r['source']:<11} {rest}")


if __name__ == "__main__":
    main()
