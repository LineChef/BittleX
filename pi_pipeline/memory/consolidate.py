"""Sleep-time consolidation: while G2 is idle (or after "go to sleep"), one Claude call tidies his memory off the conversation path.

It reads the facts G2 holds plus what happened since the last pass (new exchanges and sightings) and proposes:
  * merges: facts that say the same thing become one, better-worded fact;
  * drops: clearly trivial facts (importance 1-2) are removed;
  * reflections: up to three short inferred notes about stable preferences, written as "It seems ..." and stored with source
    "reflection" so they are recognisable and easy to delete.
Guardrails: core facts are never dropped; at most MAX_DROPS facts removed per pass; nothing with a date, time or schedule is written
(the same rule as the `remember` tool); every ids must exist; every change is written to an audit log (the old text) so a pass can be
undone by hand; the pass reads at most the last 40 exchanges. The Claude call is counted in `voice/usage.py` as a consolidation.

    python -m pi_pipeline.memory consolidate            # dry run: show what it would do
    python -m pi_pipeline.memory consolidate --apply    # do it"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

from .store import NEAR_DUPLICATE, Store, has_temporal_detail, similarity

log = logging.getLogger("g2.consolidate")

MAX_DROPS = 5
MAX_MERGES = 5
MAX_REFLECTIONS = 3
MAX_FACT_CHARS = 200

SYSTEM = """You maintain the long-term memory of G2, a small robot companion. You are given G2's current facts, and what happened since \
you last looked. Reply with ONLY a JSON object:
{"merges": [{"keep_id": <id>, "drop_ids": [<ids>], "text": "<one better-worded fact>", "importance": <1-5>}],
 "drop_ids": [<ids of clearly trivial facts>],
 "reflections": [{"text": "It seems ...", "importance": <1-3>}]}
Rules:
- Merge only facts that say the same thing (or that update each other: keep the newer information). Never merge facts about different things.
- drop_ids: only facts that are clearly trivial or one-off. Never drop a fact marked core. When unsure, keep it.
- reflections: at most 3. Each is a short note about a STABLE preference or pattern the new material supports, starting "It seems". Never
  include dates, times, days, schedules, routines, or where anyone is or was. Never invent: if nothing is supported, return none.
- Keep every fact a short standalone sentence. If nothing needs changing, return {"merges": [], "drop_ids": [], "reflections": []}."""


# Written reflections are inferences, so they get a stricter filter than saved facts: no times of day, meals, comings and goings.
_ROUTINE_RE = re.compile(
    r"\b(morning|afternoon|evening|night|overnight|dawn|dusk|bedtime|breakfast|lunch|dinner|weekday|weekend|usually at|always at|"
    r"comes? home|gets? home|leav(es|ing) (for|the house)|goes? to (work|bed|school)|wakes? up|when they (come|get|leave|arrive))\b", re.I)


def _unsafe(text: str) -> bool:
    return has_temporal_detail(text) or bool(_ROUTINE_RE.search(text))


def _clip(text: str, n: int = 160) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def parse_plan(text: str) -> dict | None:
    """The first JSON object in the model's reply (it may be wrapped in a code fence), or None."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        plan = json.loads(m.group(0))
    except ValueError:
        return None
    return plan if isinstance(plan, dict) else None


def make_llm(cfg):
    """The default model call: (system, user) -> (text, usage). One short Claude request, no tools."""
    import anthropic

    from ..voice.conversation import _http_client_kwargs
    client = anthropic.Anthropic(api_key=cfg.require_api_key(), timeout=cfg.request_timeout_s, **_http_client_kwargs(cfg.api_keepalive_s))

    def llm(system: str, user: str):
        resp = client.messages.create(
            model=cfg.claude_model, max_tokens=900, system=system, messages=[{"role": "user", "content": user}],
            **({"output_config": {"effort": cfg.claude_effort}} if cfg.claude_effort else {}))
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text"), getattr(resp, "usage", None)
    return llm


