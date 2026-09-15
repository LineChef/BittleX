#!/usr/bin/env python3
"""Analyze the vision library per class against a distance-composition target,
and (optionally) build a diversity-optimized training subset capped at a
target count.

Selection is distance-stratified (far/mid/close/vclose, by YOLO box size --
the same buckets docs/vision/capture-progress.md's diagnostic work uses),
quality-ranked (sharpness + exposure, the same scoring curate_captures.py
uses), and average-hash deduped, so a class that's grown lopsided (e.g. 99%
close-up shots, like `<you>` was found to be on 2026-09-14) doesn't just get
truncated to its first N images -- within each bucket the sharpest/best-exposed
images win first, near-duplicates collapse to their best representative, and
the target composition is filled as far as the available pool allows. Any
bucket that's short just contributes everything it has (never fabricated) and
is flagged so you know what to capture more of.

    # report only -- how each class's pool breaks down vs the target, and
    # exactly how many more of each distance bucket would close the gap
    python tools/optimize_library.py ~/Desktop/g2_vision_library --report

    # materialize an optimized, deduped, capped subset per class for upload
    python tools/optimize_library.py ~/Desktop/g2_vision_library --classes sam,dog,cat \\
        --target 150 --out ~/Desktop/g2_vision_library/upload_optimized

Default target composition (tune with --mix far:mid:close:vclose):
  far (sz<0.30) 20%   mid (0.30-0.50) 30%   close (0.50-0.70) 30%   vclose (>=0.70) 20%

Re-run any time new images are promoted into the library -- it always
re-selects from the full current pool, never from a cached snapshot, so the
result only gets better as capture continues. Never touches or deletes
anything in the library itself; `--out` only ever copies.
"""
from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from curate_captures import ahash, brightness_contrast, hamming, sharpness  # noqa: E402
from PIL import Image  # noqa: E402

BUCKETS = [("far", 0.00, 0.30), ("mid", 0.30, 0.50), ("close", 0.50, 0.70), ("vclose", 0.70, 1.01)]
TARGET_BRIGHTNESS = 110.0   # same mid-tone target curate_captures.py scores against


def _quality(path: str) -> float:
    """Sharpness + exposure score, 0-1ish -- same formula curate_captures.py
    uses minus the box-centering term (bucket selection already handles size)."""
    im = Image.open(path)
    sharp = sharpness(im)
    bright, contrast = brightness_contrast(im)
    s_sharp = min(1.0, sharp / 60.0)
    s_bright = 1.0 - min(1.0, abs(bright - TARGET_BRIGHTNESS) / TARGET_BRIGHTNESS)
    s_contrast = min(1.0, contrast / 45.0)
    return 0.55 * s_sharp + 0.30 * s_bright + 0.15 * s_contrast


def _box_size(txt_path: str) -> float | None:
    try:
        with open(txt_path) as f:
            parts = f.readline().split()
    except OSError:
        return None
    if len(parts) < 5:
        return None
    w, h = float(parts[3]), float(parts[4])
    return (w * h) ** 0.5


def _bucket(sz: float) -> str:
    for name, lo, hi in BUCKETS:
        if lo <= sz < hi:
            return name
    return BUCKETS[-1][0]


def _dedup(paths: list[str], thresh: int, quality: dict[str, float]) -> list[str]:
    """Collapse near-duplicate frames (average-hash), keeping the HIGHEST-
    QUALITY representative of each cluster, not just the first one seen."""
    kept: list[tuple[str, int]] = []  # (path, hash)
    for p in paths:
        try:
            h = ahash(Image.open(p))
        except Exception:
            continue
        match = next((i for i, (kp, kh) in enumerate(kept) if hamming(h, kh) <= thresh), None)
        if match is None:
            kept.append((p, h))
        elif quality.get(p, 0.0) > quality.get(kept[match][0], 0.0):
            kept[match] = (p, h)
    return [p for p, _ in kept]


def _top_quality(pool: list[str], n: int, quality: dict[str, float]) -> list[str]:
    """The n sharpest/best-exposed images in pool -- variety within the bucket
    already comes from dedup having collapsed near-identical frames; quality
    is the right tiebreaker among genuinely distinct survivors."""
    if n <= 0:
        return []
    if len(pool) <= n:
        return list(pool)
    return sorted(pool, key=lambda p: -quality.get(p, 0.0))[:n]


def analyze(cls_dir: str, cls: str, dedup_thresh: int) -> dict:
    imgs = sorted(glob.glob(os.path.join(cls_dir, f"{cls}_*.jpg")))
    by_bucket: dict[str, list[str]] = defaultdict(list)
    unlabeled = 0
    for img in imgs:
        txt = os.path.splitext(img)[0] + ".txt"
        sz = _box_size(txt) if os.path.exists(txt) else None
        if sz is None:
            unlabeled += 1
            continue
        by_bucket[_bucket(sz)].append(img)
    quality = {}
    for paths in by_bucket.values():
        for p in paths:
            try:
                quality[p] = _quality(p)
            except Exception:
                quality[p] = 0.0
    deduped = {b: _dedup(paths, dedup_thresh, quality) for b, paths in by_bucket.items()}
    return {"total": len(imgs), "unlabeled": unlabeled, "raw": by_bucket, "deduped": deduped, "quality": quality}


