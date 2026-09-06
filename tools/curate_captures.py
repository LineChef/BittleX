#!/usr/bin/env python3
"""Curate a raw capture batch into a training-ready set.

Repeatable post-processing for face/object capture sessions (see
docs/research/person-recognition.md). Given a folder of `*.jpg` frames -- and,
if present, `<name>.json` sidecars carrying the module's detection boxes for
that frame -- it:

  1. scores every frame for brightness / contrast / sharpness (blur);
  2. drops rejects (too dark / blown / blurry / low-contrast);
  3. splits positives (a detection box present) from negatives (none);
  4. de-duplicates near-identical frames (average-hash) so poses/distances/
     lighting are spread, not clumped;
  5. spread-samples the requested number of positives across the capture
     timeline, plus a few clean negatives;
  6. rotates everything upright;
  7. writes YOLO pre-labels (`<cls> cx cy w h`, normalised) for positives from
     the detection box -- upload-ready, you just assign the class name;
  8. emits a contact sheet + a summary with reject reasons and balance hints.

Input is never modified. Deps: Pillow, numpy (dev machine).

    python tools/curate_captures.py IN_DIR OUT_DIR [options]
    python tools/curate_captures.py --selftest
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageStat


# ----------------------------------------------------------------- metrics

def _gray(im: Image.Image) -> np.ndarray:
    return np.asarray(im.convert("L"), dtype=np.float64)


def brightness_contrast(im: Image.Image) -> tuple[float, float]:
    st = ImageStat.Stat(im.convert("L"))
    return st.mean[0], st.stddev[0]


def sharpness(im: Image.Image) -> float:
    """Variance of the Laplacian -- higher = sharper. Blur -> near 0."""
    g = _gray(im)
    lap = (g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
           - 4.0 * g[1:-1, 1:-1])
    return float(lap.var())


def ahash(im: Image.Image, side: int = 8) -> int:
    g = np.asarray(im.convert("L").resize((side, side), Image.BILINEAR), float)
    bits = (g > g.mean()).flatten()
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ------------------------------------------------------------------ model

@dataclass
class Frame:
    path: str
    idx: int
    bright: float = 0.0
    contrast: float = 0.0
    sharp: float = 0.0
    box: list[float] | None = None      # [cx, cy, w, h] in frame px
    frame_px: int = 240
    hash: int = 0
    reject: str = ""
    score: float = 0.0

    @property
    def has_face(self) -> bool:
        return self.box is not None


@dataclass
class Config:
    positives: int = 80
    negatives: int = 12
    rotate: int = 270                  # 0 | 90 | 180 | 270 (degrees clockwise)
    min_brightness: float = 22.0
    max_brightness: float = 245.0
    min_sharpness: float = 8.0
    min_contrast: float = 12.0
    min_box_frac: float = 0.03         # box area / frame area to count as a face
    hash_thresh: int = 6              # <= this hamming distance == "same frame"
    class_id: int = 0
    target_brightness: float = 110.0   # ideal mid-tone for scoring
    n_buckets: int = 12               # timeline buckets for spread sampling


# --------------------------------------------------------------- pipeline

def _load(in_dir: str) -> list[Frame]:
    frames: list[Frame] = []
    for i, p in enumerate(sorted(glob.glob(os.path.join(in_dir, "*.jpg")))):
        f = Frame(path=p, idx=i)
        side = os.path.splitext(p)[0] + ".json"
        if os.path.isfile(side):
            try:
                d = json.load(open(side))
                f.frame_px = (d.get("resolution") or [240])[0]
                boxes = d.get("boxes") or []
                if boxes:
                    b = max(boxes, key=lambda z: z[2] * z[3])   # largest by area
                    f.box = [float(b[0]), float(b[1]), float(b[2]), float(b[3])]
            except Exception:
                pass
        frames.append(f)
    return frames


def _measure(frames: list[Frame]) -> None:
    for f in frames:
        im = Image.open(f.path)
        f.bright, f.contrast = brightness_contrast(im)
        f.sharp = sharpness(im)
        f.hash = ahash(im)


def _reject_reason(f: Frame, c: Config) -> str:
    if f.bright < c.min_brightness:
        return "too_dark"
    if f.bright > c.max_brightness:
        return "blown_out"
    if f.sharp < c.min_sharpness:
        return "blurry"
    if f.contrast < c.min_contrast:
        return "low_contrast"
    return ""


def _quality(f: Frame, c: Config) -> float:
    s_sharp = min(1.0, f.sharp / 60.0)
    s_bright = 1.0 - min(1.0, abs(f.bright - c.target_brightness) / c.target_brightness)
    s_contrast = min(1.0, f.contrast / 45.0)
    s_box = 0.5
    if f.box is not None:
        frac = (f.box[2] * f.box[3]) / (f.frame_px ** 2)
        s_box = 1.0 - min(1.0, abs(frac - 0.14) / 0.14)          # ideal ~14% of frame
        cx, cy = f.box[0] / f.frame_px, f.box[1] / f.frame_px
        s_box *= 1.0 - min(1.0, (abs(cx - 0.5) + abs(cy - 0.5)))  # centred-ish
    return 0.40 * s_sharp + 0.25 * s_bright + 0.15 * s_contrast + 0.20 * s_box


def _dedup(frames: list[Frame], thresh: int) -> list[Frame]:
    """Keep the best-scoring frame from each run of near-identical frames."""
    kept: list[Frame] = []
    for f in frames:
        dup_of = next((k for k in kept if hamming(k.hash, f.hash) <= thresh), None)
        if dup_of is None:
            kept.append(f)
        elif f.score > dup_of.score:
            kept[kept.index(dup_of)] = f
    return kept


def _spread_select(pool: list[Frame], n: int, buckets: int, total: int) -> list[Frame]:
    if len(pool) <= n:
        return sorted(pool, key=lambda f: f.idx)
    by_bucket: list[list[Frame]] = [[] for _ in range(buckets)]
    for f in pool:
        by_bucket[min(buckets - 1, f.idx * buckets // max(1, total))].append(f)
    for b in by_bucket:
        b.sort(key=lambda f: -f.score)
    out: list[Frame] = []
    while len(out) < n and any(by_bucket):
        for b in by_bucket:
            if b and len(out) < n:
                out.append(b.pop(0))
    return sorted(out, key=lambda f: f.idx)


def _rot_box(box: list[float], px: int, deg: int) -> list[float]:
    cx, cy, w, h = box
    if deg == 90:
        return [cy, px - cx, h, w]
    if deg == 180:
        return [px - cx, px - cy, w, h]
    if deg == 270:
        return [px - cy, cx, h, w]
    return box


def curate(in_dir: str, out_dir: str, c: Config) -> dict:
    frames = _load(in_dir)
    if not frames:
        raise SystemExit(f"no *.jpg in {in_dir}")
    _measure(frames)
    have_boxes = any(f.box is not None for f in frames)

    for f in frames:
        f.reject = _reject_reason(f, c)
        f.score = _quality(f, c)

    survivors = [f for f in frames if not f.reject]
    if have_boxes:
        pos = [f for f in survivors if f.has_face
               and (f.box[2] * f.box[3]) / (f.frame_px ** 2) >= c.min_box_frac]
        neg = [f for f in survivors if not f.has_face]
    else:
        pos, neg = survivors, []

    pos = _dedup(pos, c.hash_thresh)
    neg = _dedup(neg, c.hash_thresh)
    sel_pos = _spread_select(pos, c.positives, c.n_buckets, len(frames))
    sel_neg = sorted(neg, key=lambda f: -f.score)[:c.negatives]

    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*")):
        if os.path.isfile(old):
            os.remove(old)

    for i, f in enumerate(sel_pos, 1):
        im = Image.open(f.path).convert("RGB")
        if c.rotate:
            im = im.rotate(-c.rotate, expand=True)      # PIL rotate is CCW
        stem = os.path.join(out_dir, f"pos_{i:04d}")
        im.save(stem + ".jpg", quality=92)
        if have_boxes and f.box is not None:
            bx = _rot_box(f.box, f.frame_px, c.rotate)
            p = f.frame_px
            with open(stem + ".txt", "w") as fh:
                fh.write(f"{c.class_id} {bx[0]/p:.6f} {bx[1]/p:.6f} "
                         f"{bx[2]/p:.6f} {bx[3]/p:.6f}\n")
    for i, f in enumerate(sel_neg, 1):
        im = Image.open(f.path).convert("RGB")
        if c.rotate:
            im = im.rotate(-c.rotate, expand=True)
        im.save(os.path.join(out_dir, f"neg_{i:04d}.jpg"), quality=92)

    rej: dict[str, int] = {}
    for f in frames:
        if f.reject:
            rej[f.reject] = rej.get(f.reject, 0) + 1

    _contact_sheet(sel_pos, sel_neg, c, os.path.join(out_dir, "_contact_sheet.png"))
    summary = _summary(frames, sel_pos, sel_neg, rej, have_boxes, c)
    open(os.path.join(out_dir, "_summary.txt"), "w").write(summary)
    print(summary)
    return {"positives": len(sel_pos), "negatives": len(sel_neg),
            "rejected": sum(rej.values()), "pre_labeled": have_boxes}


def _contact_sheet(pos, neg, c: Config, path: str) -> None:
    items = [(f, "pos") for f in pos] + [(f, "neg") for f in neg]
    if not items:
        return
    cols, th = 10, 120
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * th, rows * (th + 14)), (18, 18, 18))
    d = ImageDraw.Draw(sheet)
    for k, (f, kind) in enumerate(items):
        im = Image.open(f.path).convert("RGB")
        if c.rotate:
            im = im.rotate(-c.rotate, expand=True)
        im = im.resize((th, th))
        x, y = (k % cols) * th, (k // cols) * (th + 14)
        sheet.paste(im, (x, y))
        col = (90, 210, 120) if kind == "pos" else (210, 110, 100)
        d.text((x + 2, y + th + 1), f"{kind} b{f.bright:.0f} s{f.sharp:.0f}", fill=col)
    sheet.save(path)


def _summary(frames, pos, neg, rej, have_boxes, c: Config) -> str:
    L = []
    L.append(f"curated {len(frames)} frames  ->  {len(pos)} positives, {len(neg)} negatives")
    L.append(f"pre-labels: {'YES (from detection boxes)' if have_boxes else 'NO (no sidecars) -- label at upload'}")
    L.append(f"rotate: {c.rotate} deg CW   class_id: {c.class_id}")
    if rej:
        L.append("rejected: " + ", ".join(f"{k}={v}" for k, v in sorted(rej.items())))
    if pos:
        b = [f.bright for f in pos]
        s = [f.sharp for f in pos]
        L.append(f"kept brightness: {min(b):.0f}..{max(b):.0f} (mean {sum(b)/len(b):.0f})   "
                 f"sharpness: {min(s):.0f}..{max(s):.0f}")
        if have_boxes:
            fr = [(f.box[2]*f.box[3])/(f.frame_px**2) for f in pos if f.box]
            L.append(f"kept face-size (frac of frame): {min(fr):.2f}..{max(fr):.2f} (mean {sum(fr)/len(fr):.2f})")
        # balance hints
        if max(b) - min(b) < 30:
            L.append("  ! narrow brightness range -- vary lighting more next time")
        if have_boxes and fr and max(fr) - min(fr) < 0.06:
            L.append("  ! all faces about the same size -- vary distance (close AND far)")
        if len(pos) < c.positives:
            L.append(f"  ! only {len(pos)} usable positives (wanted {c.positives}) -- "
                     "capture more / brighter / more varied")
    if not have_boxes:
        L.append("  ! no detection sidecars -- capture with Person or (better) Face "
                 "Detection loaded so frames carry boxes for pre-labels + auto neg split")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ selftest

def _selftest() -> None:
    import tempfile
    d = tempfile.mkdtemp()
    rng = np.random.default_rng(0)
    for i in range(60):
        arr = rng.integers(80, 170, (240, 240, 3), dtype=np.uint8)   # mid-tone noise
        if i < 8:                       # dark rejects
            arr = (arr // 6).astype(np.uint8)
        if 40 <= i < 48:                # blurry-ish: heavy blur
            im = Image.fromarray(arr).filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(6))
            arr = np.asarray(im)
        Image.fromarray(arr).save(os.path.join(d, f"f_{i:03d}.jpg"))
        boxes = [] if i % 7 == 0 else [[120, 120, 70, 90, 80, 0]]     # ~1/7 negatives
        json.dump({"resolution": [240, 240], "boxes": boxes},
                  open(os.path.join(d, f"f_{i:03d}.json"), "w"))
    out = tempfile.mkdtemp()
    r = curate(d, out, Config(positives=20, negatives=5))
    assert r["positives"] > 0 and r["negatives"] > 0 and r["pre_labeled"]
    assert os.path.isfile(os.path.join(out, "pos_0001.txt"))
    assert os.path.isfile(os.path.join(out, "_contact_sheet.png"))
    print("selftest OK:", r)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("in_dir", nargs="?", help="folder of raw *.jpg (+ optional *.json sidecars)")
    ap.add_argument("out_dir", nargs="?", help="curated output folder")
    ap.add_argument("--positives", type=int, default=80)
    ap.add_argument("--negatives", type=int, default=12)
    ap.add_argument("--rotate", type=int, default=270, choices=(0, 90, 180, 270),
                    help="degrees clockwise to make frames upright (default 270)")
    ap.add_argument("--min-brightness", type=float, default=22.0)
    ap.add_argument("--max-brightness", type=float, default=245.0)
    ap.add_argument("--min-sharpness", type=float, default=8.0)
    ap.add_argument("--min-contrast", type=float, default=12.0)
    ap.add_argument("--min-box-frac", type=float, default=0.03)
    ap.add_argument("--hash-thresh", type=int, default=6)
    ap.add_argument("--class-id", type=int, default=0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
        return
    if not a.in_dir or not a.out_dir:
        ap.error("in_dir and out_dir required (or --selftest)")
    c = Config(positives=a.positives, negatives=a.negatives, rotate=a.rotate,
               min_brightness=a.min_brightness, max_brightness=a.max_brightness,
               min_sharpness=a.min_sharpness, min_contrast=a.min_contrast,
               min_box_frac=a.min_box_frac, hash_thresh=a.hash_thresh,
               class_id=a.class_id)
    curate(a.in_dir, a.out_dir, c)


if __name__ == "__main__":
    main()
