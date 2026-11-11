"""Render a docs page's markdown as semantic HTML, so the site can style the page by tag. Stdlib only. No class names are written; the site adds wrappers and classes if it wants them.

The docs use a small subset of markdown (headings, paragraphs, bulleted and numbered lists, block quotes, fenced code, links, images, inline code, emphasis), so this renderer covers that subset
and nothing else; text it does not recognise is escaped, never passed through. `render()` returns one `<article>` element:

    article[data-section][data-audience][data-kind]
      h1 ... h6[id]                      the page's own headings; the id is the heading's anchor slug
      p                                  a paragraph
      h4                                 a title that opens a list item or a paragraph ("Run G2 day to day: ..."): the text before its first colon, without the colon; the rest follows in a <p>
      ul > li, ol > li                   lists; an item with a title is <li><h4>Title</h4><p>rest</p>(nested list)</li>
      aside[data-callout]                from `> [!NOTE]`, `[!TIP]`, `[!IMPORTANT]`, `[!WARNING]`, `[!CAUTION]`; its first child is <h4>Note</h4>
      blockquote                         any other block quote
      pre[data-lang] > code              a fenced code block
      figure > img[src][alt][width][height][loading], figcaption     an image alone in a paragraph; the figcaption is its markdown title (`![Alt](file.png "Caption")`)
      figure > svg[role="img"][aria-label]                           a small SVG file is inlined so the site's CSS reaches it (see `images` below)
      code, a[href], img[src][alt], em, strong, hr

`render(..., images=fn)`: `fn(src)` returns None for an image it knows nothing about, or a dict with optional `width`, `height` and `svg` (the file's text, already checked). With it, a figure's
image gets `width` and `height` (no layout shift) and an SVG with `svg` text is inlined, its ids prefixed so two figures cannot collide.
"""
from __future__ import annotations

import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import md_headings  # noqa: E402

UNDER2, UNDER1 = md_headings.UNDER2, md_headings.UNDER1

ALERTS = {"NOTE": "note", "TIP": "tip", "IMPORTANT": "important", "WARNING": "warning", "CAUTION": "caution"}
FENCE = re.compile(r"^\s*(```|~~~)\s*([\w+-]*)\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
BULLET = re.compile(r"^(\s*)([-*])\s+(.*)$")
NUMBER = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
RULE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
LEAD = re.compile(r"^(?P<lead>[^:\n]{1,90}?):(?P<rest>\s.*|)$")


def slug(text: str) -> str:
    s = re.sub(r"[^\w\s-]", "", re.sub(r"<[^>]+>", "", text).lower())
    return re.sub(r"\s", "-", s.strip())


def inline(text: str) -> str:
    """Inline markdown to HTML: code spans first (their content is literal), then links and images, then emphasis."""
    spans: list[str] = []

    def stash(m):
        spans.append(f"<code>{html.escape(m.group(1))}</code>")
        return f"\x00{len(spans) - 1}\x00"
    t = re.sub(r"`([^`]+)`", stash, text)
    t = html.escape(t, quote=False)
    t = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)", lambda m: f'<img src="{html.escape(m.group(2), quote=True)}" alt="{html.escape(m.group(1), quote=True)}">', t)
    t = re.sub(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)", lambda m: f'<a href="{html.escape(m.group(2), quote=True)}">{m.group(1)}</a>', t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], t)


def lead_split(text: str):
    """(lead, rest) when the text opens with a short title and a colon ("Run G2 day to day: ..."), else None. A colon inside code, a link or a sentence does not count."""
    m = LEAD.match(text)
    if not m:
        return None
    lead = m.group("lead")
    if re.search(r"[.!?]\s|://|\bhttps?\b|[*\[\]]", lead) or lead.count("`") % 2 or lead.count("(") != lead.count(")") or lead.endswith((".", ",", ";")):
        return None
    return lead, m.group("rest")


def lead_html(text: str) -> tuple[str, bool]:
    sp = lead_split(text)
    if sp is None:
        return inline(text), False
    lead, rest = sp
    rest = rest.strip()
    return f"<h4>{inline(lead)}</h4>" + (f"<p>{inline(rest)}</p>" if rest else ""), True


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _list(lines: list[str], i: int, base: int) -> tuple[str, int]:
    """Render the list starting at lines[i] (indent `base`); return (html, next index)."""
    ordered = bool(NUMBER.match(lines[i]) and not BULLET.match(lines[i]))
    items = []                                   # (lead or None, text html, children html)
    while i < len(lines):
        m = (NUMBER if ordered else BULLET).match(lines[i])
        if not m or len(m.group(1)) != base:
            break
        i += 1
        body_lines, children = [m.group(3)], ""
        while i < len(lines):
            ln = lines[i]
            if not ln.strip():
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                if j < len(lines) and _indent(lines[j]) > base:
                    i = j
                    continue
                break
            if (BULLET.match(ln) or NUMBER.match(ln)) and _indent(ln) > base:
                sub, i = _list(lines, i, _indent(ln))
                children += sub
                continue
            if BULLET.match(ln) or NUMBER.match(ln):
                break
            if _indent(ln) > base or not (FENCE.match(ln) or HEADING.match(ln)):
                body_lines.append(ln.strip())
                i += 1
                continue
            break
        text = " ".join(body_lines)
        sp = lead_split(text)
        items.append((sp, text, children))
    if ordered:
        return "<ol>" + "".join(f"<li>{lead_html(t)[0]}{c}</li>" for _sp, t, c in items) + "</ol>", i
    return "<ul>" + "".join(f"<li>{lead_html(t)[0]}{c}</li>" for _sp, t, c in items) + "</ul>", i


