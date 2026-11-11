#!/usr/bin/env python3
"""Build the docs bundle: every documentation page in the repo as site-ready content for a React (or any) front end. Stdlib only.

    python tools/build_docs_bundle.py [--out build/docs-bundle] [--base /docs] [--assets-url URL] [--repo-url URL] [--branch development] [--no-check]

Reads git-tracked files only (nothing gitignored, no CLAUDE.md, no training data can reach it) and writes:

    latest.json          a tiny pointer: version, build time, the file names below (fetch this first; it is never cached for long)
    manifest.json        the navigation tree and every page's route, title, section, summary, headings and last-changed date
    search.json          one plain-text record per page for a client-side search library
    schema.json          the JSON Schema of latest.json, manifest.json and search.json (source: docs/guides/docs-bundle.schema.json)
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import img_info  # noqa: E402
import md_headings  # noqa: E402
import md_render  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

GIT_EXES = ("git", "/Library/Developer/CommandLineTools/usr/bin/git")
ASSET_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".html"}
CODE_READMES = ("pi_pipeline/README.md", "tools/README.md", "rl_training/README.md", "rl_training/opencat-gym/reference_gait/README.md")
FOLDER_TITLES = {"hardware/build-logs": "Build logs", "code": "Code", "legal": "Legal"}
# The short titles the site's navigation shows (docs/nav-titles.json: route -> title). A page keeps its full `title`; its nav node and its `navTitle` use the short one. A top-level node is one or two words,
# a child is at most four words and 30 characters, so the sidebar does not wrap; the build refuses anything longer.
NAV_TITLES_FILE = os.path.join(ROOT, "docs", "nav-titles.json")
NAV_TOP_WORDS, NAV_TOP_CHARS, NAV_CHILD_WORDS, NAV_CHILD_CHARS = 2, 22, 4, 30


INLINE_SVG_MAX = 30 * 1024          # an SVG figure up to this size is written into the page's HTML so the site's CSS and dark mode reach it
NAV_ORDER_FILE = os.path.join(ROOT, "docs", "nav-order.json")


def load_nav_order():
    """docs/nav-order.json: for a folder route (or "top"), a list of [group label, [child routes in order]]. Most important first. A child that is not listed fails the build, so every page has a deliberate place."""
    try:
        return json.load(open(NAV_ORDER_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_nav_titles():
    try:
        return json.load(open(NAV_TITLES_FILE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def nav_title_problems(nodes, depth=0):
    """Titles in the nav tree that are too long to fit the sidebar: [(route, title, why)]."""
    bad = []
    for n in nodes:
        words, chars = len(n["title"].split()), len(n["title"])
        lw, lc = (NAV_TOP_WORDS, NAV_TOP_CHARS) if depth == 0 else (NAV_CHILD_WORDS, NAV_CHILD_CHARS)
        if words > lw or chars > lc:
            bad.append((n["route"], n["title"], f"{'top-level' if depth == 0 else 'child'} nav titles are at most {lw} words and {lc} characters"))
        bad += nav_title_problems(n.get("children", []), depth + 1)
    return bad
# Top-level order and sidebar groups (a top-level node's `group`): what a newcomer reads first, then how to build and run G2, then the internals.
TOP_LAYOUT = [("Start here", ["how-it-works", "capabilities", "STATUS", "project-plan"]),
              ("Build and operate", ["guides", "hardware", "vision", "blueprints"]),
              ("Under the hood", ["architecture", "rl", "code"]),
              ("About", ["about", "legal"])]
# Working notes stay in the repo but never reach the site: plans, backlogs, history, outside-project reviews, run logs.
EXCLUDED_DIRS = ("docs/plan-detail/", "docs/planned/", "docs/archive/", "docs/research/", "docs/hardware/build-logs/")
EXCLUDED_FILES = {"docs/vision/capture-progress.md", "docs/vision/wall-check-plan.md", "docs/backlog.md", "docs/maintaining-docs.md", "docs/rl/real-walk-log.md", "docs/rl/hw1-log.md",
                  "docs/rl/carpet-findings-2026-10-20.md", "docs/rl/getup-sim-replay.md", "docs/rl/h1-rubric.md", "docs/rl/sysid-capture-plan.md",
                  "docs/rl/training-upgrade-2026-10.md"}
# Who a page is for and what it is, by section; a page's front matter (`audience:` / `kind:`) overrides these.
AUDIENCES = ["visitor", "builder", "contributor"]
KINDS = ["overview", "guide", "reference", "concept"]
SECTION_DEFAULTS = {"overview": ("visitor", "overview"), "specification": ("contributor", "reference"), "guides": ("builder", "guide"), "hardware": ("builder", "reference"),
                    "vision": ("builder", "reference"), "rl": ("contributor", "concept"), "blueprints": ("builder", "guide"),
                    "code": ("contributor", "reference"), "legal": ("visitor", "reference"), "about": ("visitor", "overview")}
LEFT_OUT = "left-out page: "
LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+)((?:\s+\"[^\"]*\")?\))")
FENCE = re.compile(r"^(```|~~~)")
# The closed sets the schema (docs/guides/docs-bundle.schema.json, shipped as schema.json) promises; the build refuses a value outside them, so the schema cannot drift.
SECTIONS = ["overview", "specification", "guides", "hardware", "vision", "rl", "blueprints", "code", "legal", "about"]
ASSET_KINDS = ["png", "jpg", "jpeg", "gif", "svg", "pdf", "html"]      # one per ASSET_EXT; the files in the bundle today are html and pdf
SUMMARY_MAX = 220


def git(*args):
    for exe in GIT_EXES:
        try:
            r = subprocess.run([exe, *args], cwd=ROOT, capture_output=True, text=True)
        except OSError:
            continue
        if r.returncode == 0:
            return r.stdout
    return ""


def unemphasize(text):
    """Drop Markdown emphasis marks (backticks, asterisks, and underscores at a word edge) but keep underscores inside names (pi_pipeline, gait_mode.py)."""
    return re.sub(r"(?<!\w)_+|_+(?!\w)", "", re.sub(r"[`*]", "", text))


def slug(text):
    """GitHub-style heading id (what rehype-slug / github-slugger produce): lower case, markup marks and punctuation other than hyphens and underscores removed, each space a hyphen."""
    s = unemphasize(text.strip().lower())
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
    if path.startswith("docs/"):
        parts = path.split("/")
        return parts[1] if len(parts) > 2 else "overview"
    if path.startswith("blueprints/"):
        return "blueprints"
    if route.startswith("code/"):
        return "code"
    if route.startswith("legal/"):
        return "legal"
    return "about"


def is_page(path):
    if not path.endswith(".md"):
        return False
    return route_for(path) is not None


def is_excluded(path):
    """True for working notes: kept in the repo, never published in the bundle."""
    return path in EXCLUDED_FILES or path.startswith(EXCLUDED_DIRS)


def parse_front(text):
    """Split optional `---` front matter (flat `key: value` lines) from a page. Returns (meta, body)."""
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).split("\n"):
        k, _, v = line.partition(":")
        if k.strip() and v.strip():
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def is_asset(path):
    return not is_excluded(path) and path.startswith(("docs/", "blueprints/")) and os.path.splitext(path)[1].lower() in ASSET_EXT


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
        if is_excluded(res_clean) or is_excluded(res_clean + "/"):
            warnings.append(f"{LEFT_OUT}{src}: links to a working note that is not published: {target}")
            return m.group(0)
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
    for _i, level, t in md_headings.parse_headings(text):
        if level == 1:
            return md_headings.unescape(t).strip()
    return fallback


def headings_of(text):
    hs = []
    for _i, level, raw in md_headings.parse_headings(text):
        if level in (2, 3):
            raw = md_headings.unescape(raw)
            t = re.sub(r"[`*]", "", raw).strip()
            hs.append({"level": level, "text": t, "id": slug(raw)})
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
    t = unemphasize(t)
    if len(t) <= SUMMARY_MAX:
        return t
    cut = t[:SUMMARY_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-—–")     # cut at a word boundary, never mid-word
    return cut + "…"


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
    heads = {i: (lv, md_headings.unescape(t)) for i, lv, t in md_headings.parse_headings(readme_text)}
    for idx, line in enumerate(readme_text.split("\n")):
        if idx in heads and heads[idx][0] == 3:
            current = re.sub(r"[`*]", "", heads[idx][1]).strip()
            continue
        if idx in heads and heads[idx][0] <= 2:
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
    titles = load_nav_titles()
    nav_order, unplaced = load_nav_order(), []
    nodes = {r: {"route": r, "title": titles.get(r, e["title"]), "section": e["section"], "children": []} for r, e in entries.items()}
    folders = {}

    def folder(path):
        if path in folders:
            return folders[path]
        if path in nodes:
            folders[path] = nodes[path]
            return nodes[path]
        title = titles.get(path, FOLDER_TITLES.get(path, path.split("/")[-1]))
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
        listed = nav_order.get(n["route"])
        if listed and n["children"]:                  # an explicit order (docs/nav-order.json) replaces the README's order and groups
            by = {c["route"]: c for c in n["children"]}
            arranged = []
            for label, routes in listed:
                for r in routes:
                    c = by.pop(r, None)
                    if c is not None:
                        c.pop("group", None)
                        if label:
                            c["group"] = label
                        arranged.append(c)
            if by:
                unplaced.extend(sorted(by))
                arranged += sorted(by.values(), key=lambda c: c["title"].lower())
            n["children"] = arranged
        for c in n["children"]:
            finish(c)
        if not n["children"]:
            n.pop("children")
        elif not n["section"]:                       # a folder node has no page of its own: it takes its first child's section
            n["section"] = next((c["section"] for c in n["children"] if c["section"]), "")
    top = {}
    for n in roots:
        top[n["route"]] = n
    ordered = []
    if home:
        ordered.append(home)
    for label, names in (nav_order.get("top") or TOP_LAYOUT):
        for name in names:
            if name in top:
                n = top.pop(name)
                n["group"] = label
                ordered.append(n)
    ordered += [top[k] for k in sorted(top)]
    for n in ordered:
        finish(n)
    if unplaced:
        raise SystemExit("pages with no place in the navigation order (add them to docs/nav-order.json):\n  " + "\n  ".join(unplaced))
    return ordered


def build(out, base, gh, branch, check=True, assets_url=None):
    if check:
        r = subprocess.run([sys.executable, os.path.join(HERE, "check_docs.py")], cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            print(r.stdout + r.stderr)
            raise SystemExit("check_docs failed: not building a bundle from broken docs")
    tracked = [f for f in git("ls-files").splitlines() if f]
    pages = {p: route_for(p) for p in tracked if is_page(p) and not is_excluded(p) and os.path.exists(os.path.join(ROOT, p))}
    assets = {p for p in tracked if is_asset(p) and os.path.exists(os.path.join(ROOT, p))}
    assets_url = (assets_url or f"{base}/_assets").rstrip("/")
    warnings, entries, bodies, search = [], {}, {}, []
    image_users = {}
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(os.path.join(out, "pages"))
    digest = hashlib.sha256()
    for src, route in sorted(pages.items()):
        meta, raw = parse_front(open(os.path.join(ROOT, src), encoding="utf-8").read())
        text = rewrite_links(raw, src, pages, assets, base, assets_url, gh, warnings, branch)
        title = title_of(raw, os.path.splitext(os.path.basename(src))[0])
        updated = git("log", "-1", "--format=%cs", "--", src).strip()
        section = section_for(src, route)
        d_aud, d_kind = SECTION_DEFAULTS.get(section, ("contributor", "reference"))
        audience, kind = meta.get("audience", d_aud), meta.get("kind", d_kind)
        if audience not in AUDIENCES or kind not in KINDS:
            raise SystemExit(f"{src}: front matter audience '{audience}' / kind '{kind}' must be one of {AUDIENCES} / {KINDS}")
        entries[route] = {"route": route, "title": title, "navTitle": load_nav_titles().get(route, title), "section": section, "source": src, "updated": updated, "audience": audience, "kind": kind,
                          "summary": summary_of(raw), "headings": headings_of(raw)}
        bodies[route] = raw
        dest = os.path.join(out, "pages", (route or "index") + ".md")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "w", encoding="utf-8").write(text)
        entries[route]["html"] = "pages/" + (route or "index") + ".html"
        used = []
        for m_ in re.finditer(r"!\[[^\]]*\]\(" + re.escape(assets_url) + r"/([^)\s]+)", text):
            if m_.group(1) not in used:
                used.append(m_.group(1))
        for u_ in used:
            image_users.setdefault(u_, []).append(route)
        if used:
            entries[route]["images"] = used

        def image_lookup(src, _assets_url=assets_url):
            if not src.startswith(_assets_url + "/"):
                return None
            repo = src[len(_assets_url) + 1:]
            full = os.path.join(ROOT, repo)
            wh = img_info.image_size(full)
            info = {"width": wh[0], "height": wh[1]} if wh else {}
            if repo.lower().endswith(".svg") and os.path.getsize(full) <= INLINE_SVG_MAX:
                svg = open(full, encoding="utf-8", errors="replace").read()
                if not img_info.svg_problems(svg):
                    info["svg"] = svg
            return info
        open(os.path.join(out, entries[route]["html"]), "w", encoding="utf-8").write(md_render.render(text, section=section, audience=audience, kind=kind, slugify=slug, images=image_lookup))      # the same page as semantic HTML (tools/md_render.py)
        digest.update(src.encode() + text.encode())
        search.append({"route": route, "title": title, "section": entries[route]["section"],
                       "headings": [h["text"] for h in entries[route]["headings"]], "text": plain_text(raw)[:4000]})
    leaks = [w for w in warnings if w.startswith(LEFT_OUT)]
    if leaks:
        raise SystemExit("published pages link to working notes that are not in the bundle:\n  " + "\n  ".join(w[len(LEFT_OUT):] for w in leaks))
    asset_list = []
    for a in sorted(assets):
        dest = os.path.join(out, "assets", a)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, a), dest)
        data = open(dest, "rb").read()
        digest.update(a.encode() + data)
        rec = {"path": a, "kind": os.path.splitext(a)[1].lstrip(".").lower(), "size": len(data)}
        wh = img_info.image_size(dest)
        if wh:
            rec["width"], rec["height"] = wh
        if a in image_users:
            rec["usedBy"] = sorted(set(image_users[a]))
        asset_list.append(rec)
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
    too_long = nav_title_problems(nav)
    if too_long:
        raise SystemExit("navigation titles too long for the sidebar (shorten them in docs/nav-titles.json):\n  " + "\n  ".join(f"{r or '(home)'}: {t!r}: {why}" for r, t, why in too_long))
    bad_sections = sorted({e["section"] for e in entries.values()} - set(SECTIONS))
    bad_kinds = sorted({a_["kind"] for a_ in asset_list} - set(ASSET_KINDS))

    def empty_sections(nodes):
        return [n["route"] for n in nodes if not n["section"]] + [r for n in nodes for r in empty_sections(n.get("children", []))]
    if bad_sections or bad_kinds or empty_sections(nav):
        raise SystemExit(f"bundle values outside the schema: sections {bad_sections}, asset kinds {bad_kinds}, nav nodes without a section {empty_sections(nav)}; "
                         "add the value to SECTIONS / ASSET_KINDS, docs/guides/docs-bundle.schema.json and docs/guides/docs-bundle.md together")

    def annotate(nodes, parent):
        """Copy each node's place in the tree onto its flat page entry, so a site can reorder from the flat list without walking `nav`."""
        for i, n in enumerate(nodes):
            n["order"] = i
            e = entries.get(n["route"])
            if e is not None:
                e["parent"], e["order"] = parent, i
                if "group" in n:
                    e["group"] = n["group"]
            annotate(n.get("children", []), n["route"])
    annotate(nav, None)
    built = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    manifest = {"version": version, "built": built, "repo": gh, "branch": branch, "base": base, "assetsUrl": assets_url,
                "pages": [entries[r] for r in sorted(entries)], "nav": nav, "assets": asset_list}
    json.dump(manifest, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    json.dump(search, open(os.path.join(out, "search.json"), "w"))
    shutil.copyfile(os.path.join(ROOT, "docs", "guides", "docs-bundle.schema.json"), os.path.join(out, "schema.json"))
    json.dump({"version": version, "built": built, "manifest": "manifest.json", "search": "search.json", "schema": "schema.json", "pageCount": len(entries),
               "assetCount": len(asset_list)}, open(os.path.join(out, "latest.json"), "w"), indent=1)
    open(os.path.join(out, ".nojekyll"), "w").close()
    return manifest, warnings


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "docs-bundle"))
    ap.add_argument("--base", default="/docs", help="the URL path the site serves the docs under")
    ap.add_argument("--assets-url", default=None, help="where the bundle's assets/ folder is served (default <base>/_assets); an absolute URL such as https://host/BittleX/assets makes every image link work without a route in the site")
    ap.add_argument("--repo-url", default=None)
    ap.add_argument("--branch", default="development")
    ap.add_argument("--no-check", action="store_true")
    a = ap.parse_args()
    manifest, warnings = build(a.out, a.base.rstrip("/"), repo_url(a.repo_url), a.branch, check=not a.no_check, assets_url=a.assets_url)
    for w in warnings:
        print("warning:", w)
    print(f"bundle {manifest['version']}: {len(manifest['pages'])} pages, {len(manifest['assets'])} assets, {len(warnings)} warning(s) -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
