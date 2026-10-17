#!/usr/bin/env python3
"""Build the docs bundle: every documentation page in the repo as site-ready content for a React (or any) front end. Stdlib only.

    python tools/build_docs_bundle.py [--out build/docs-bundle] [--base /docs] [--repo-url URL] [--branch development] [--no-check]

Reads git-tracked files only (nothing gitignored, no CLAUDE.md, no training data can reach it) and writes:

    latest.json          a tiny pointer: version, build time, the file names below (fetch this first; it is never cached for long)
    manifest.json        the navigation tree and every page's route, title, section, summary, headings and last-changed date
    search.json          one plain-text record per page for a client-side search library
    pages/<route>.md     each page's Markdown, with links rewritten to site routes (pages/index.md is the home page)
    assets/<repo path>   images, PDFs and the standalone HTML pages, served by the site under `<base>/_assets/`

The format and how to load it: docs/guides/docs-bundle.md. The bundle is built on every push by .github/workflows/docs-bundle.yml.
"""
import argparse
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

GIT_EXES = ("git", "/Library/Developer/CommandLineTools/usr/bin/git")
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".html"}
CODE_READMES = ("pi_pipeline/README.md", "tools/README.md", "rl_training/README.md", "rl_training/opencat-gym/reference_gait/README.md")
TOP_ORDER = ["STATUS", "how-it-works", "architecture", "capabilities", "project-plan", "code-map", "backlog"]
FOLDER_TITLES = {"archive/plan-detail": "Archived plan write-ups", "archive/rl": "Archived training campaigns", "blueprints/build-logs": "Build logs",
                 "code": "Code READMEs", "legal": "Legal", "code/pi_pipeline": "Pi pipeline code"}
FOLDER_ORDER = ["guides", "hardware", "vision", "rl", "research", "plan-detail", "planned", "archive"]
LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))")
FENCE = re.compile(r"^(```|~~~)")


def git(*args):
    for exe in GIT_EXES:
        try:
            r = subprocess.run([exe, *args], cwd=ROOT, capture_output=True, text=True)
        except OSError:
            continue
        if r.returncode == 0:
            return r.stdout
    return ""


def slug(text):
    """GitHub-style heading id."""
    s = re.sub(r"[`*_]", "", text.strip().lower())
    s = re.sub(r"[^\w\- ]", "", s, flags=re.UNICODE)
    return s.replace(" ", "-")


def route_for(path):
    """Site route of a Markdown source path ('' is the home page), or None if the file is not a page."""
    if path == "README.md":
        return "about"
    if path == "THIRD_PARTY_NOTICES.md":
        return "legal/third-party-notices"
    stem = path[:-3]
    if path in CODE_READMES or (path.startswith("pi_pipeline/") and path.endswith("/README.md") and "/tests/" not in path):
        return "code/" + posixpath.dirname(path)
    if path.startswith("docs/"):
        rest = stem[len("docs/"):]
        if rest == "README":
            return ""
        return rest[:-len("/README")] if rest.endswith("/README") else rest
    if path.startswith("blueprints/"):
        return stem[:-len("/README")] if stem.endswith("/README") else stem
    return None


