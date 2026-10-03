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
WARNINGS (printed, never fail):
  * a link whose #anchor matches no heading in the target page
  * a docs page that no other page links to (an orphan)

The rule behind the volatile-fact checks: a fact that changes belongs in ONE place (docs/STATUS.md for what is deployed and
what is true now; the code for the policy name; `pytest` for test results). Dated logs (docs/rl, docs/plan-detail, docs/history.md,
docs/research, blueprints) record what was true then and are exempt. See docs/README.md, "Where to update what".
Bypass a genuine false positive with `git commit --no-verify`.
"""
import argparse
import os
import re
import subprocess
import sys

SKIP_DIRS = {".git", ".venv", "node_modules", ".pytest_cache", "__pycache__", "trained"}
# pages that must not carry hard-coded counts / the current policy name (everything else is a log, a record, or generated)
VOLATILE_FREE = ("README.md", "docs/README.md", "docs/STATUS.md", "docs/capabilities.md", "docs/how-it-works.md",
                 "docs/project-plan.md", "docs/backlog.md", "docs/guides/", "docs/hardware/", "pi_pipeline/")
COUNT_RE = re.compile(r"\b\d{2,4}\s+(?:passing\s+)?tests\b|\b\d{2,4}\s+passing\b", re.I)
LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def md_files(root, staged=False):
    if staged:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], cwd=root,
                             capture_output=True, text=True).stdout.split()
        return sorted(f for f in out if f.endswith(".md") and os.path.exists(os.path.join(root, f)))
    found = []
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
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
    infence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            infence = not infence
            continue
        m = None if infence else re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            s = slug(m.group(1))
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
        if f.startswith("docs/") and not f.startswith(("docs/plan-detail/", "docs/rl/")) and f != "docs/README.md" \
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--root", default=None)
    ap.add_argument("--quiet-warnings", action="store_true")
    args = ap.parse_args()
    root = args.root or subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() \
        or os.getcwd()
    files = md_files(root, staged=args.staged)
    errors, warnings = check(root, files)
    errors += backlog_errors(root)
    if not args.quiet_warnings:
        for w in warnings:
            print(f"warning: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    print(f"check_docs: {len(files)} file(s) checked, {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
