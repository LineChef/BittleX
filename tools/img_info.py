"""Image facts for the docs bundle without any imaging library: pixel size of a PNG, JPEG, GIF, WebP or SVG, and a safety check for SVG text. Stdlib only.

`image_size(path)` returns (width, height) in pixels (an SVG's viewBox or width and height attributes, in user units) or None. `svg_problems(text)` lists what makes an SVG unsafe to inline
or publish: a script, a foreignObject, an event handler attribute, or a reference to anything outside the file.
"""
from __future__ import annotations

import os
import re
import struct


def _png(b):
    return struct.unpack(">II", b[16:24]) if b[:8] == b"\x89PNG\r\n\x1a\n" and len(b) >= 24 else None


def _gif(b):
    return struct.unpack("<HH", b[6:10]) if b[:6] in (b"GIF87a", b"GIF89a") and len(b) >= 10 else None


def _jpeg(b):
    if b[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        marker = b[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", b[i + 2:i + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return None


def _webp(b):
    if b[:4] != b"RIFF" or b[8:12] != b"WEBP":
        return None
    kind = b[12:16]
    if kind == b"VP8X":
        return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
    if kind == b"VP8 ":
        w, h = struct.unpack("<HH", b[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if kind == b"VP8L":
        v = int.from_bytes(b[21:25], "little")
        return 1 + (v & 0x3FFF), 1 + ((v >> 14) & 0x3FFF)
    return None


def _num(s):
    m = re.match(r"\s*([0-9.]+)", s or "")
    return float(m.group(1)) if m else None


def svg_size(text):
    root = re.search(r"<svg\b[^>]*>", text, re.S)
    if not root:
        return None
    tag = root.group(0)
    vb = re.search(r'viewBox\s*=\s*"([^"]+)"', tag)
    if vb:
        p = re.split(r"[\s,]+", vb.group(1).strip())
        if len(p) == 4 and _num(p[2]) and _num(p[3]):
            return int(round(float(p[2]))), int(round(float(p[3])))
    w = re.search(r'\bwidth\s*=\s*"([^"]+)"', tag)
    h = re.search(r'\bheight\s*=\s*"([^"]+)"', tag)
    if w and h and _num(w.group(1)) and _num(h.group(1)):
        return int(round(_num(w.group(1)))), int(round(_num(h.group(1))))
    return None


def image_size(path):
    """(width, height) of the image at `path`, or None when it cannot be read."""
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".svg":
            return svg_size(open(path, encoding="utf-8", errors="replace").read())
        b = open(path, "rb").read(65536)
        for fn in {".png": (_png,), ".gif": (_gif,), ".jpg": (_jpeg,), ".jpeg": (_jpeg,), ".webp": (_webp,)}.get(ext, ()):
            r = fn(b)
            if r:
                return int(r[0]), int(r[1])
    except Exception:  # noqa: BLE001
        return None
    return None


def svg_problems(text):
    out = []
    if re.search(r"<\s*script\b", text, re.I):
        out.append("contains a <script>")
    if re.search(r"<\s*foreignObject\b", text, re.I):
        out.append("contains a <foreignObject>")
    if re.search(r"\son[a-z]+\s*=", text, re.I):
        out.append("has an event handler attribute")
    for m in re.finditer(r'(?:href|src)\s*=\s*"([^"]*)"', text, re.I):
        if not m.group(1).startswith("#") and not m.group(1).startswith("data:image/"):
            out.append(f"references {m.group(1)[:50]}")
    if re.search(r"url\(\s*['\"]?(?!#)(?!data:)", text):
        out.append("a CSS url() reaches outside the file")
    if re.search(r"@import\b", text):
        out.append("uses @import")
    return out
