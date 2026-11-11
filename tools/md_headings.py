"""Section headings in the published docs are a title line over a `---` underline (a Setext heading), not `## Title` (owner, 2026-11-11: no `##` markup in the site's pages). Every tool that reads
headings goes through `parse_headings()`, which understands both forms; `h2_to_setext()` converts text; `python tools/md_headings.py FILE...` converts files in place. Stdlib only.

Only level 2 changes. The page title stays `# Title`, and sub-sections (`###` and deeper) are unchanged. A title that would open a list (`1. The exported policy`) or a quote has its first marker
escaped (`1\\. The exported policy`) so it stays a heading; `unescape()` and the anchor slug ignore the backslash.
"""
from __future__ import annotations

import re
import sys

FENCE = re.compile(r"^\s*(```|~~~)")
ATX = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
UNDER2 = re.compile(r"^-{2,}\s*$")
UNDER1 = re.compile(r"^={2,}\s*$")
OPENER = re.compile(r"^(\d+)([.)])(\s)|^([-+*>])(\s)")


def unescape(text: str) -> str:
    return re.sub(r"\\([.)\-+*>#])", r"\1", text)


def _front_matter_end(lines: list[str]) -> int:
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return i + 1
    return 0


def parse_headings(text: str):
    """[(line index from 0, level, heading text)] for every heading: ATX (`## T`) and Setext (a line over `---` or `===` that follows a blank line). Code fences and front matter are skipped."""
    lines = text.split("\n")
    out, i, fence = [], _front_matter_end(lines), False
    while i < len(lines):
        ln = lines[i]
        if FENCE.match(ln):
            fence = not fence
            i += 1
            continue
        if fence:
            i += 1
            continue
        m = ATX.match(ln)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
            i += 1
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        prev_blank = i == 0 or not lines[i - 1].strip() or i == _front_matter_end(lines)
        if ln.strip() and prev_blank and not ln.lstrip().startswith(("|", ">", "<")) and (UNDER2.match(nxt) or UNDER1.match(nxt)) and not re.match(r"^\s*([-*+]|\d+[.)])\s", ln):
            out.append((i, 1 if UNDER1.match(nxt) else 2, ln.strip()))
            i += 2
            continue
        i += 1
    return out


def h2_to_setext(text: str) -> tuple[str, int]:
    """Convert every `## Title` outside code fences and front matter to `Title` over a `---` underline. Returns (text, count)."""
    lines = text.split("\n")
    out, n, fence = [], 0, False
    fm = _front_matter_end(lines)
    for i, ln in enumerate(lines):
        if i < fm:
            out.append(ln)
            continue
        if FENCE.match(ln):
            fence = not fence
        m = None if fence else re.match(r"^##\s+(.*?)\s*#*\s*$", ln)
        if not m:
            out.append(ln)
            continue
        title = m.group(1)
        if OPENER.match(title):                                   # a title that begins like a list item or a quote keeps its first marker escaped
            title = _escape_opener(title)
        if out and out[-1].strip():
            out.append("")
        out.append(title)
        out.append("-" * max(3, min(len(unescape(title)), 60)))
        n += 1
    return "\n".join(out), n


def _escape_opener(title: str) -> str:
    m = re.match(r"^(\d+)([.)])(\s)", title)
    if m:
        return m.group(1) + "\\" + m.group(2) + title[m.end(2):]
    return "\\" + title


if __name__ == "__main__":
    total = 0
    for p in sys.argv[1:]:
        s = open(p, encoding="utf-8").read()
        new, n = h2_to_setext(s)
        if n:
            open(p, "w", encoding="utf-8").write(new)
            total += n
    print("h2 headings converted:", total)
