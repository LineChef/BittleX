#!/usr/bin/env python3
"""Rebuild G2's object gallery with another embedder, from the pictures you labelled (user, 2026-11-06). Nothing is deleted: the pictures and their names stay where they are; only the fingerprints
(the lists of numbers the gallery compares) are recomputed with the new model, and the gallery file records which model made them and the similarity thresholds that fit its scale.

    python tools/rebuild_gallery.py [--embedder dinov2_small.onnx#cls] [--pictures training_data/exploration/promoted] [--out ~/g2_data/gallery_rebuilt/gallery.json]

The labelled pictures are `<pictures>/<name>/*.jpg` (the promoted set). For the new embedder it measures, over those pictures, how similar two pictures of the SAME object are and how similar
pictures of DIFFERENT objects are, and sets the gallery's thresholds from that (same-instance between the two groups, near-duplicate near the top of the same-object group), then teaches every
picture to a fresh gallery and saves it. It also prints the leave-one-out score (the share of pictures whose closest OTHER picture has the same name) next to the histogram embedder's, so the change
can be judged. The live gallery is never touched: the output goes to --out, and putting it on the Pi is a separate, deliberate step. Needs Pillow, numpy and onnxruntime (the Mac's tools venv).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pi_pipeline.vision.embedder import make_embedder, spec_for  # noqa: E402
from pi_pipeline.vision.interest import crop_quality  # noqa: E402
from pi_pipeline.vision.object_gallery import ObjectGallery, ObjectGalleryConfig  # noqa: E402
from pi_pipeline.vision.recognizer import Recognizer  # noqa: E402

DEFAULT_PICTURES = Path(__file__).resolve().parents[1] / "training_data" / "exploration" / "promoted"
DEFAULT_OUT = Path(os.path.expanduser("~/g2_data/gallery_rebuilt/gallery.json"))


def load_labelled(root: Path) -> dict[str, list[Path]]:
    out = {}
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        files = sorted(d.glob("*.jpg"))
        if files:
            out[d.name.replace("-", " ")] = files
    return out


def embed_all(labelled: dict, embedder) -> tuple[list[str], np.ndarray, list[Path]]:
    from PIL import Image
    names, vecs, paths = [], [], []
    for name, files in labelled.items():
        for f in files:
            try:
                img = Image.open(f)
                img.load()
            except OSError:
                continue                                         # a picture the camera cut short does not decode
            names.append(name)
            vecs.append(np.asarray(embedder.embed(img), dtype=np.float32))
            paths.append(f)
    return names, np.vstack(vecs), paths


def similarity_groups(names: list[str], vecs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(same-object similarities, different-object similarities) over all pairs of unit vectors."""
    s = vecs @ vecs.T
    n = len(names)
    same, diff = [], []
    for i in range(n):
        for j in range(i + 1, n):
            (same if names[i] == names[j] else diff).append(float(s[i, j]))
    return np.array(same), np.array(diff)


def choose_thresholds(same: np.ndarray, diff: np.ndarray) -> tuple[float, float]:
    """(same-instance, near-duplicate). Same-instance sits between the top of the different-object group (95th percentile) and the lower quarter of the same-object group; near-duplicate near the top of the same-object group."""
    hi_diff = float(np.percentile(diff, 95)) if len(diff) else 0.5
    lo_same = float(np.percentile(same, 25)) if len(same) else 0.9
    t_same = (hi_diff + lo_same) / 2 if lo_same > hi_diff else hi_diff + 0.01
    t_near = max(t_same + 0.05, float(np.percentile(same, 90)) if len(same) else 0.97)
    return round(min(t_same, 0.97), 3), round(min(t_near, 0.995), 3)


def leave_one_out(names: list[str], vecs: np.ndarray) -> float:
    s = vecs @ vecs.T
    np.fill_diagonal(s, -1.0)
    ok = sum(1 for i in range(len(names)) if names[int(np.argmax(s[i]))] == names[i])
    return ok / len(names) if names else 0.0


def build_gallery(names, vecs, paths, key: str, t_same: float, t_near: float) -> ObjectGallery:
    cfg = ObjectGalleryConfig(lock_by_holdout=True, same_instance_threshold=t_same, near_duplicate_threshold=t_near)
    gal = ObjectGallery(cfg)
    gal.embedder = key

    class Fixed:                                                 # the vectors are already computed
        def __init__(self): self.table, self.dim, self.name = {}, int(vecs.shape[1]), key
        def embed(self, img): return self.table[id(img)]
    fixed = Fixed()
    rec = Recognizer(fixed, gal)
    for name, v, p in zip(names, vecs, paths):
        marker = object()
        fixed.table[id(marker)] = v
        rec.learn_named(marker, name, quality=1.0, crop_ref=str(p.relative_to(p.parents[1])))
    return gal


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--embedder", default="dinov2_small.onnx#cls", help="'histogram' or a model file name in the models folder, with '#cls' / '#mean' for a ViT's pooling")
    ap.add_argument("--pictures", default=str(DEFAULT_PICTURES))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry", action="store_true", help="print the numbers, write nothing")
    a = ap.parse_args(argv)
    root = Path(a.pictures)
    if not root.is_dir():
        print(f"no pictures at {root}")
        return 1
    labelled = load_labelled(root)
    print(f"{sum(len(v) for v in labelled.values())} labelled pictures in {len(labelled)} objects")
    results = {}
    for key in ("histogram", a.embedder):
        emb = make_embedder(spec_for(key))
        names, vecs, paths = embed_all(labelled, emb)
        same, diff = similarity_groups(names, vecs)
        t_same, t_near = choose_thresholds(same, diff)
        results[key] = (names, vecs, paths, t_same, t_near)
        print(f"{key:24s} same-object {np.median(same):.3f} (25%: {np.percentile(same, 25):.3f})  different {np.median(diff):.3f} (95%: {np.percentile(diff, 95):.3f})  gap {np.median(same) - np.median(diff):.3f}  "
              f"leave-one-out {leave_one_out(names, vecs) * 100:.0f}%  thresholds {t_same} / {t_near}")
        print(f"{'':24s} at the same-instance threshold: {np.mean(same >= t_same) * 100:.0f}% of same-object pairs are recognised, {np.mean(diff >= t_same) * 100:.1f}% of different-object pairs are wrongly matched")
        if a.embedder == "histogram":
            break
    if a.dry:
        return 0
    names, vecs, paths, t_same, t_near = results[a.embedder]
    gal = build_gallery(names, vecs, paths, a.embedder, t_same, t_near)
    out = Path(os.path.expanduser(a.out))
    out.parent.mkdir(parents=True, exist_ok=True)
    gal.save(out)
    print(f"wrote {out}: {len(gal.entries)} entries, {sum(1 for e in gal.entries.values() if e.name)} named, embedder {a.embedder}, thresholds {t_same} / {t_near}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
