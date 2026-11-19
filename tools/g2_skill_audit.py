#!/usr/bin/env python3
"""Audit how the project skills are really used, from the Claude Code session transcripts (read-only, local; nothing is sent anywhere).

    python tools/g2_skill_audit.py [--since 2026-11-01] [--top 15] [--transcripts DIR]

Replaces the by-hand "check our skill usage" pass. It reads the sessions' JSONL transcripts and prints:
  1. how often each skill in `.claude/skills/` was invoked, and which were never invoked in the range;
  2. per skill, the `tools/...` scripts and `g2...` helpers its steps name that were never run in the range (a step nobody runs is missing, stale or too slow to bother with);
  3. command shapes (the program and its first argument) typed by hand at least `--min` times that no skill names and no tool script covers: candidates for a script.
Default transcripts folder: ~/.claude/projects/<this repo's path with / as ->. Dates are the transcript timestamps (UTC). The logic is in pure functions so it is tested on made-up transcripts."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_TOOLS = re.compile(r"(?:bash |python3? )?(tools/[\w./-]+)")
SKILL_ALIAS = re.compile(r"`(g2[a-z0-9]+)(?:[ `])")
SKIP_FIRST = {"cd", "export", "set", "source", "echo", "ls", "cat", "head", "tail", "grep", "sed", "awk", "wc", "sort", "pwd", "git", "rm", "mkdir", "cp", "mv", "open", "sleep", "test", "true", "for", "if", "while", "["}


def default_transcripts() -> Path:
    return Path.home() / ".claude/projects" / str(ROOT).replace("/", "-")


def read_events(folder: Path, since: str | None = None) -> list[dict]:
    """(kind, name, text) events from every transcript in the folder: kind "skill" (name = the skill) or "bash" (text = the command)."""
    out = []
    for f in sorted(folder.glob("*.jsonl")):
        try:
            lines = f.read_text(errors="ignore").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if since and str(d.get("timestamp", ""))[:10] < since:
                continue
            c = (d.get("message") or {}).get("content")
            if d.get("type") != "assistant" or not isinstance(c, list):
                continue
            for b in c:
                if b.get("type") != "tool_use":
                    continue
                inp = b.get("input") or {}
                if b.get("name") == "Skill" and inp.get("skill"):
                    out.append({"kind": "skill", "name": str(inp["skill"]).split(":")[-1], "text": ""})
                elif b.get("name") == "Bash" and inp.get("command"):
                    out.append({"kind": "bash", "name": "", "text": str(inp["command"])})
    return out


def skill_steps(skills_dir: Path) -> dict[str, set]:
    """{skill: the tools/ scripts and g2 helpers its SKILL.md names}."""
    out = {}
    for md in sorted(skills_dir.glob("*/SKILL.md")):
        text = md.read_text(errors="ignore")
        out[md.parent.name] = {m.rstrip(".,;:)") for m in SKILL_TOOLS.findall(text)} | set(SKILL_ALIAS.findall(text))
    return out


def shape(command: str) -> str | None:
    """The program and its first argument of the command's last segment ("tools/g2_sync.sh run", "git status"): what a person would name as one routine. None for plain shell chatter."""
    seg = re.split(r"&&|\|\||;|\n", command.strip())
    seg = [s.strip() for s in seg if s.strip() and not s.strip().startswith(("cd ", "#"))]
    if not seg:
        return None
    try:
        toks = shlex.split(seg[0].split("|")[0])
    except ValueError:
        toks = seg[0].split()
    toks = [t for t in toks if "=" not in t.split("/")[0] or t.startswith("-")]
    wrappers = ("bash", "python3", "python", "nohup", "timeout", "pi_pipeline/.venv/bin/python", ".venv/bin/python")
    for _ in range(6):                                     # peel the wrappers off the front: `bash x`, `python3 x`, `pi_pipeline/.venv/bin/python -m x`
        if not toks or toks[0] not in wrappers:
            break
        w = toks.pop(0)
        if w == "timeout" and toks:
            toks.pop(0)                                    # its duration
        if toks and toks[0] == "-m":
            toks.pop(0)
    if not toks:
        return None
    if toks[0].startswith("pi_pipeline/.venv/bin/pytest") or toks[0] == "pytest":
        return "pytest"
    if toks[0] in ("-", "-c") or toks[0].startswith("<<"):
        return "python inline script"                       # `python - <<EOF` or `python -c`: a script typed on the spot, the commonest candidate
    if toks[0] in SKIP_FIRST:
        return None
    return " ".join(toks[:2])[:60]


def audit(events: list[dict], steps: dict[str, set], min_repeat: int = 3, known_tools: set | None = None) -> dict:
    invoked = Counter(e["name"] for e in events if e["kind"] == "skill")
    cmds = [e["text"] for e in events if e["kind"] == "bash"]
    joined = "\n".join(cmds)
    never = {s: sorted(x for x in names if x not in joined and Path(x).name not in joined) for s, names in steps.items()}
    named = set().union(*steps.values()) if steps else set()
    shapes = Counter(s for s in (shape(c) for c in cmds) if s)
    covered = lambda sh: any(n in sh or Path(n).name in sh for n in named | (known_tools or set()))  # noqa: E731
    repeated = [(s, n) for s, n in shapes.most_common() if n >= min_repeat and not covered(s)]
    return {"invoked": dict(invoked), "never_invoked": sorted(set(steps) - set(invoked)), "steps_never_run": {k: v for k, v in never.items() if v}, "repeated": repeated}


def render(a: dict, top: int = 15) -> list[str]:
    out = ["skill invocations: " + (", ".join(f"{k} {v}" for k, v in sorted(a["invoked"].items(), key=lambda kv: -kv[1])) or "none")]
    out.append("never invoked: " + (", ".join(a["never_invoked"]) or "none"))
    out.append("steps a skill names that were never run:")
    out += [f"  {s}: {', '.join(v)}" for s, v in sorted(a["steps_never_run"].items())] or ["  none"]
    out.append(f"command shapes typed by hand {'3+'} times that no skill or tool script covers (script candidates):")
    out += [f"  {n:3d} x {s}" for s, n in a["repeated"][:top]] or ["  none"]
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit skill usage from the Claude Code transcripts (read-only).")
    ap.add_argument("--since", default=None, help="only events on or after this date, YYYY-MM-DD")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min", type=int, default=3, help="a command shape must repeat this many times to be listed")
    ap.add_argument("--transcripts", default=None)
    a = ap.parse_args()
    folder = Path(a.transcripts) if a.transcripts else default_transcripts()
    if not folder.is_dir():
        raise SystemExit(f"no transcripts folder at {folder}")
    tools = {f"tools/{p.name}" for p in (ROOT / "tools").iterdir() if p.is_file()}
    print("\n".join(render(audit(read_events(folder, a.since), skill_steps(ROOT / ".claude/skills"), a.min, tools), a.top)))


if __name__ == "__main__":
    main()