class Consolidator:
    def __init__(self, store: Store, llm, *, usage=None, audit_path=None, min_new_exchanges: int = 6):
        self.store, self._llm, self._usage = store, llm, usage
        self._audit = Path(audit_path).expanduser() if audit_path else None
        self.min_new_exchanges = min_new_exchanges

    # -- what is new since the last pass ---------------------------------------
    def _marks(self) -> tuple[int, int]:
        return int(self.store.get_meta("consolidated_exchange_id", "0")), int(self.store.get_meta("consolidated_observation_id", "0"))

    def pending_exchanges(self) -> list:
        return self.store.exchanges_after(self._marks()[0], limit=40)

    def has_enough_new(self) -> bool:
        return len(self.pending_exchanges()) >= self.min_new_exchanges

    # -- propose (one model call) -------------------------------------------------
    def propose(self) -> tuple[dict | None, str]:
        """Ask the model for a plan. Returns (validated actions or None, a short note)."""
        ex_mark, ob_mark = self._marks()
        exchanges, sightings = self.store.exchanges_after(ex_mark, limit=40), self.store.observations_after(ob_mark, limit=20)
        facts = self.store.list_facts()
        payload = {
            "facts": [{"id": f["id"], "fact": f["fact"], "importance": f["importance"], "core": bool(f["core"]), "source": f["source"]}
                      for f in facts],
            "new_exchanges": [{"user": _clip(e["user_text"]), "g2": _clip(e["assistant_text"])} for e in exchanges],
            "new_sightings": [_clip(o["caption"]) for o in sightings],
        }
        text, usage = self._llm(SYSTEM, json.dumps(payload))
        if self._usage is not None:
            self._usage.record("consolidation", usage)
        plan = parse_plan(text)
        if plan is None:
            return None, "the model's reply was not a usable plan"
        actions = self._validate(plan, {f["id"]: f for f in facts})
        actions["marks"] = (exchanges[-1]["id"] if exchanges else ex_mark, sightings[-1]["id"] if sightings else ob_mark)
        return actions, "ok"

    def _validate(self, plan: dict, by_id: dict) -> dict:
        merges, drops, reflections, seen_drop = [], [], [], set()

        def droppable(i) -> bool:
            f = by_id.get(i)
            return f is not None and not f["core"] and i not in seen_drop

        for m in (plan.get("merges") or [])[:MAX_MERGES]:
            try:
                keep, text = int(m["keep_id"]), str(m["text"]).strip()
                ids = [int(i) for i in (m.get("drop_ids") or [])]
                imp = max(1, min(5, int(m.get("importance", by_id.get(keep, {"importance": 3})["importance"]))))
            except (KeyError, TypeError, ValueError):
                continue
            if keep not in by_id or not text or len(text) > MAX_FACT_CHARS or _unsafe(text):
                continue
            ids = [i for i in ids if i != keep and droppable(i) and len(seen_drop) < MAX_DROPS]
            if not ids:
                continue
            if any(similarity(text, f["fact"]) >= NEAR_DUPLICATE and fid not in ids and fid != keep for fid, f in by_id.items()):
                continue                                              # the rewrite would just duplicate an unrelated third fact
            seen_drop.update(ids)
            merges.append({"keep_id": keep, "drop_ids": ids, "text": text, "importance": imp})
        for i in plan.get("drop_ids") or []:
            try:
                i = int(i)
            except (TypeError, ValueError):
                continue
            if droppable(i) and by_id[i]["importance"] <= 2 and len(seen_drop) < MAX_DROPS:
                seen_drop.add(i); drops.append(i)
        for r in (plan.get("reflections") or [])[:MAX_REFLECTIONS]:
            try:
                text, imp = str(r["text"]).strip(), max(1, min(3, int(r.get("importance", 2))))
            except (KeyError, TypeError, ValueError):
                continue
            if not text or len(text) > MAX_FACT_CHARS or _unsafe(text):
                continue
            if not re.match(r"(it seems|probably)\b", text, re.I):
                text = "It seems " + text[0].lower() + text[1:]
            reflections.append({"text": text, "importance": imp})
        return {"merges": merges, "drops": drops, "reflections": reflections}

    # -- apply (with an audit trail) -----------------------------------------------
    def apply(self, actions: dict) -> dict:
        by_id = {f["id"]: f for f in self.store.list_facts()}
        audit = {"merged": [], "dropped": [], "reflected": []}
        for m in actions["merges"]:
            before = by_id[m["keep_id"]]["fact"]
            old_dropped = [by_id[i]["fact"] for i in m["drop_ids"] if i in by_id]
            for i in m["drop_ids"]:
                self.store.delete_fact(i)
            if self.store.update_fact(m["keep_id"], m["text"], m["importance"]):
                audit["merged"].append({"kept_before": before, "dropped": old_dropped, "now": m["text"]})
        for i in actions["drops"]:
            if i in by_id and self.store.delete_fact(i):
                audit["dropped"].append(by_id[i]["fact"])
        for r in actions["reflections"]:
            if self.store.add_fact(r["text"], importance=r["importance"], core=False, source="reflection"):
                audit["reflected"].append(r["text"])
        ex, ob = actions["marks"]
        self.store.set_meta("consolidated_exchange_id", str(ex))
        self.store.set_meta("consolidated_observation_id", str(ob))
        if self._audit and (audit["merged"] or audit["dropped"] or audit["reflected"]):
            try:
                self._audit.parent.mkdir(parents=True, exist_ok=True)
                with open(self._audit, "a") as f:
                    f.write(json.dumps({"date": time.strftime("%Y-%m-%d"), **audit}) + "\n")
            except OSError:
                log.debug("could not write the consolidation audit log", exc_info=True)
        log.info("consolidation: merged %d, dropped %d, reflected %d", len(audit["merged"]), len(audit["dropped"]), len(audit["reflected"]))
        return audit

    def run(self, apply: bool = True) -> dict:
        actions, note = self.propose()
        if actions is None:
            return {"ok": False, "note": note}
        if not apply:
            return {"ok": True, "applied": False, "plan": actions}
        return {"ok": True, "applied": True, "result": self.apply(actions)}


