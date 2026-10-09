"""What is worth a picture while G2 explores (user, 2026-10-09; plan: docs/vision/exploration-object-learning-plan.md).

"Interesting" = a clear object that is NOT a person and that the library does not already know completely:

  unknown     an object-like blob (the foreground localizer) whose fingerprint matches no named entry and no candidate that already has enough pictures waiting for a name
              -> take the picture routine (a few pictures from a little different spots) and add them to the library as an unnamed candidate
  reinforce   it matches a NAMED entry that is not locked yet -> take another picture to grow that entry, until the gallery's held-out rule locks it
  none        nothing object-like, the object is a locked (complete) entry, or the pictures of that candidate are already waiting for a name
  vetoed      the on-camera detector sees a person (a face, or anyone on the roster) in the frame: no picture at all

Pure logic over injected pieces (a localizer, an embedder, a gallery, a veto set); nothing here touches the camera or the motors."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Interest:
    kind: str                      # unknown | reinforce | none | vetoed
    reason: str
    box: tuple | None = None       # x0, y0, x1, y1 as fractions of the picture
    score: float = 0.0
    entry_id: str | None = None
    name: str | None = None


def crop_quality(img) -> float:
    """0..1 for a crop: big enough, neither dark nor blown out, and not blurry (edge energy). Used as the gallery's `quality`."""
    import numpy as np
    from .embedder import to_image
    im = to_image(img).convert("L")
    a = np.asarray(im, dtype=float)
    h, w = a.shape
    size = min(1.0, (h * w) / (48 * 48))
    mean = a.mean()
    light = 1.0 if 45 <= mean <= 215 else 0.5
    edge = float(np.abs(np.diff(a, axis=0)).mean() + np.abs(np.diff(a, axis=1)).mean()) if h > 2 and w > 2 else 0.0
    sharp = min(1.0, edge / 6.0)
    return round(size * light * (0.4 + 0.6 * sharp), 3)


class InterestScorer:
    def __init__(self, localizer, embedder, gallery, *, veto_labels=lambda: frozenset({"face", "person", "human"}), pending_samples: int = 3,
                 min_detection_score: float = 0.3, min_quality: float = 0.35):
        self.localizer, self.embedder, self.gallery = localizer, embedder, gallery
        self._veto = veto_labels                    # a callable: the roster can change while he explores
        self.pending_samples = pending_samples      # an unnamed candidate with this many pictures is waiting for a name: no more pictures of it
        self.min_detection_score, self.min_quality = min_detection_score, min_quality

    def vetoed(self, snap) -> str | None:
        labels = {str(x).lower() for x in self._veto()}
        for d in getattr(snap, "detections", None) or []:
            if str(d[0]).lower() in labels and float(d[1]) >= self.min_detection_score:
                return str(d[0])
        return None

    def assess(self, snap) -> Interest:
        """`snap` has `.jpeg` (bytes) and `.detections`."""
        who = self.vetoed(snap)
        if who is not None:
            return Interest("vetoed", f"a person is in view ({who}): no picture")
        from .embedder import to_image
        im = to_image(snap.jpeg)
        w, h = im.size
        best_pending = None
        for cand in self.localizer.candidates(im)[:3]:
            x0, y0, x1, y1 = cand.box
            crop = im.crop((int(x0 * w), int(y0 * h), max(int(x0 * w) + 1, int(x1 * w)), max(int(y0 * h) + 1, int(y1 * h))))
            if crop_quality(crop) < self.min_quality:
                continue
            emb = [float(v) for v in self.embedder.embed(crop)]
            entry, sim = self.gallery.match(emb, named_only=True)
            if entry is not None and sim >= self.gallery.cfg.same_instance_threshold:
                if entry.locked:
                    continue                                                   # known and complete: nothing to learn
                return Interest("reinforce", f"looks like '{entry.name}' ({sim:.2f}): one more picture", cand.box, cand.score, entry.id, entry.name)
            other, osim = self.gallery.match(emb, named_only=False)
            if other is not None and not other.labeled and osim >= self.gallery.cfg.same_instance_threshold:
                if other.sample_count >= self.pending_samples:
                    best_pending = best_pending or Interest("none", "its pictures are already waiting for a name", cand.box, cand.score, other.id)
                    continue
                return Interest("unknown", f"the same unnamed object as before ({osim:.2f}), still needs pictures", cand.box, cand.score, other.id)
            return Interest("unknown", "an object-like thing that matches nothing in the library", cand.box, cand.score)
        return best_pending or Interest("none", "nothing object-like and new in view")
