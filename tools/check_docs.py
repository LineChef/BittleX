#!/usr/bin/env python3
"""Doc checks: broken links, volatile facts in the wrong place, orphan pages. Stdlib only.

    python tools/check_docs.py             # every tracked .md file
    python tools/check_docs.py --staged    # only staged .md files (what the pre-commit hook runs)
    python tools/check_docs.py --root DIR  # check another tree (used by the tests)

ERRORS (exit 1, block the commit):
  * a relative link whose target file or directory does not exist
  * a hard-coded test count ("679 tests", "599 passing") in a page that must not carry one
  * the currently deployed policy's name (read from DEFAULT_POLICY in the code) in a page that must not name it
  * docs/backlog.md out of date with the item headings it is generated from (tools/gen_backlog.py)
  * a `##` section heading in a published page (owner, 2026-11-11: sections are a title line over `---`; tools/md_headings.py converts)
  * a markdown pipe table (owner, 2026-11-11: no tables in the docs; write a bulleted list, one bullet per row; tools/md_lists.py converts)
WARNINGS (printed, never fail):
  * readability of a page published on the docs site: a line over 700 characters, an attribution tag such as
    "(user, 2026-10-21)", or no opening paragraph (the site uses it as the page summary)
  * a link whose #anchor matches no heading in the target page
  * a docs page that no other page links to (an orphan)

The rule behind the volatile-fact checks: a fact that changes belongs in ONE place (docs/STATUS.md for what is deployed and
what is true now; the code for the policy name; `pytest` for test results). Dated logs (docs/rl, docs/plan-detail, docs/archive/history.md,
docs/research, blueprints) record what was true then and are exempt. See docs/maintaining-docs.md, "Where to update what".
Bypass a genuine false positive with `git commit --no-verify`.
"""
import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md_headings  # noqa: E402

SKIP_DIRS = {".git", ".venv", "node_modules", ".pytest_cache", "__pycache__", "trained", "build"}  # build/ = local docs-bundle output
# pages that must not carry hard-coded counts / the current policy name (everything else is a log, a record, or generated)
VOLATILE_FREE = ("README.md", "docs/README.md", "docs/STATUS.md", "docs/capabilities.md", "docs/how-it-works.md",
                 "docs/project-plan.md", "docs/backlog.md", "docs/guides/", "docs/hardware/", "pi_pipeline/")
COUNT_RE = re.compile(r"\b\d{2,4}\s+(?:passing\s+)?tests\b|\b\d{2,4}\s+passing\b", re.I)
LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


GENERATED_PAGES = ("docs/guides/env-reference.md", "docs/guides/shell-helpers.md", "docs/guides/cheatsheet.md", "docs/guides/cheatsheet-advanced.md")
ATTRIBUTION_RE = re.compile(r"\((?:user|owner)[,:] ?20\d\d-\d\d-\d\d")
# Published pages read as a product specification, not as working notes (docs/maintaining-docs.md, "Writing a published page"): these patterns are the note-taking voice.
NOTE_PATTERNS = (
    ("assistant", re.compile(r"\b(?:tell|ask|let|have) Claude\b|\bClaude Code\b|\bClaude's (?:own )?(?:session|work)\b", re.I)),
    ("people", re.compile(r"\b(?:the user|the owner|owner|the user's|user's)\b")),
    ("first person", re.compile(r"(?<![\w`/.-])(?:I|we|we've|we're|our|ours|us|my)(?![\w`/.-])(?!\s*[=:(])")),
    ("date in prose", re.compile(r"\b20\d\d-\d\d-\d\d\b")),
    ("history", re.compile(r"\b(?:turned out|was tried|were tried|we tried|was found|were found|earlier (?:session|run|version)s?|at first|originally|previously)\b", re.I)),
)


