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

    def readable(f) -> bool:                 # pictures cut off by the camera's small buffer (6 of 89 so far) do not decode: left out, and counted
        from PIL import Image
        try:
            Image.open(f).load()
            return True
        except OSError:
            skipped.append(f.name)
            return False
    skipped: list = []
    for f in sorted((root / "named").glob("*/*.jpg")):
        if readable(f):
            named.setdefault(f.parent.name, []).append(f)
    survey = [f for f in sorted((root / "survey").glob("*/*.jpg")) if readable(f)]
    if skipped:
        print(f"left out {len(skipped)} cut-off picture(s): {', '.join(skipped)}")
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


def sweep(spec: str, named, survey, thresholds) -> dict:
    """Threshold sweep with views embedded once. A picture's score against an object = the best cosine between ANY of its views (the whole picture or a tile) and ANY named sample of that object
    (the whole-picture vectors of the other pictures of it). Hit rate = held-out named pictures whose best score against their own object reaches the threshold; false rate = survey pictures whose
    best score against any named object reaches it; also the rate at which a held-out picture scores higher against ANOTHER object than its own (a wrong name)."""
    emb = make_embedder(spec)
    loc = GridLocalizer()
    whole = {f: emb.embed(f.read_bytes()) for fs in named.values() for f in fs}

    def views(f):
        return [emb.embed(c) for _, c in loc.views(f.read_bytes())]
    named_views = {f: views(f) for fs in named.values() for f in fs}
    survey_views = {f: views(f) for f in survey}

    def best(vs, samples):
        return max((float(v @ x) for v in vs for x in samples), default=-1.0)
    own, wrong, other_best = [], 0, 0
    for n, fs in named.items():
        for f in fs:
            mine = [whole[g] for g in fs if g != f]
            if not mine:
                continue
            a = best(named_views[f], mine)
            b = max((best(named_views[f], [whole[g] for g in named[m]]) for m in named if m != n), default=-1.0)
            own.append(a)
            other_best += 1
            wrong += b > a
    allsamples = list(whole.values())
    false = [best(vs, allsamples) for vs in survey_views.values()]
    rows = []
    for t in thresholds:
        hit = sum(a >= t for a in own) / len(own) if own else None
        fr = sum(x >= t for x in false) / len(false) if false else None
        rows.append((t, hit, fr))
    return dict(embedder=emb.name, rows=rows, wrong=(wrong / other_best) if other_best else None)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.expanduser("~/g2_pictures/explore"))
    ap.add_argument("--embedder", action="append", default=None)
    ap.add_argument("--threshold", type=float, default=0.80)
    ap.add_argument("--sweep", action="store_true", help="instead of one threshold, sweep 0.30-0.95 and show the hit rate and the false-recognition rate at each, and the best cut")
    a = ap.parse_args(argv)
    named, survey = load(Path(a.root))
    if not named:
        print(f"no named pictures under {a.root}/named: name some objects first (voice: 'this is the mug'), then g2pics pull")
        return 1
    f = lambda v, p="{:.3f}": "n/a" if v is None else p.format(v)       # noqa: E731
    if a.sweep:
        ths = [round(0.30 + 0.05 * i, 2) for i in range(14)]
        for spec in (a.embedder or ["histogram"]):
            r = sweep(spec, named, survey, ths)
            print(f"{r['embedder']}: wrong-name rate (a held-out picture matches ANOTHER object better than its own) {f(r['wrong'], '{:.0%}')}")
            print("  threshold  hit rate  false recognitions")
            best_t = max(r["rows"], key=lambda x: ((x[1] or 0) - (x[2] or 0), x[0]))
            for t, hit, fr in r["rows"]:
                print(f"  {t:.2f}      {f(hit, '{:.0%}'):>6}    {f(fr, '{:.0%}'):>6}{'   <- best cut (hit minus false)' if t == best_t[0] else ''}")
        return 0
    for spec in (a.embedder or ["histogram"]):
        r = evaluate(spec, named, survey, a.threshold)
        gap = None if r["within"] is None or r["between"] is None else r["within"] - r["between"]
        print(f"{r['embedder']}  dim {r['dim']}  {r['objects']} objects / {r['pictures']} named pictures / {r['survey']} survey pictures (threshold {a.threshold})")
        print(f"  within-object similarity {f(r['within'])}   between-object {f(r['between'])}   gap {f(gap)}   {'(need 2+ objects for the gap)' if r['between'] is None else ''}")
        print(f"  leave-one-out retrieval {f(r['retrieval'], '{:.0%}')}   hit rate on held-out pictures {f(r['hit_rate'], '{:.0%}')}   false recognitions in survey pictures {f(r['false_rate'], '{:.0%}')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
