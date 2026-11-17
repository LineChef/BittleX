"""Score training pictures and choose the best under a cap (2026-11-17, owner-approved: no class may build up unlimited pictures; the worst are replaced by better ones).

One shared module for the three places that need it: the chase's picture saver on the Pi (`behavior/ball_chase.PictureSaver`), the nightly pass on the Mac and the pruning tool (`tools/curate_class.py`).
A picture's QUALITY is its own sharpness, contrast and exposure, plus a bonus when the ball finder sees the ball in it. `choose` keeps the protected pictures, drops rejects and near-duplicates, and spreads
what is left over bins of distance and bearing, the best of each bin first, up to the cap. numpy and Pillow only.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageFile

CLASS_CAP = 250
DIST_BIN_IN = 4.0
BEARING_BIN_DEG = 10.0
DEDUP_HAMMING = 6
MIN_BRIGHT, MAX_BRIGHT, MIN_CONTRAST, MIN_SHARP = 40.0, 215.0, 18.0, 20.0
UNKNOWN_QUALITY = 0.35          # a picture with no stored score is assumed to be a middling one: it is the first to be replaced by a scored one


def _gray(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L"), dtype=np.float64)


def brightness_contrast(im: Image.Image) -> tuple[float, float]:
    g = _gray(im)
    return float(g.mean()), float(g.std())


def sharpness(im: Image.Image) -> float:
    """Variance of the Laplacian: higher = sharper, a blur is near 0."""
    g = _gray(im)
    lap = g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:] - 4.0 * g[1:-1, 1:-1]
    return float(lap.var())


def ahash(im: Image.Image, side: int = 16) -> int:
    g = np.asarray(im.convert("L").resize((side, side), Image.BILINEAR), float)
    out = 0
    for b in (g > g.mean()).flatten():
        out = (out << 1) | int(b)
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def measure(jpeg: bytes) -> dict | None:
    """The picture's own numbers, or None when it cannot be read."""
    im = None
    for lenient in (False, True):                                               # the camera's pictures are often cut short by a few bytes (no end marker): they still decode whole when truncation is allowed
        ImageFile.LOAD_TRUNCATED_IMAGES = lenient
        try:
            im = Image.open(io.BytesIO(jpeg))
            im.load()
            im = im.convert("RGB")
            break
        except Exception:  # noqa: BLE001
            im = None
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
    if im is None:
        return None
    mean, contrast = brightness_contrast(im)
    return {"mean": round(mean, 1), "contrast": round(contrast, 1), "sharp": round(sharpness(im), 1), "hash": ahash(im)}


def reject_reason(m: dict) -> str:
    if m["mean"] < MIN_BRIGHT:
        return "dark"
    if m["mean"] > MAX_BRIGHT:
        return "blown"
    if m["contrast"] < MIN_CONTRAST:
        return "flat"
    if m["sharp"] < MIN_SHARP:
        return "blurry"
    return ""


def quality(m: dict, ball_found: bool = True) -> float:
    return round(min(m["sharp"] / 200.0, 1.0) * 0.5 + min(m["contrast"] / 60.0, 1.0) * 0.3 + (1.0 - abs(m["mean"] - 128.0) / 128.0) * 0.2 + (0.3 if ball_found else 0.0), 3)


def choose(rows: list, cap: int | None = None, protected=lambda name: False, dedup: int = DEDUP_HAMMING) -> tuple[list, dict]:
    """(kept file names, {file: reason dropped}). `rows` = dicts with file, ok, why, quality, hash and optionally dist_in and bearing_deg; `protected(name)` pictures are always kept."""
    cap = CLASS_CAP if cap is None else cap
    dropped: dict = {}
    kept = [r["file"] for r in rows if protected(r["file"])]
    for r in rows:
        if not r["ok"] and not protected(r["file"]):
            dropped[r["file"]] = r["why"]
    pool = sorted((r for r in rows if r["ok"] and not protected(r["file"])), key=lambda r: -r["quality"])
    uniq: list = []
    for r in pool:                                                              # best first: a later near-twin is the one dropped
        if any(hamming(r["hash"], u["hash"]) <= dedup for u in uniq):
            dropped[r["file"]] = "near-duplicate"
        else:
            uniq.append(r)
    room = max(0, cap - len(kept))
    bins: dict = {}
    for r in uniq:
        key = (int(r.get("dist_in", 0) // DIST_BIN_IN), int((r.get("bearing_deg", 0) + 90) // BEARING_BIN_DEG))
        bins.setdefault(key, []).append(r)
    order: list = []
    depth = 0
    while len(order) < len(uniq):                                               # round-robin over the bins, the best of each bin first
        for key in sorted(bins):
            if depth < len(bins[key]):
                order.append(bins[key][depth])
        depth += 1
    kept += [r["file"] for r in order[:room]]
    for r in order[room:]:
        dropped[r["file"]] = "over the cap (a better one fills the bin)"
    return kept, dropped


def replace_victim(existing: dict, new_quality: float, cap: int | None = None) -> str | None:
    """The saver's cheap rule at the cap: `existing` = {file: stored quality or None}. Below the cap nothing is replaced (None). At the cap the lowest-scored file (an unscored one counts UNKNOWN_QUALITY) is
    the victim if the new picture scores higher, else None and the new picture is not kept. Returns the victim's file name, or "" when the new picture should simply not be kept."""
    cap = CLASS_CAP if cap is None else cap
    if len(existing) < cap:
        return None
    worst = min(existing, key=lambda f: UNKNOWN_QUALITY if existing[f] is None else existing[f])
    worst_q = UNKNOWN_QUALITY if existing[worst] is None else existing[worst]
    return worst if new_quality > worst_q else ""
