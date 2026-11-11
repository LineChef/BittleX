#!/usr/bin/env python3
"""The cheat sheet's A to Z index, and the rules that keep the cheat sheet a quick reference. Stdlib only.

    python tools/gen_cheatsheet_index.py           # rewrite the index at the bottom of docs/guides/cheatsheet.md
    python tools/gen_cheatsheet_index.py --check   # exit 1 if the index is stale or a row breaks a rule (the doc checker runs this)

The index lists every `g2*` command in docs/guides/cheatsheet.md and cheatsheet-advanced.md with the section it is in. The rules (user, 2026-11-04: a quick reference shows
an example you can copy, not the grammar of the command):
  * a command row is a bullet, - `example`: short description, one command per row (no pipe tables in the docs);
  * the example has no [optional] brackets and no \\| choices (write one real example; give each variation its own row);
  * the description is at most 80 characters;
  * a `g2*` command exists in tools/g2_aliases.sh.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md_headings  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PAGES = [("cheatsheet.md", "docs/guides/cheatsheet.md"), ("cheatsheet-advanced.md", "docs/guides/cheatsheet-advanced.md")]
START, END = "<!-- index:start -->", "<!-- index:end -->"
ROW = re.compile(r"^- `([^`]+)`(?:: (.*))?$")
MAX_DESC = 80


def slug(heading: str) -> str:
    s = re.sub(r"[^\w\s-]", "", heading.lower())
    return re.sub(r"\s", "-", s.strip())


def aliases(root: str = ROOT) -> set:
    text = open(os.path.join(root, "tools", "g2_aliases.sh")).read()
    return set(re.findall(r"^(g2[\w-]*)\(\)", text, re.M)) | set(re.findall(r"^alias (g2[\w-]*)=", text, re.M))


def rows(root: str = ROOT):
    """[(page file, heading, command, description, line number)] for every command row outside code blocks."""
    out = []
    for fname, rel in PAGES:
        heading, fence = "", False
        body = open(os.path.join(root, rel)).read()
        heads = {i: md_headings.unescape(t) for i, _lv, t in md_headings.parse_headings(body)}          # ATX and Setext headings, by line index
        for n, line in enumerate(body.splitlines(), 1):
            if n - 1 in heads:
                heading = heads[n - 1]
                continue
            if line.strip() == START:                     # everything after this is the generated index itself
                break
            if line.startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            m = ROW.match(line)
            if m:
                out.append((fname, heading, m.group(1), m.group(2) or "", n))
    return out


def errors(root: str = ROOT) -> list:
    known, bad = aliases(root), []
    for fname, heading, cmd, desc, n in rows(root):
        where = f"docs/guides/{fname}:{n}"
        if "\\|" in cmd or re.search(r"\[[^\]]*\]", cmd) or "|" in cmd:
            bad.append(f"{where}: `{cmd}` shows the grammar, not an example (no [brackets] or | choices; one real example per row)")
        if len(desc) > MAX_DESC and not re.fullmatch(r"\*\*.*", desc):
            bad.append(f"{where}: the description is {len(desc)} characters (at most {MAX_DESC}); move the detail to a guide")
        first = cmd.split()[0]
        if first.startswith("g2") and first not in known:
            bad.append(f"{where}: `{first}` is not defined in tools/g2_aliases.sh")
    return bad


def build_index(root: str = ROOT) -> str:
    where = {}
    for fname, heading, cmd, _desc, _n in rows(root):
        first = cmd.split()[0]
        if first.startswith("g2"):
            where.setdefault(first, [])
            link = f"[{heading}]({'' if fname == 'cheatsheet.md' else fname}#{slug(heading)})"
            if link not in where[first]:
                where[first].append(link)
    return "\n".join(f"- `{a}`: {', '.join(where[a])}" for a in sorted(where))


def build(root: str = ROOT) -> str:
    """The cheat sheet's text with the index filled in."""
    path = os.path.join(root, "docs", "guides", "cheatsheet.md")
    text = open(path).read()
    a, b = text.index(START) + len(START), text.index(END)
    return text[:a] + "\n" + build_index(root) + "\n" + text[b:]


def main(argv) -> int:
    path = os.path.join(ROOT, "docs", "guides", "cheatsheet.md")
    if "--check" in argv:
        bad = errors()
        if open(path).read() != build():
            bad.append("docs/guides/cheatsheet.md: the A to Z index is out of date -- run: python tools/gen_cheatsheet_index.py")
        print("\n".join(bad))
        return 1 if bad else 0
    text = build()                                  # built BEFORE the file is opened for writing (opening it first empties it)
    with open(path, "w") as f:
        f.write(text)
    print("wrote", path)
    for e in errors():
        print("RULE:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