class ConsolidationWatcher:
    """Runs a pass when G2 has been idle long enough, enough has happened since the last pass, and enough time has gone by in this
    process since the last one (so a day costs about one call). `nudge()` (the person told G2 to sleep) skips the idle wait."""

    def __init__(self, consolidator: Consolidator, idle_age, *, idle_s: float = 1200.0, min_interval_s: float = 21600.0,
                 poll_s: float = 60.0, clock=time.monotonic):
        self._c, self._idle_age = consolidator, idle_age
        self._idle_s, self._min_interval_s, self._poll_s, self._clock = idle_s, min_interval_s, poll_s, clock
        self._last_run: float | None = None
        self._nudged = False
        self._stop = threading.Event()
        self._started = clock()

    def nudge(self) -> None:
        self._nudged = True

    def tick(self) -> dict | None:
        now = self._clock()
        age = self._idle_age()
        idle_for = age if age is not None else now - self._started
        if not (self._nudged or idle_for >= self._idle_s):
            return None
        if self._last_run is not None and now - self._last_run < self._min_interval_s:
            return None
        if not self._c.has_enough_new():
            return None
        self._nudged = False
        self._last_run = now
        try:
            return self._c.run(apply=True)
        except Exception:  # noqa: BLE001 -- a failed pass must never disturb G2
            log.warning("consolidation failed", exc_info=True)
            return None

    def start(self) -> "ConsolidationWatcher":
        def _run() -> None:
            while not self._stop.wait(self._poll_s):
                self.tick()
        threading.Thread(target=_run, name="consolidation", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