def note_voice_hits(text):
    """[(line number, category, matched text)] for note-taking wording in a page's prose (code fences, front matter and link targets ignored)."""
    body = re.sub(r"^---\n.*?\n---\n", lambda m: "\n" * m.group(0).count("\n"), text, count=1, flags=re.S)
    out, infence = [], False
    for i, line in enumerate(body.splitlines(), 1):
        if FENCE_RE.match(line):
            infence = not infence
            continue
        if infence:
            continue
        prose = re.sub(r"`[^`]*`|\"[^\"]*\"|\u201c[^\u201d]*\u201d", "", re.sub(r"\]\([^)]*\)", "]", line))      # code, link targets and quoted speech (a spoken command may say "we" or "my") are not prose
        for cat, rx in NOTE_PATTERNS:
            m = rx.search(prose)
            if m:
                out.append((i, cat, m.group(0)))
    return out
CELL_WORDS, LONG_LINE = 40, 700


def published(path):
    """True for a page the docs bundle publishes (needs tools/build_docs_bundle.py next to this file)."""
    try:
        import build_docs_bundle as B
    except ImportError:
        return False
    return B.is_page(path) and not B.is_excluded(path)


def readability_warnings(path, text):
    """Warnings about a published page that reads like a working note rather than documentation."""
    out, infence, has_intro = [], False, False
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    generated = path in GENERATED_PAGES
    for i, line in enumerate(body.splitlines(), 1):
        if FENCE_RE.match(line):
            infence = not infence
            continue
        if infence:
            continue
        st = line.strip()
        if not has_intro and st and not st.startswith(("#", "|", ">", "-", "*", "!", "<")):
            has_intro = True
        if len(line) > LONG_LINE and not generated:
            out.append(f"{path}:{i}: line of {len(line)} characters; split it up or move detail into a list")
        if ATTRIBUTION_RE.search(line):
            out.append(f"{path}:{i}: attribution tag in a published page; keep who decided what in the working notes")
    if not has_intro:
        out.append(f"{path}: no opening paragraph; the site uses it as the page summary")
    hits = [] if generated else note_voice_hits(text)
    if hits:
        cats = sorted({c for _n, c, _m in hits})
        out.append(f"{path}: {len(hits)} note-style wording hit(s) ({', '.join(cats)}); write it as a specification (python tools/check_docs.py --notes lists them)")
    return out


def md_files(root, staged=False):
    if staged:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], cwd=root,
                             capture_output=True, text=True).stdout.split()
        return sorted(f for f in out if f.endswith(".md") and os.path.exists(os.path.join(root, f)))
    found = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".venv")]      # .venv-x86_64 etc. (2026-10-08)
        for f in files:
            if f.endswith(".md"):
                found.append(os.path.relpath(os.path.join(d, f), root))
    # CLAUDE.md is local-only and gitignored; it is not part of the shared docs
    return sorted(f for f in found if f != "CLAUDE.md")


def slug(heading):
    h = re.sub(r"`", "", heading.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h, flags=re.U)
    return h.replace(" ", "-")


def anchors_of(path):
    seen, out = {}, set()
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return out
    for _i, _level, heading in md_headings.parse_headings(text):
        s = slug(md_headings.unescape(heading))
        n = seen.get(s, 0)
        seen[s] = n + 1
        out.add(s if n == 0 else f"{s}-{n}")
    for m in re.finditer(r'<a\s+(?:name|id)="([^"]+)"', text):
        out.add(m.group(1))
    return out


def links_of(text):
    infence = False
    for i, line in enumerate(text.splitlines(), 1):
        if FENCE_RE.match(line):
            infence = not infence
            continue
        if infence:
            continue
        stripped = re.sub(r"`[^`\n]*`", "", line)           # links inside inline code are examples
        for m in LINK_RE.finditer(stripped):
            yield i, m.group(1)


