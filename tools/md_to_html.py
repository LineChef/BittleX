#!/usr/bin/env python3
"""Turn one of our Markdown docs into a single self-contained HTML page (light and dark, tables scroll on a narrow window), with no Markdown package needed.

    python tools/md_to_html.py docs/research/xiaozhi-vendor-docs.md OUT.html docs/research

The third argument is the folder of the source file inside the repo: relative links such as `../plan-detail/x.md` are turned into links to that file on GitHub (the page is read away from the repo).
It handles what our docs use: headings, tables, flat lists, bold, inline code and links. A document with its own "Contents" section gets no second contents box. The page is a snapshot; the Markdown file stays the source of truth.
"""
import html, posixpath, re, sys

SRC, OUT, BASE = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "x")
SRC_DIR = BASE if BASE != "x" else "docs/plan-detail"


def link_target(u):
    if re.match(r"https?://", u) or u.startswith("#"):
        return u
    path = posixpath.normpath(posixpath.join(SRC_DIR, u))
    return f"https://github.com/LineChef/BittleX/blob/development/{path}"


def inline(t):
    t = html.escape(t, quote=False)
    codes = []
    def keep(m):
        codes.append(m.group(1)); return f"\x00{len(codes)-1}\x00"
    t = re.sub(r"`([^`]+)`", keep, t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: f'<a href="{html.escape(link_target(html.unescape(m.group(2))), quote=True)}">{m.group(1)}</a>', t)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{codes[int(m.group(1))]}</code>", t)


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"<[^>]+>", "", t).lower()).strip("-")


lines = open(SRC, encoding="utf-8").read().splitlines()
body, toc, i, title = [], [], 0, ""
while i < len(lines):
    l = lines[i]
    if not l.strip():
        i += 1; continue
    m = re.match(r"(#{1,3}) (.+)", l)
    if m:
        lvl, txt = len(m.group(1)), m.group(2)
        if lvl == 1:
            title = re.sub(r"<[^>]+>", "", inline(txt))
            body.append(f"<h1>{inline(txt)}</h1>")
        else:
            sid = slug(inline(txt))
            if lvl == 2:
                toc.append((sid, re.sub(r"<[^>]+>", "", inline(txt))))
            body.append(f'<h{lvl} id="{sid}">{inline(txt)}</h{lvl}>')
        i += 1; continue
    if l.startswith("|"):
        rows = []
        while i < len(lines) and lines[i].startswith("|"):
            rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")]); i += 1
        head, data = rows[0], [r for r in rows[2:]]
        t = "<div class='tw'><table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
        for r in data:
            t += "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
        body.append(t + "</tbody></table></div>"); continue
    if re.match(r"- ", l) or re.match(r"\d+\. ", l):
        ordered = bool(re.match(r"\d+\. ", l))
        items = []
        while i < len(lines) and (re.match(r"- ", lines[i]) if not ordered else re.match(r"\d+\. ", lines[i])):
            items.append(re.sub(r"^(- |\d+\. )", "", lines[i])); i += 1
        tag = "ol" if ordered else "ul"
        body.append(f"<{tag}>" + "".join(f"<li>{inline(x)}</li>" for x in items) + f"</{tag}>"); continue
    para = [l]; i += 1
    while i < len(lines) and lines[i].strip() and not re.match(r"(#{1,3} |\||- |\d+\. )", lines[i]):
        para.append(lines[i]); i += 1
    body.append(f"<p>{inline(' '.join(para))}</p>")

has_own_toc = any(t == "Contents" for _, t in toc)
toc_html = "".join(f'<li><a href="#{sid}">{html.escape(t)}</a></li>' for sid, t in toc)
nav_html = "" if has_own_toc else f"<nav><strong>Contents</strong><ol>{toc_html}</ol></nav>"
page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--bg:#f6f7f6;--surface:#fff;--ink:#14201e;--ink2:#41524d;--muted:#72827d;--line:#dce3e0;--accent:#0b6b62;--code:#eef2f0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1514;--surface:#172120;--ink:#e8efed;--ink2:#b2c0bb;--muted:#869590;--line:#2a3836;--accent:#4fc4b6;--code:#1f2c2a;color-scheme:dark}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 system-ui,-apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:1040px;margin:0 auto;padding:28px 16px 90px}}
h1{{font-size:1.7rem;line-height:1.25;margin:0 0 14px}}
h2{{font-size:1.3rem;margin:38px 0 10px;padding-top:14px;border-top:2px solid var(--accent);color:var(--accent)}}
h3{{font-size:1.05rem;margin:22px 0 6px}}
p,li{{color:var(--ink)}} li{{margin:4px 0}} ul,ol{{padding-left:1.4rem}}
a{{color:var(--accent)}} strong{{color:var(--ink)}}
code{{background:var(--code);border-radius:4px;padding:1px 5px;font:.88em ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}}
.tw{{overflow-x:auto;margin:14px 0;border:1px solid var(--line);border-radius:8px;background:var(--surface)}}
table{{border-collapse:collapse;width:100%;font-size:.93rem}}
th,td{{text-align:left;vertical-align:top;padding:9px 12px;border-bottom:1px solid var(--line)}}
th{{background:var(--code);font-weight:600;white-space:nowrap}} tr:last-child td{{border-bottom:0}}
nav{{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:6px 18px;margin:18px 0 8px}}
nav ol{{columns:2;column-gap:28px;margin:8px 0;padding-left:1.2rem}} nav li{{font-size:.93rem;margin:2px 0;break-inside:avoid}}
.note{{color:var(--muted);font-size:.85rem;margin-top:34px}}
@media (max-width:640px){{nav ol{{columns:1}} th{{white-space:normal}}}}
</style></head><body><div class="wrap">
{body[0]}
{nav_html}
{chr(10).join(body[1:])}
<p class="note">Generated from <code>docs/planned/ai-head/ai-head-implementation.md</code>. The Markdown file in the repository is the source of truth; edit that, not this page.</p>
</div></body></html>"""
open(OUT, "w", encoding="utf-8").write(page)
print(len(page), "bytes,", len(toc), "sections,", sum(1 for b in body if b.startswith("<div class='tw'>")), "tables")