IMG_ONLY = re.compile(r'^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)$')
_FIG_N = [0]


def _figure(m, images) -> str:
    alt, src, caption = m.group(1), m.group(2), m.group(3)
    info = images(src) if images else None
    cap = f"<figcaption>{inline(caption)}</figcaption>" if caption else ""
    if info and info.get("svg"):
        _FIG_N[0] += 1
        svg = info["svg"]
        pre = f"f{_FIG_N[0]}-"
        svg = re.sub(r'\bid="([^"]+)"', lambda x: f'id="{pre}{x.group(1)}"', svg)
        svg = re.sub(r'(href|xlink:href)="#([^"]+)"', lambda x: f'{x.group(1)}="#{pre}{x.group(2)}"', svg)
        svg = re.sub(r"url\(#([^)]+)\)", lambda x: f"url(#{pre}{x.group(1)})", svg)
        svg = re.sub(r"^<\?xml[^>]*>\s*|<!DOCTYPE[^>]*>\s*", "", svg.strip())
        svg = re.sub(r"<svg\b[^>]*>", lambda x: re.sub(r'\s(?:role|aria-label)="[^"]*"', "", x.group(0)), svg, count=1)
        svg = re.sub(r"<svg\b", f'<svg role="img" aria-label="{html.escape(alt, quote=True)}"', svg, count=1)
        return f"<figure>{svg}{cap}</figure>"
    dims = ""
    if info and info.get("width") and info.get("height"):
        dims = f' width="{info["width"]}" height="{info["height"]}"'
    return f'<figure><img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}"{dims} loading="lazy" decoding="async">{cap}</figure>'


def _blocks(lines: list[str], slugify=None, images=None) -> str:
    slugify = slugify or slug
    out, i = [], 0
    while i < len(lines):
        ln = lines[i]
        if not ln.strip():
            i += 1
            continue
        m = FENCE.match(ln)
        if m:
            fence, lang = m.group(1), m.group(2)
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f'<pre data-lang="{html.escape(lang, quote=True)}"><code>{html.escape(chr(10).join(code))}</code></pre>')
            continue
        m = HEADING.match(ln)
        if m:
            n, text = len(m.group(1)), md_headings.unescape(m.group(2))
            out.append(f'<h{n} id="{slugify(text)}">{inline(text)}</h{n}>')
            i += 1
            continue
        if RULE.match(ln):
            out.append("<hr>")
            i += 1
            continue
        if ln.lstrip().startswith(">"):
            quote = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            kind = None
            am = re.match(r"^\[!(\w+)\]\s*$", quote[0].strip()) if quote else None
            if am and am.group(1).upper() in ALERTS:
                kind = ALERTS[am.group(1).upper()]
                quote = quote[1:]
            inner = _blocks(quote, slugify, images)
            if kind:
                out.append(f'<aside data-callout="{kind}"><h4>{kind.capitalize()}</h4>{inner}</aside>')
            else:
                out.append(f"<blockquote>{inner}</blockquote>")
            continue
        if BULLET.match(ln) or NUMBER.match(ln):
            h, i = _list(lines, i, _indent(ln))
            out.append(h)
            continue
        if ln.strip().startswith("<!--"):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1
            continue
        if i + 1 < len(lines) and (UNDER2.match(lines[i + 1]) or UNDER1.match(lines[i + 1])) and not ln.lstrip().startswith(("|", "<")):
            text = md_headings.unescape(ln.strip())                  # a Setext heading: the title over `---` (level 2) or `===` (level 1)
            n = 1 if UNDER1.match(lines[i + 1]) else 2
            out.append(f'<h{n} id="{slugify(text)}">{inline(text)}</h{n}>')
            i += 2
            continue
        para = [ln.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not (FENCE.match(lines[i]) or HEADING.match(lines[i]) or BULLET.match(lines[i]) or NUMBER.match(lines[i])
                                                           or lines[i].lstrip().startswith(">") or RULE.match(lines[i])):
            para.append(lines[i].strip())
            i += 1
        text = " ".join(para)
        fm = IMG_ONLY.match(text)
        if fm:
            out.append(_figure(fm, images))
            continue
        sp = lead_split(text)
        if sp and len(sp[0]) <= 40 and sp[0][:1].isupper():
            out.append(lead_html(text)[0])
        else:
            out.append(f"<p>{inline(text)}</p>")
    return "".join(out)


def render(markdown: str, *, section: str = "", audience: str = "", kind: str = "", slugify=None, images=None) -> str:
    """`slugify` is the anchor function (the bundle passes its own, so the heading ids match the manifest's `headings`)."""
    attrs = "".join(f' data-{k}="{html.escape(v, quote=True)}"' for k, v in (("section", section), ("audience", audience), ("kind", kind)) if v)
    return f"<article{attrs}>" + _blocks(markdown.split("\n"), slugify, images) + "</article>\n"