def deployed_policy_stem(root):
    p = os.path.join(root, "pi_pipeline", "gait", "residual_policy.py")
    try:
        m = re.search(r'^DEFAULT_POLICY\s*=\s*"([^"]+)"', open(p).read(), re.M)
    except OSError:
        return None
    if not m:
        return None
    return re.sub(r"(_ppo)?\.onnx$", "", m.group(1))


def table_lines(text):
    """Line numbers where a pipe table starts (a header row followed by a separator row), outside code fences."""
    lines, out, infence = text.split("\n"), [], False
    sep = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
    for i, ln in enumerate(lines):
        if FENCE_RE.match(ln):
            infence = not infence
            continue
        if not infence and re.match(r"^\s*\|.*\|\s*$", ln) and i + 1 < len(lines) and "|" in lines[i + 1] and sep.match(lines[i + 1]):
            out.append(i + 1)
    return out


def check(root, files):
    errors, warnings = [], []
    policy = deployed_policy_stem(root)
    all_md = md_files(root)
    inbound = {f: 0 for f in all_md}
    anchor_cache = {}
    for f in all_md:                                     # inbound links come from every page, not just the checked ones
        full = os.path.join(root, f)
        for _, target in links_of(open(full, encoding="utf-8", errors="ignore").read()):
            t = target.split("#")[0].split("?")[0]
            if not t or re.match(r"^[a-z]+:", t):
                continue
            dest = os.path.normpath(os.path.join(os.path.dirname(full), t))
            rel = os.path.relpath(dest, root)
            if rel in inbound and rel != f:
                inbound[rel] += 1
    for f in files:
        full = os.path.join(root, f)
        text = open(full, encoding="utf-8", errors="ignore").read()
        volatile_free = any(f == v or (v.endswith("/") and f.startswith(v)) for v in VOLATILE_FREE)
        for line_no, target in links_of(text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):          # http:, https:, mailto:, ...
                continue
            path_part, _, anchor = target.partition("#")
            path_part = path_part.split("?")[0]
            if not path_part:                                            # same-page anchor
                if anchor and slug(anchor) not in anchors_of(full) and anchor not in anchors_of(full):
                    warnings.append(f"{f}:{line_no}: anchor #{anchor} not found in this page")
                continue
            dest = os.path.normpath(os.path.join(os.path.dirname(full), path_part))
            if not os.path.exists(dest):
                errors.append(f"{f}:{line_no}: broken link -> {target}")
                continue
            if anchor and dest.endswith(".md"):
                if dest not in anchor_cache:
                    anchor_cache[dest] = anchors_of(dest)
                if anchor not in anchor_cache[dest]:
                    warnings.append(f"{f}:{line_no}: anchor #{anchor} not found in {os.path.relpath(dest, root)}")
        for line_no in table_lines(text):
            errors.append(f"{f}:{line_no}: markdown pipe table -- no tables in the docs; write a bulleted list, one bullet per row (python tools/md_lists.py {f} converts it)")
        if volatile_free:
            infence = False
            for i, line in enumerate(text.splitlines(), 1):
                if FENCE_RE.match(line):
                    infence = not infence
                    continue
                if infence:
                    continue
                m = COUNT_RE.search(line)
                if m:
                    errors.append(f"{f}:{i}: hard-coded test count '{m.group(0)}' -- don't quote counts, run pytest")
                if policy and policy in line and f != "docs/STATUS.md":
                    errors.append(f"{f}:{i}: names the deployed policy '{policy}' -- say 'the deployed policy' and link docs/STATUS.md")
        if published(f) and f not in GENERATED_PAGES:
            for i, level, _t in md_headings.parse_headings(text):
                if level == 2 and re.match(r"^##\s", text.split("\n")[i]):
                    errors.append(f"{f}:{i + 1}: a `##` section heading in a published page -- write the title on its own line over a line of `---` (python tools/md_headings.py {f} converts it)")
        if published(f):
            warnings += readability_warnings(f, text)
        if f.startswith("docs/") and not f.startswith(("docs/plan-detail/", "docs/rl/", "docs/archive/", "docs/planned/", "docs/guides/", "docs/hardware/", "docs/research/")) and f != "docs/README.md" \
                and inbound.get(f, 0) == 0:
            warnings.append(f"{f}: orphan page -- no other page links to it (add it to docs/README.md)")
    return errors, warnings


