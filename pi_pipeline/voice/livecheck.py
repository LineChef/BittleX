"""Live end-to-end check of the voice pipeline against the real Anthropic API.

Everything except this has only ever run against mocks. This makes a handful of
real (billed) calls -- a few cents -- and verifies:

  * a plain question comes back as spoken text
  * "do a happy wiggle" is parsed into a `perform_skill` action
  * "remember X" is parsed into a `remember` fact
  * the `memory_context` seam accepts injected context without error

Run it after putting a key in `.env` (`ANTHROPIC_API_KEY=...`):

    pi_pipeline/.venv/bin/python -m pi_pipeline.voice.livecheck

Exit 0 = all checks passed. `test_livecheck.py` runs the same thing under pytest
and SKIPS when no key is configured.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import settings
from .conversation import Conversation


@dataclass
class LiveCheckReport:
    passed: bool = True
    lines: list[str] = field(default_factory=list)
    timings_s: list[float] = field(default_factory=list)

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.passed &= ok
        self.lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name}"
                          + (f" -- {detail}" if detail else ""))


def run_livecheck(cfg=settings) -> LiveCheckReport:
    r = LiveCheckReport()
    if not cfg.anthropic_api_key:
        r.passed = False
        r.lines.append("  no ANTHROPIC_API_KEY -- set it in .env")
        return r

    conv = Conversation(cfg)
    r.lines.append(f"  model: {cfg.claude_model}   max_tokens: {cfg.claude_max_tokens}")

    import time
    def _turn(text, mem=None):
        t0 = time.monotonic()
        out = conv.send(text, memory_context=mem)
        r.timings_s.append(time.monotonic() - t0)
        return out

    t1 = _turn("In one short sentence: what are you?")
    r.check("plain reply has spoken text", bool(t1.speech.strip()),
            t1.speech[:80])

    t2 = _turn("Show me you're happy -- do a little happy wiggle.")
    r.check("'happy wiggle' -> a perform_skill action", bool(t2.actions),
            f"actions={t2.actions}")

    t3 = _turn("Please remember that my favourite colour is teal.")
    r.check("'remember ...' -> a fact", any("teal" in f.lower() for f in t3.facts),
            f"facts={t3.facts}")

    t4 = _turn("What did I just tell you to remember?",
               mem="Fact: their favourite colour is teal.")
    r.check("memory_context seam accepted + used",
            "teal" in t4.speech.lower(), t4.speech[:80])

    if r.timings_s:
        r.lines.append(f"  {len(r.timings_s)} calls, "
                       f"{sum(r.timings_s)/len(r.timings_s):.1f}s avg, "
                       f"{max(r.timings_s):.1f}s max")
    return r


def main() -> int:
    r = run_livecheck()
    print("voice pipeline live check")
    print("\n".join(r.lines))
    print("=> " + ("ALL PASSED" if r.passed else "FAILURES"))
    return 0 if r.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