def section_for(path, route):
    if route == "":
        return "overview"
    if path.startswith("docs/archive/"):
        return "archive"
    if path.startswith("docs/planned/"):
        return "planned"
    if path.startswith("docs/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 2 else "overview"
    if path.startswith("blueprints/"):
        return "blueprints"
    if route.startswith("code/"):
        return "code"
    return "about"


def is_page(path):
    if not path.endswith(".md"):
        return False
    if path.startswith("docs/rl/real-walk-data/") and not path.endswith("README.md"):
        return False
    return route_for(path) is not None


def is_asset(path):
    return path.startswith(("docs/", "blueprints/")) and os.path.splitext(path)[1].lower() in ASSET_EXT


def repo_url(arg):
    if arg:
        return arg.rstrip("/")
    u = git("config", "--get", "remote.origin.url").strip()
    u = re.sub(r"^git@github\.com:", "https://github.com/", u)
    return re.sub(r"\.git$", "", u).rstrip("/")


def rewrite_links(text, src, pages, assets, base, assets_url, gh, warnings, branch="{branch}"):
    """Rewrite relative links in Markdown `text` (from repo path `src`) to site routes, asset URLs or GitHub links."""
    out, fenced = [], False
    srcdir = posixpath.dirname(src)

    def fix(m):
        pre, target, post = m.group(1), m.group(2), m.group(3)
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith(("#", "/")):
            return m.group(0)
        path, _, anchor = target.partition("#")
        frag = ("#" + anchor) if anchor else ""
        res = posixpath.normpath(posixpath.join(srcdir, path)) if path else src
        res_clean = res.rstrip("/")
        if res_clean in pages:
            r = pages[res_clean]
            return f"{pre}{base}{('/' + r) if r else ''}{frag}{post}"
        if res_clean in assets:
            return f"{pre}{assets_url}/{res_clean}{frag}{post}"
        if os.path.isdir(os.path.join(ROOT, res_clean)):
            for cand in (res_clean + "/README.md",):
                if cand in pages:
                    r = pages[cand]
                    return f"{pre}{base}{('/' + r) if r else ''}{frag}{post}"
            return f"{pre}{gh}/tree/{branch}/{res_clean}{post}"
        if os.path.exists(os.path.join(ROOT, res_clean)):
            return f"{pre}{gh}/blob/{branch}/{res_clean}{frag}{post}"
        warnings.append(f"{src}: link target not found: {target}")
        return m.group(0)

    for line in text.split("\n"):
        if FENCE.match(line.strip()):
            fenced = not fenced
            out.append(line)
            continue
        out.append(line if fenced else LINK.sub(fix, line))
    return "\n".join(out)


def title_of(text, fallback):
    for line in text.split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def headings_of(text):
    hs, fenced = [], False
    for line in text.split("\n"):
        if FENCE.match(line.strip()):
            fenced = not fenced
            continue
        m = None if fenced else re.match(r"^(#{2,3})\s+(.*)$", line)
        if m:
            t = re.sub(r"[`*]", "", m.group(2)).strip()
            hs.append({"level": len(m.group(1)), "text": t, "id": slug(m.group(2))})
    return hs


def summary_of(text):
    para, fenced = [], False
    for line in text.split("\n"):
        s = line.strip()
        if FENCE.match(s):
            fenced = not fenced
            continue
        if fenced or s.startswith(("#", "|", ">", "-", "*", "!", "<")) or not s:
            if para:
                break
            continue
        para.append(s)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", " ".join(para))
    return re.sub(r"[`*_]", "", t)[:220]


def plain_text(text):
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"[`*_>#|]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def order_children(children, readme_text, readme_src, pages):
    """Order sibling nodes: by first appearance in the folder README's links, then alphabetically."""
    rank = {}
    if readme_text:
        srcdir = posixpath.dirname(readme_src)
        for m in LINK.finditer(readme_text):
            t = m.group(2).split("#")[0]
            if not t or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", t):
                continue
            res = posixpath.normpath(posixpath.join(srcdir, t)).rstrip("/")
            r = pages.get(res) if res in pages else pages.get(res + "/README.md")
            if r is not None and r not in rank:
                rank[r] = len(rank)
    return sorted(children, key=lambda n: (rank.get(n["route"], 10_000), n["title"].lower()))


def groups_of(readme_text, readme_src, pages):
    """Sidebar groups: a `###` heading in a folder README labels the pages linked under it, until the next heading of level 2 or 3."""
    groups, current = {}, None
    srcdir = posixpath.dirname(readme_src)
    for line in readme_text.split("\n"):
        if re.match(r"^###\s+", line):
            current = re.sub(r"[`*]", "", line[4:]).strip()
            continue
        if re.match(r"^#{1,2}\s+", line):
            current = None
            continue
        if current:
            for m in LINK.finditer(line):
                t = m.group(2).split("#")[0]
                if not t or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", t):
                    continue
                res = posixpath.normpath(posixpath.join(srcdir, t)).rstrip("/")
                r = pages.get(res) if res in pages else pages.get(res + "/README.md")
                if r is not None and r not in groups:
                    groups[r] = current
    return groups


def build_nav(entries, bodies, pages):
    """entries: route -> entry. Returns a nested nav list."""
    nodes = {r: {"route": r, "title": e["title"], "section": e["section"], "children": []} for r, e in entries.items()}
    folders = {}

    def folder(path):
        if path in folders:
            return folders[path]
        if path in nodes:
            folders[path] = nodes[path]
            return nodes[path]
        title = FOLDER_TITLES.get(path, path.split("/")[-1])
        n = {"route": path, "title": title, "section": "", "children": [], "folder": True}
        folders[path] = n
        parent = folder(posixpath.dirname(path)) if posixpath.dirname(path) else None
        (parent["children"] if parent else roots).append(n)
        return n

    roots = []
    home = nodes.get("")
    for r, n in sorted(nodes.items()):
        if r == "":
            continue
        d = posixpath.dirname(r)
        is_index = entries[r]["source"].endswith("/README.md") and r != "about"
        if is_index:
            folders[r] = n
            d = posixpath.dirname(r)
        if d:
            folder(d)["children"].append(n) if (d not in nodes or True) else None
        else:
            roots.append(n)
    # detach nodes wrongly added as children of themselves, then order
    def finish(n):
        n["children"] = [c for c in n["children"] if c is not n]
        readme_src = entries.get(n["route"], {}).get("source", "")
        txt = bodies.get(n["route"]) if readme_src.endswith("/README.md") else None
        n["children"] = order_children(n["children"], txt, readme_src, pages)
        if txt:
            g = groups_of(txt, readme_src, pages)
            for c in n["children"]:
                if c["route"] in g:
                    c["group"] = g[c["route"]]
        for c in n["children"]:
            finish(c)
        if not n["children"]:
            n.pop("children")
        n.pop("folder", None)
    top = {}
    for n in roots:
        top[n["route"]] = n
    ordered = []
    if home:
        ordered.append(home)
    for name in TOP_ORDER:
        if name in top:
            ordered.append(top.pop(name))
    for name in FOLDER_ORDER + ["blueprints", "code", "legal"]:
        if name in top:
            ordered.append(top.pop(name))
    ordered += [top[k] for k in sorted(top)]
    for n in ordered:
        finish(n)
    return ordered


def build(out, base, gh, branch, check=True):
    if check:
        r = subprocess.run([sys.executable, os.path.join(HERE, "check_docs.py")], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            raise SystemExit("check_docs failed: not building a bundle from broken docs")
    tracked = [f for f in git("ls-files").splitlines() if f]
    pages = {p: route_for(p) for p in tracked if is_page(p) and os.path.exists(os.path.join(ROOT, p))}
    assets = {p for p in tracked if is_asset(p) and os.path.exists(os.path.join(ROOT, p))}
    assets_url = f"{base}/_assets"
    warnings, entries, bodies, search = [], {}, {}, []
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "pages"))
    digest = hashlib.sha256()
    for src, route in sorted(pages.items()):
        raw = open(os.path.join(ROOT, src), encoding="utf-8").read()
        text = rewrite_links(raw, src, pages, assets, base, assets_url, gh, warnings, branch)
        title = title_of(raw, os.path.splitext(os.path.basename(src))[0])
        updated = git("log", "-1", "--format=%cs", "--", src).strip()
        entries[route] = {"route": route, "title": title, "section": section_for(src, route), "source": src, "updated": updated,
                          "summary": summary_of(raw), "headings": headings_of(raw)}
        bodies[route] = raw
        dest = os.path.join(out, "pages", (route or "index") + ".md")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w", encoding="utf-8").write(text)
        digest.update(src.encode() + text.encode())
        search.append({"route": route, "title": title, "section": entries[route]["section"],
                       "headings": [h["text"] for h in entries[route]["headings"]], "text": plain_text(raw)[:4000]})
    asset_list = []
    for a in sorted(assets):
        dest = os.path.join(out, "assets", a)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, a), dest)
        data = open(dest, "rb").read()
        digest.update(a.encode() + data)
        asset_list.append({"path": a, "kind": os.path.splitext(a)[1].lstrip(".").lower(), "size": len(data)})
    privacy = os.path.join(ROOT, ".gitprivacy-terms")
    if os.path.exists(privacy):
        # whole-word match; a term written with a capital is matched with that capital (a name), so the same word in lowercase is not a hit
        terms = [t.strip() for t in open(privacy, encoding="utf-8") if t.strip() and not t.lstrip().startswith("#")]
        blob = "\n".join(open(os.path.join(out, "pages", (r or "index") + ".md"), encoding="utf-8").read() for r in entries)
        for a_ in asset_list:
            if a_["kind"] == "html":
                blob += "\n" + open(os.path.join(out, "assets", a_["path"]), encoding="utf-8", errors="replace").read()
        bad = [t for t in terms if re.search(r"(?<![A-Za-z0-9_])" + re.escape(t) + r"(?![A-Za-z0-9_])", blob, 0 if t[0].isupper() else re.I)]
        if bad:
            raise SystemExit(f"{len(bad)} private term(s) found in the bundle; not publishing (run the pre-commit privacy check)")
    version = digest.hexdigest()[:12]
    nav = build_nav(entries, bodies, pages)
    built = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest = {"version": version, "built": built, "repo": gh, "branch": branch, "base": base, "assetsUrl": assets_url,
                "pages": [entries[r] for r in sorted(entries)], "nav": nav, "assets": asset_list}
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    json.dump(search, open(os.path.join(out, "search.json"), "w"))
    json.dump({"version": version, "built": built, "manifest": "manifest.json", "search": "search.json", "pageCount": len(entries),
               "assetCount": len(asset_list)}, open(os.path.join(out, "latest.json"), "w"), indent=1)
    open(os.path.join(out, ".nojekyll"), "w").close()
    return manifest, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "docs-bundle"))
    ap.add_argument("--base", default="/docs", help="the URL path the site serves the docs under")
    ap.add_argument("--repo-url", default=None)
    ap.add_argument("--branch", default="development")
    ap.add_argument("--no-check", action="store_true")
    a = ap.parse_args()
    manifest, warnings = build(a.out, a.base.rstrip("/"), repo_url(a.repo_url), a.branch, check=not a.no_check)
    for w in warnings:
        print("warning:", w)
    print(f"bundle {manifest['version']}: {len(manifest['pages'])} pages, {len(manifest['assets'])} assets, {len(warnings)} warning(s) -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