def backlog_errors(root):
    """docs/backlog.md is generated from the item headings; fail if it is stale (only for the real repo tree)."""
    try:
        import gen_backlog
    except ImportError:
        return []
    if os.path.realpath(root) != os.path.realpath(gen_backlog.ROOT):
        return []
    target = os.path.join(root, "docs", "backlog.md")
    cur = open(target).read() if os.path.exists(target) else ""
    if cur != gen_backlog.build():
        return ["docs/backlog.md is out of date with the item headings -- run: python tools/gen_backlog.py"]
    return []


def helpers_doc_errors(root):
    """docs/guides/shell-helpers.md is generated from tools/g2_aliases.sh; fail if it is stale (only for the real repo tree)."""
    try:
        import gen_helpers_doc
    except ImportError:
        return []
    if os.path.realpath(root) != os.path.realpath(gen_helpers_doc.ROOT):
        return []
    target = os.path.join(root, "docs", "guides", "shell-helpers.md")
    cur = open(target).read() if os.path.exists(target) else ""
    if cur != gen_helpers_doc.build():
        return ["docs/guides/shell-helpers.md is out of date with tools/g2_aliases.sh -- run: python tools/gen_helpers_doc.py"]
    return []


def env_reference_errors(root):
    """docs/guides/env-reference.md is generated from the source; fail if it is stale (only for the real repo tree)."""
    try:
        import gen_env_reference
    except ImportError:
        return []
    if os.path.realpath(root) != os.path.realpath(gen_env_reference.ROOT):
        return []
    target = os.path.join(root, "docs", "guides", "env-reference.md")
    cur = open(target).read() if os.path.exists(target) else ""
    if cur != gen_env_reference.build():
        return ["docs/guides/env-reference.md is out of date with the code -- run: python tools/gen_env_reference.py"]
    return []


def cheatsheet_errors(root):
    """The cheat sheet stays a quick reference (examples you can copy, short descriptions, real aliases) and its A to Z index is current (tools/gen_cheatsheet_index.py; only for the real repo tree)."""
    try:
        import gen_cheatsheet_index as g
    except ImportError:
        return []
    if os.path.realpath(root) != os.path.realpath(g.ROOT):
        return []
    out = g.errors(root)
    target = os.path.join(root, "docs", "guides", "cheatsheet.md")
    cur = open(target).read() if os.path.exists(target) else ""
    if cur != g.build(root):
        out.append("docs/guides/cheatsheet.md: the A to Z index is out of date -- run: python tools/gen_cheatsheet_index.py")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--root", default=None)
    ap.add_argument("--quiet-warnings", action="store_true")
    ap.add_argument("--notes", action="store_true", help="list the note-style wording in published pages, line by line")
    args = ap.parse_args()
    root = args.root or subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() \
        or os.getcwd()
    files = md_files(root, staged=args.staged)
    if args.notes:
        total = 0
        for f in files:
            if published(f) and f not in GENERATED_PAGES:
                for n, cat, m in note_voice_hits(open(os.path.join(root, f), encoding="utf-8").read()):
                    print(f"{f}:{n}: {cat}: {m}")
                    total += 1
        print(f"{total} hit(s)")
        return 0
    errors, warnings = check(root, files)
    errors += backlog_errors(root)
    errors += helpers_doc_errors(root)
    errors += env_reference_errors(root)
    errors += cheatsheet_errors(root)
    if not args.quiet_warnings:
        for w in warnings:
            print(f"warning: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"check_docs: {len(files)} file(s) checked, {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