def select(deduped: dict[str, list[str]], target: int, mix: dict[str, float],
           quality: dict[str, float]) -> dict[str, list[str]]:
    want = {b: round(target * pct) for b, _, _ in BUCKETS for pct in [mix.get(b, 0.0)]}
    chosen: dict[str, list[str]] = {}
    leftover = 0
    for b, _, _ in BUCKETS:
        pool = deduped.get(b, [])
        take = min(want.get(b, 0), len(pool))
        chosen[b] = _top_quality(pool, take, quality)
        leftover += want.get(b, 0) - take
    if leftover > 0:
        spare = {b: len(deduped.get(b, [])) - len(chosen[b]) for b, _, _ in BUCKETS}
        for b, _, _ in sorted(BUCKETS, key=lambda x: -spare[x[0]]):
            room, extra = spare[b], 0
            if room <= 0 or leftover <= 0:
                continue
            extra = min(room, leftover)
            pool = deduped.get(b, [])
            already = set(chosen[b])
            more = _top_quality([p for p in pool if p not in already], extra, quality)
            chosen[b].extend(more)
            leftover -= len(more)
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("library", help="the vision library root")
    ap.add_argument("--classes", help="comma-separated class list (default: every dir with <cls>_0001.jpg-style files)")
    ap.add_argument("--target", type=int, default=150)
    ap.add_argument("--mix", default="far:0.20,mid:0.30,close:0.30,vclose:0.20",
                    help="target composition, e.g. far:0.2,mid:0.3,close:0.3,vclose:0.2")
    ap.add_argument("--dedup-thresh", type=int, default=4,
                    help="hamming distance counted as a duplicate (matches curate's --dup-thresh)")
    ap.add_argument("--neg-target", type=int, default=40,
                    help="top-quality, deduped negatives to also copy to --out (0 to skip)")
    ap.add_argument("--out", help="if given, copy the optimized selection here (per-class subfolders)")
    ap.add_argument("--report", action="store_true", help="analysis only (default if --out is omitted)")
    a = ap.parse_args()

    mix = {}
    for tok in a.mix.split(","):
        k, v = tok.split(":")
        mix[k.strip()] = float(v)

    lib = os.path.expanduser(a.library)
    if a.classes:
        classes = [c.strip() for c in a.classes.split(",")]
    else:
        classes = sorted(
            d for d in os.listdir(lib)
            if os.path.isdir(os.path.join(lib, d)) and glob.glob(os.path.join(lib, d, f"{d}_*.jpg"))
        )

    for cls in classes:
        cls_dir = os.path.join(lib, cls)
        info = analyze(cls_dir, cls, a.dedup_thresh)
        chosen = select(info["deduped"], a.target, mix, info["quality"])
        picked = sum(len(v) for v in chosen.values())
        print(f"\n== {cls} ==  {info['total']} labeled images in library"
              + (f"  ({info['unlabeled']} unlabeled, skipped)" if info["unlabeled"] else ""))
        for b, _, _ in BUCKETS:
            raw_n = len(info["raw"].get(b, []))
            dedup_n = len(info["deduped"].get(b, []))
            got = len(chosen.get(b, []))
            want = round(a.target * mix.get(b, 0.0))
            short = f"  <-- short by {want - got}, capture more" if got < want else ""
            print(f"  {b:7s} raw {raw_n:4d}  deduped {dedup_n:4d}  target {want:4d}  selected {got:4d}{short}")
        print(f"  selected total: {picked} / target {a.target}")

        if a.out:
            out_dir = os.path.join(os.path.expanduser(a.out), cls)
            os.makedirs(out_dir, exist_ok=True)
            for paths in chosen.values():
                for p in paths:
                    txt = os.path.splitext(p)[0] + ".txt"
                    shutil.copy(p, out_dir)
                    if os.path.exists(txt):
                        shutil.copy(txt, out_dir)
            print(f"  -> copied {picked} images+labels to {out_dir}")

    if a.out and a.neg_target > 0:
        _process_negatives(lib, os.path.expanduser(a.out), a.neg_target, a.dedup_thresh)


def _process_negatives(lib: str, out_root: str, neg_target: int, dedup_thresh: int) -> None:
    neg_dir = next((d for d in ("_negatives", "negatives") if os.path.isdir(os.path.join(lib, d))), None)
    neg_paths = sorted(glob.glob(os.path.join(lib, neg_dir, "neg_*.jpg"))) if neg_dir else []
    print(f"\n== negatives ==  {len(neg_paths)} in library")
    if not neg_paths:
        return
    quality = {}
    for p in neg_paths:
        try:
            quality[p] = _quality(p)
        except Exception:
            quality[p] = 0.0
    deduped = _dedup(neg_paths, dedup_thresh, quality)
    chosen = _top_quality(deduped, neg_target, quality)
    out_dir = os.path.join(out_root, "_negatives")
    os.makedirs(out_dir, exist_ok=True)
    for p in chosen:
        shutil.copy(p, out_dir)
    print(f"  deduped {len(deduped)}  target {neg_target}  selected {len(chosen)}")
    print(f"  -> copied {len(chosen)} images to {out_dir}")


if __name__ == "__main__":
    main()
