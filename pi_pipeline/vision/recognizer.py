"""Recognition by instance: embedder + localizer + ObjectGallery (plan Phase 5, not yet switched on in the exploration session).

    rec = Recognizer(make_embedder("histogram"))
    rec.learn_named(jpeg, "dishwasher")           # embeds the whole picture, adds / extends the entry and names it
    rec.recognize(jpeg)                           # [Recognition(name, similarity, box, whole)], best first, named entries only

Every view of a picture (the whole picture and each tile) is embedded and matched against the named entries; a view is a hit when its similarity reaches `threshold` (default: the gallery's
`same_instance_threshold`). One Recognition per name: the best view. The announce / ask wording and cooldowns are the driver's job (Phase 5 step 3-4); this class only answers "what do I see".
"""
from __future__ import annotations

from dataclasses import dataclass

from .embedder import Embedder, HistogramEmbedder
from .localizer import GridLocalizer
from .object_gallery import GalleryDecision, ObjectGallery


@dataclass(frozen=True)
class Recognition:
    name: str
    entry_id: str
    similarity: float
    box: tuple[float, float, float, float]
    whole: bool


class Recognizer:
    def __init__(self, embedder: Embedder | None = None, gallery: ObjectGallery | None = None, localizer: GridLocalizer | None = None, threshold: float | None = None):
        self.embedder = embedder or HistogramEmbedder()
        self.gallery = gallery or ObjectGallery()
        self.localizer = localizer or GridLocalizer()
        self.threshold = self.gallery.cfg.same_instance_threshold if threshold is None else threshold
        self.last_conflict: tuple[str, float] | None = None

    def recognize(self, img) -> list[Recognition]:
        best: dict[str, Recognition] = {}
        for view, crop in self.localizer.views(img):
            entry, sim = self.gallery.match([float(x) for x in self.embedder.embed(crop)], named_only=True)
            if entry is None or sim < self.threshold:
                continue
            cur = best.get(entry.name)
            if cur is None or sim > cur.similarity:
                best[entry.name] = Recognition(entry.name, entry.id, float(sim), view.box, view.whole)
        return sorted(best.values(), key=lambda r: -r.similarity)

    def learn_named(self, img, name: str, *, quality: float = 1.0, crop_ref: str | None = None) -> GalleryDecision | None:
        """Teach the gallery a named picture: embed the whole picture, add it to the entry it matches (or a new one) and give the entry `name`. A picture too close to a sample the entry
        already has is skipped (DUPLICATE) and a locked entry is not resampled (LOCKED); both still leave the entry named. If the picture looks like an entry that already has a DIFFERENT name,
        nothing is changed and None is returned (`last_conflict` says which name and how close): two names for look-alikes is a decision for the person, not an overwrite."""
        vec = [float(x) for x in self.embedder.embed(img)]
        self.last_conflict = None
        entry, sim = self.gallery.match(vec, named_only=False)
        if entry is not None and sim >= self.gallery.cfg.same_instance_threshold and entry.name not in (None, name):
            self.last_conflict = (entry.name, float(sim))
            return None
        decision = self.gallery.consider(vec, quality=quality, crop_ref=crop_ref)
        eid = self.gallery.last_entry_id
        if eid is not None and eid in self.gallery.entries:
            self.gallery.set_name(eid, name)
        return decision
