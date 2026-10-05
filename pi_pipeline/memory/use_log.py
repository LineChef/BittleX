"""Which memory shaped a reply? Two independent signals, both kept as per-fact counters (no conversation text is stored):

  * declared: G2 is shown each note with a tag ([#12] for a fact, [s3] for a sighting) and calls the `memory_used` tool, naming the tags,
    only when a note actually shaped what he said. This catches influence that shows no shared words (tone, a decision).
  * matched:  the reply itself is compared with the injected notes; a note counts when the reply shares enough of its content words
    (`overlap_used`). Free and automatic, but a heuristic: it misses paraphrases.

`python -m pi_pipeline.memory usage` reports the counters: how often each fact was injected, declared, matched, and the facts that were
injected many times without ever being used (candidates to forget or demote)."""
from __future__ import annotations

import re

_STOP = frozenset("""a an the and or but if then so of in on at to for from with without by as is are was were be been being am do does did
have has had i me my mine you your yours we our us they them their he she it its this that these those there here what which who whom how
why when where not no yes can could would should will just very really also too about like love into out up down over under again""".split())


def _words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9']+", (text or "").lower()):
        w = w.strip("'")
        if len(w) < 3 or w in _STOP:
            continue
        out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)      # crude plural stripping: dogs -> dog
    return out


def overlap_used(reply: str, notes: dict[int, str]) -> set[int]:
    """Ids of the notes whose content words appear in `reply`: at least two shared words that make up at least half of the note's own
    content words, or at least three shared words."""
    r = _words(reply)
    hit = set()
    for nid, text in notes.items():
        n = _words(text)
        shared = len(r & n)
        if n and shared >= 2 and (shared / len(n) >= 0.5 or shared >= 3):
            hit.add(nid)
    return hit


def parse_tags(tags) -> tuple[set[int], set[int]]:
    """The tags G2 named in `memory_used` -> (fact ids, sighting ids). Ignores anything it cannot read."""
    facts, sights = set(), set()
    for t in tags or []:
        m = re.fullmatch(r"\s*(#|s|S)\s*(\d+)\s*", str(t))
        if not m:
            continue
        (facts if m.group(1) == "#" else sights).add(int(m.group(2)))
    return facts, sights


def format_report(store) -> str:
    """The text of `python -m pi_pipeline.memory usage`."""
    turns = int(store.get_meta("use_turns", "0"))
    if not turns:
        return "  no turns with memory notes recorded yet"
    n = lambda k: int(store.get_meta(k, "0"))
    pct = lambda x: f"{100 * x / turns:.0f}%"
    lines = [f"  {turns} turn(s) had memory notes in the prompt.",
             f"  G2 named a note that shaped his reply in {n('use_turns_declared')} ({pct(n('use_turns_declared'))}); the reply echoed a note in "
             f"{n('use_turns_matched')} ({pct(n('use_turns_matched'))}); either signal: {n('use_turns_any')} ({pct(n('use_turns_any'))}).",
             f"  Sightings: injected {n('sight_injected')}, named {n('sight_declared')}, echoed {n('sight_matched')}.", "",
             "  fact   injected  declared  matched  last used   importance  text"]
    rows = store.fact_use_rows()
    for r in rows:
        tag = ("core " if r["core"] else "") + ("reflection " if r["source"] == "reflection" else "")
        lines.append(f"  #{r['id']:<5} {r['injected']:>8}  {r['declared']:>8}  {r['matched']:>7}  {r['last_used'] or '-':<10}  "
                     f"{r['importance']:>10}  {tag}{r['fact'][:70]}")
    idle = [r for r in rows if r["injected"] >= 20 and not r["declared"] and not r["matched"] and not r["core"]]
    if idle:
        lines += ["", "  Injected 20+ times and never used (consider forgetting or lowering): " + ", ".join(f"#{r['id']}" for r in idle)]
    return "\n".join(lines)
