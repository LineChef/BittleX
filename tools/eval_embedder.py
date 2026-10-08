#!/usr/bin/env python3
"""Phase 3 of the object recognition plan: how well does an embedder tell G2's pictures apart? Run on the Mac over the pulled pictures (`g2pics pull`; default ~/g2_pictures/explore).

    python tools/eval_embedder.py [--root DIR] [--embedder histogram] [--embedder onnx:/path/model.onnx] [--threshold 0.80]

Named pictures are `named/<name>/*.jpg`; every survey picture (`survey/<day>/*.jpg`) is a distractor, a scene that should NOT be recognised as any named object. For each embedder it prints
  * within-object vs between-object similarity (whole picture against whole picture) and the gap between them (needs two or more named objects with two or more pictures each),
  * leave-one-out retrieval: the share of named pictures whose closest OTHER named picture has the same name,
  * the false-recognition rate: the share of survey pictures in which some view (the whole picture or a tile) reaches the threshold against a named object, and the
    hit rate: the share of named pictures that a gallery built from the OTHER pictures of that object recognises,
so thresholds and the embedder can be chosen on real data. Nothing is written and nothing is downloaded.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pi_pipeline.vision.embedder import make_embedder  # noqa: E402
from pi_pipeline.vision.localizer import GridLocalizer  # noqa: E402
from pi_pipeline.vision.object_gallery import ObjectGallery, ObjectGalleryConfig  # noqa: E402
from pi_pipeline.vision.recognizer import Recognizer  # noqa: E402


def load(root: Path):
    named, survey = {}, []
    for f in sorted((root / "named").glob("*/*.jpg")):
        named.setdefault(f.parent.name, []).append(f)
    survey = sorted((root / "survey").glob("*/*.jpg"))
    return named, survey


def evaluate(spec: str, named, survey, threshold: float) -> dict:
    emb = make_embedder(spec)
    vec = {f: emb.embed(f.read_bytes()) for fs in named.values() for f in fs}
    items = [(n, f) for n, fs in named.items() for f in fs]
    within, between = [], []
    for i, (na, fa) in enumerate(items):
        for nb, fb in items[i + 1:]:
            (within if na == nb else between).append(float(vec[fa] @ vec[fb]))
    correct = total = 0
    for na, fa in items:
        others = [(nb, float(vec[fa] @ vec[fb])) for nb, fb in items if fb != fa]
        if others and any(nb == na for nb, _ in others):
            total += 1
            correct += max(others, key=lambda t: t[1])[0] == na
    # hit rate: a gallery built from the OTHER pictures of the same object recognises this picture
    hits = tried = 0
    for na, fa in items:
        rest = [f for f in named[na] if f != fa]
        if not rest:
            continue
        rec = Recognizer(emb, ObjectGallery(ObjectGalleryConfig(same_instance_threshold=threshold, near_duplicate_threshold=1.01, max_samples_per_entry=999)), GridLocalizer())
        for f in rest:
            rec.learn_named(f.read_bytes(), na)
        tried += 1
        hits += any(r.name == na for r in rec.recognize(fa.read_bytes()))
    # false recognitions on the survey pictures, against a gallery of all the named pictures
    rec = Recognizer(emb, ObjectGallery(ObjectGalleryConfig(same_instance_threshold=threshold, near_duplicate_threshold=1.01, max_samples_per_entry=999)), GridLocalizer())
    for n, f in items:
        rec.learn_named(f.read_bytes(), n)
    false = sum(bool(rec.recognize(f.read_bytes())) for f in survey)
    return dict(embedder=emb.name, dim=emb.dim, objects=len(named), pictures=len(items), survey=len(survey),
                within=float(np.mean(within)) if within else None, between=float(np.mean(between)) if between else None,
                retrieval=(correct / total) if total else None, hit_rate=(hits / tried) if tried else None, false_rate=(false / len(survey)) if survey else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/g2_pictures/explore"))
    ap.add_argument("--embedder", action="append", default=None)
    ap.add_argument("--threshold", type=float, default=0.80)
    a = ap.parse_args(argv)
    named, survey = load(Path(a.root))
    if not named:
        print(f"no named pictures under {a.root}/named: name some objects first (voice: 'this is the mug'), then g2pics pull")
        return 1
    f = lambda v, p="{:.3f}": "n/a" if v is None else p.format(v)       # noqa: E731
    for spec in (a.embedder or ["histogram"]):
        r = evaluate(spec, named, survey, a.threshold)
        gap = None if r["within"] is None or r["between"] is None else r["within"] - r["between"]
        print(f"{r['embedder']}  dim {r['dim']}  {r['objects']} objects / {r['pictures']} named pictures / {r['survey']} survey pictures (threshold {a.threshold})")
        print(f"  within-object similarity {f(r['within'])}   between-object {f(r['between'])}   gap {f(gap)}   {'(need 2+ objects for the gap)' if r['between'] is None else ''}")
        print(f"  leave-one-out retrieval {f(r['retrieval'], '{:.0%}')}   hit rate on held-out pictures {f(r['hit_rate'], '{:.0%}')}   false recognitions in survey pictures {f(r['false_rate'], '{:.0%}')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
