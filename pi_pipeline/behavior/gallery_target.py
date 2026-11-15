"""Find a NAMED object in a picture with the Pi's object gallery, for the attentive bout (2026-11-15).

The camera's own detector knows three classes and found nothing in the bout's pictures. The gallery (`vision/object_gallery.py`: an embedding of each named object, the library exploration builds and
`g2pics` reviews) is what names objects in exploration ("toy body", "couch", "dishwasher"...). This module runs the same steps `vision/guess_labels.py` runs on a survey picture, on a picture taken
now: the localizer proposes object-like regions, each region's crop is embedded, and the closest NAMED gallery entry at or above `min_sim` becomes a detection in the bout's own format:
(label, score, cx, cy, w, h), all in frame fractions. The gallery is only read.

    python -m pi_pipeline.behavior.gallery_target --pictures 5 --target toy        # camera only: G2 does not move; the voice service is stopped (`g2seen`)
"""
from __future__ import annotations

import os
from pathlib import Path

MIN_SIM = float(os.environ.get("G2_TARGET_MIN_SIM", "0.45"))     # below the gallery's "a guess" line (0.55) on purpose: the bout follows slowly, and a wrong look is cheap
MAX_CANDIDATES = 3


class GalleryTargets:
    def __init__(self, scorer, gallery, *, min_sim: float = MIN_SIM, target: str | None = None):
        self.scorer, self.gallery, self.min_sim = scorer, gallery, min_sim
        self.target = target.strip().lower() if target else None     # a name (or part of one): only entries whose name contains it count

    def detections(self, jpeg: bytes) -> list:
        """Named matches in one picture as (label, similarity, cx, cy, w, h). Never raises: a picture that cannot be read gives []."""
        try:
            from ..vision.embedder import to_image
            from ..vision.interest import crop_quality
            im = to_image(jpeg)
            w, h = im.size
            out = []
            for cand in self.scorer.localizer.candidates(im)[:MAX_CANDIDATES]:
                x0, y0, x1, y1 = cand.box
                crop = im.crop((int(x0 * w), int(y0 * h), max(int(x0 * w) + 1, int(x1 * w)), max(int(y0 * h) + 1, int(y1 * h))))
                if crop_quality(crop) < self.scorer.min_quality:
                    continue
                emb = [float(v) for v in self.scorer.embedder.embed(crop)]
                entry, sim = self.gallery.match(emb, named_only=True)
                name = getattr(entry, "name", None)
                if not name or sim is None or float(sim) < self.min_sim:
                    continue
                if self.target and self.target not in str(name).lower():
                    continue
                out.append((str(name), float(sim), (x0 + x1) / 2.0, (y0 + y1) / 2.0, x1 - x0, y1 - y0))
            return out
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger("g2.gallery_target").debug("gallery matching failed", exc_info=True)
            return []


def open_targets(*, target: str | None = None, min_sim: float = MIN_SIM) -> GalleryTargets:
    """The recognizer exploration uses, read-only: the gallery file, the localizer and the embedder the gallery was built with."""
    from ..config import settings
    from ..vision.embedder import embedder_for
    from ..vision.interest import InterestScorer
    from ..vision.localizer import ForegroundLocalizer
    from ..vision.object_gallery import ObjectGallery, ObjectGalleryConfig
    gpath = os.path.join(os.path.expanduser(settings.object_gallery_dir), "gallery.json")
    gallery = ObjectGallery.load(gpath, ObjectGalleryConfig(lock_by_holdout=True))
    scorer = InterestScorer(ForegroundLocalizer(), embedder_for(gallery, os.environ.get("G2_EMBEDDER", "histogram")), gallery,
                            veto_labels=lambda: frozenset({"face", "person", "human"}))
    return GalleryTargets(scorer, gallery, min_sim=min_sim, target=target)


def main() -> None:
    """Camera only: take pictures and print what the camera's detector and the gallery each see. Moves nothing."""
    import argparse
    import time

    from ..config import settings
    from ..vision.snapshot import CameraSnapshotter
    ap = argparse.ArgumentParser(description="Camera-only check: what do the camera detector and the object gallery see? (G2 does not move)")
    ap.add_argument("--pictures", type=int, default=5)
    ap.add_argument("--target", default=None, help="only gallery entries whose name contains this")
    ap.add_argument("--min-sim", type=float, default=MIN_SIM)
    args = ap.parse_args()
    targets = open_targets(target=args.target, min_sim=args.min_sim)
    cam = CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump)
    outdir = Path(os.path.expanduser(time.strftime("~/g2_claw_pics/seen_%Y%m%d_%H%M%S")))
    outdir.mkdir(parents=True, exist_ok=True)
    hits = 0
    try:
        for i in range(1, args.pictures + 1):
            cam.discard_one()
            time.sleep(1.0)
            snap = cam.snapshot()
            if snap is None:
                print(f"picture {i}: no picture from the camera")
                continue
            (outdir / f"pic_{i:02d}.jpg").write_bytes(snap.jpeg)
            cam_dets = [f"{d[0]} {d[1]:.2f}" for d in snap.detections]
            t0 = time.monotonic()
            gal = targets.detections(snap.jpeg)
            hits += 1 if gal else 0
            print(f"picture {i}: camera detector: {', '.join(cam_dets) or 'nothing'} | gallery ({time.monotonic() - t0:.1f} s): "
                  + (", ".join(f"{g[0]} {g[1]:.2f} at x={g[2]:.2f}" for g in gal) or "nothing"))
    finally:
        cam.close()
    print(f"PICTURES: {outdir} ({args.pictures} pictures, the gallery matched in {hits})")


if __name__ == "__main__":
    main()
