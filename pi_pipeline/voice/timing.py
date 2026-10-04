"""Per-turn latency trace for the voice loop.

Each Claude turn records a few timestamps (monotonic seconds) and logs ONE line,
`turn-timing {json}`, with the intervals between them -- no transcript text. Pull a
run's lines out of the journal and summarise them:

    journalctl -u g2-voice -o cat | python -m pi_pipeline.voice.timing

Stages: speech_end (the last time the partial transcript changed -- close to when you
stopped talking), transcript (STT returned), claude_start/claude_end (the API call),
voice_start (just before the spoken reply), move_sent (just before the first skill).
"""
from __future__ import annotations

import json
import re
import statistics
import sys
import time

# (interval name, from stage, to stage)
INTERVALS = (
    ("stt_wait", "speech_end", "transcript"),
    ("pre_claude", "transcript", "claude_start"),
    ("claude", "claude_start", "claude_end"),
    ("to_voice", "claude_end", "voice_start"),
    ("to_move", "claude_end", "move_sent"),
    ("total_to_voice", "speech_end", "voice_start"),
    ("total_to_move", "speech_end", "move_sent"),
)


class TurnTrace:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self.times: dict[str, float] = {}
        self.meta: dict = {}

    def stamp(self, name: str, t: float | None = None) -> None:
        if t is not None:
            self.times.setdefault(name, t)
        else:
            self.times.setdefault(name, self._clock())

    def intervals(self) -> dict[str, float]:
        out = {}
        for name, a, b in INTERVALS:
            if a in self.times and b in self.times:
                out[name] = round(self.times[b] - self.times[a], 3)
        return out

    def line(self) -> str:
        return "turn-timing " + json.dumps({**self.intervals(), **self.meta}, sort_keys=True)


_LINE = re.compile(r"turn-timing (\{.*\})")


def parse(text: str) -> list[dict]:
    return [json.loads(m.group(1)) for m in map(_LINE.search, text.splitlines()) if m]


def summarize(turns: list[dict]) -> str:
    if not turns:
        return "no turn-timing lines found"
    lines = [f"{len(turns)} turns"]
    for name, _a, _b in INTERVALS:
        vals = [t[name] for t in turns if name in t]
        if vals:
            lines.append(f"  {name:15} n={len(vals):2}  median {statistics.median(vals):5.2f}s  "
                         f"mean {statistics.mean(vals):5.2f}s  min {min(vals):5.2f}s  max {max(vals):5.2f}s")
    warm = [t.get("warm") for t in turns if "warm" in t]
    if warm:
        lines.append(f"  warm-up finished before the Claude call: {sum(1 for w in warm if w)}/{len(warm)} turns")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summarize(parse(sys.stdin.read())))
