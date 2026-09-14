"""ObjectGallery -- the recognition-by-instance library for B20's "separate
Pi-side layer" path (`docs/behavior-ideas.md` B20): recognise a *specific*
object it's seen before ("I've seen this exact thing"), not classify it into
a trained category. No retraining, ever -- the library grows by accumulating
**fingerprints** (embedding vectors) of things it's seen, matched by
similarity.

Pure decision logic, same shape as `cliff_guard.py` / `avoidance.py`: an
embedding + a quality score in, a `GalleryDecision` out, no I/O, no ML. Two
hardware/model halves are deliberately NOT here (STUBBED, same pattern as
`cliff_guard.py`'s `EdgeReading` producer):

  * THE LOCALIZER -- what decides "something worth looking at is in frame"
    (motion/frame-diff or a generic saliency model on the Pi). Not built --
    needs the real camera to tune. `behavior/object_seek.py` is the *when is
    it safe to try* gate; it doesn't localize either.
  * THE EMBEDDING MODEL -- what turns an image crop into the vector this
    module compares. Not chosen yet. This module works with whatever vector
    it's handed; swapping models later doesn't change anything here (though
    it invalidates any already-stored centroids, since they'd be in a
    different embedding space -- a model change means starting the gallery
    over, not a migration).

Storage: `object_gallery_dir` (`.env` `G2_OBJECT_GALLERY_DIR`, default
`~/.local/share/g2/object_gallery` -- same "personal data lives outside the
repo" rule as `memory_db_path`). This module never touches the filesystem for
images -- `crop_ref` is just an opaque string (a filename) the caller manages;
`save`/`load` persist the index (names, centroids, sample counts) as JSON.

Storage-space answers this directly implements (from the design conversation):
  * **dedup** -- `same_instance_threshold` collapses re-sightings of the same
    object into one entry instead of a new one each time; `near_duplicate_
    threshold` (tighter) skips saving another sample of an already
    well-represented instance.
  * **quality filter** -- `consider()` refuses anything under `min_quality`
    before it ever touches the gallery. The actual pixel-level score (blur /
    brightness / crop-size ratio, `tools/curate_captures.py`-style) is
    computed by the caller and passed in, same as `Enrollment`'s
    `face_quality` -- keeps this module free of an image-processing
    dependency.
  * **a cap, with eviction** -- `max_entries` (entry count) and an optional
    `disk_bytes_used` ceiling (`max_total_mb`, checked by the caller against
    real on-disk size and passed in -- this module doesn't stat files).
    Eviction is oldest-`last_seen` first, and **never** touches a named or
    `locked` entry -- only unnamed, not-yet-reviewed ones are ever silently
    dropped, so nothing you cared enough to label is ever auto-deleted.
  * **"enough data" per object** -- `locked`. Set automatically once an
    entry's `sample_count` reaches `max_samples_per_entry` (a sane default so
    it happens even if nobody's reviewing yet), or manually via
    `mark_complete()` from the review tool. A locked entry keeps recognising
    (its `last_seen` still updates) but never accumulates another sample.
"""
from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class GalleryDecision(Enum):
    NEW = "new"                         # no match close enough -- a fresh entry created
    ADD_SAMPLE = "add_sample"           # matched an existing entry, added another sample
    DUPLICATE = "duplicate"             # matched, but too similar to an existing sample -- skipped
    LOW_QUALITY = "low_quality"         # refused before ever comparing -- quality < min_quality
    LOCKED = "locked"                   # matched a `locked` entry -- recognised, not resampled
    REJECTED_AT_CAPACITY = "rejected_at_capacity"  # would-be NEW, but no room and nothing evictable


@dataclass
class GalleryEntry:
    id: str
    centroid: list[float]               # running-average embedding across its samples
    sample_count: int = 1
    name: str | None = None
    note: str | None = None
    locked: bool = False                # "enough data" -- stop accumulating samples
    crop_files: list[str] = field(default_factory=list)   # opaque refs the caller manages
    first_seen: float = 0.0             # wall-clock epoch seconds
    last_seen: float = 0.0

    @property
    def labeled(self) -> bool:
        return self.name is not None


@dataclass
class ObjectGalleryConfig:
    max_entries: int = 200               # entry-count cap; oldest unnamed/unlocked evicted over this
    max_samples_per_entry: int = 5       # auto-lock once an entry has this many samples
    max_total_mb: int = 200              # hard ceiling; caller measures real bytes and passes them in
    same_instance_threshold: float = 0.80   # cosine sim >= this -> "the same thing I've seen"
    near_duplicate_threshold: float = 0.93  # cosine sim >= this -> not worth another sample
    min_quality: float = 0.35            # quality score (0..1) below this is refused outright


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class ObjectGallery:
    def __init__(self, cfg: ObjectGalleryConfig | None = None, *, clock=time.time):
        self.cfg = cfg or ObjectGalleryConfig()
        self._clock = clock
        self.entries: dict[str, GalleryEntry] = {}
        self.last_decision: GalleryDecision | None = None
        self.last_entry_id: str | None = None

    # ------------------------------------------------------------- consider

    def consider(self, embedding: list[float], *, quality: float, now: float | None = None,
                crop_ref: str | None = None, disk_bytes_used: int | None = None) -> GalleryDecision:
        """One candidate sighting in, one decision out. `quality` is the
        caller's own 0..1 score (blur/brightness/crop-size -- see module
        docstring); `disk_bytes_used` is the caller's real on-disk total for
        the gallery, if it wants the byte ceiling enforced (omit to skip it
        and rely on `max_entries` alone)."""
        now = self._clock() if now is None else now
        if quality < self.cfg.min_quality:
            return self._done(GalleryDecision.LOW_QUALITY, None)

        best_id, best_sim = self._best_match(embedding)
        if best_id is not None and best_sim >= self.cfg.same_instance_threshold:
            entry = self.entries[best_id]
            entry.last_seen = now
            if entry.locked:
                return self._done(GalleryDecision.LOCKED, best_id)
            if best_sim >= self.cfg.near_duplicate_threshold:
                return self._done(GalleryDecision.DUPLICATE, best_id)
            self._add_sample(entry, embedding, crop_ref)
            if entry.sample_count >= self.cfg.max_samples_per_entry:
                entry.locked = True
            return self._done(GalleryDecision.ADD_SAMPLE, best_id)

        over_byte_cap = (disk_bytes_used is not None
                        and disk_bytes_used >= self.cfg.max_total_mb * 1_000_000)
        if len(self.entries) >= self.cfg.max_entries or over_byte_cap:
            if not self._evict_one():
                return self._done(GalleryDecision.REJECTED_AT_CAPACITY, None)

        eid = uuid.uuid4().hex[:12]
        self.entries[eid] = GalleryEntry(
            id=eid, centroid=list(embedding), sample_count=1,
            crop_files=[crop_ref] if crop_ref else [],
            first_seen=now, last_seen=now)
        return self._done(GalleryDecision.NEW, eid)

    def _done(self, decision: GalleryDecision, entry_id: str | None) -> GalleryDecision:
        self.last_decision, self.last_entry_id = decision, entry_id
        return decision

    def _best_match(self, embedding: list[float]) -> tuple[str | None, float]:
        best_id, best_sim = None, -1.0
        for eid, entry in self.entries.items():
            sim = _cosine(embedding, entry.centroid)
            if sim > best_sim:
                best_id, best_sim = eid, sim
        return best_id, best_sim

    @staticmethod
    def _add_sample(entry: GalleryEntry, embedding: list[float], crop_ref: str | None) -> None:
        n = entry.sample_count
        entry.centroid = [(c * n + e) / (n + 1) for c, e in zip(entry.centroid, embedding)]
        entry.sample_count = n + 1
        if crop_ref:
            entry.crop_files.append(crop_ref)

    def _evict_one(self) -> bool:
        """Oldest `last_seen` among unnamed, unlocked entries. Never touches a
        named or locked entry -- nothing you cared enough to label or that's
        already flagged complete is ever silently dropped."""
        candidates = [e for e in self.entries.values() if not e.labeled and not e.locked]
        if not candidates:
            return False
        victim = min(candidates, key=lambda e: e.last_seen)
        del self.entries[victim.id]
        return True

    # --------------------------------------------------------------- review

    def set_name(self, entry_id: str, name: str, note: str | None = None) -> None:
        e = self.entries[entry_id]
        e.name = name
        if note is not None:
            e.note = note

    def mark_complete(self, entry_id: str) -> None:
        self.entries[entry_id].locked = True

    def mark_incomplete(self, entry_id: str) -> None:
        self.entries[entry_id].locked = False

    def discard(self, entry_id: str) -> list[str]:
        """Remove an entry (junk -- a shadow, blur, a false trigger). Returns
        its crop_files so the caller can delete the actual image files too."""
        return self.entries.pop(entry_id).crop_files

    # ---------------------------------------------------------- persistence

    def to_dict(self) -> dict:
        return {"entries": {eid: vars(e) for eid, e in self.entries.items()}}

    @classmethod
    def from_dict(cls, data: dict, cfg: ObjectGalleryConfig | None = None, *,
                 clock=time.time) -> "ObjectGallery":
        g = cls(cfg, clock=clock)
        for eid, ev in data.get("entries", {}).items():
            g.entries[eid] = GalleryEntry(**ev)
        return g

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str | Path, cfg: ObjectGalleryConfig | None = None, *,
             clock=time.time) -> "ObjectGallery":
        p = Path(path)
        if not p.exists():
            return cls(cfg, clock=clock)
        return cls.from_dict(json.loads(p.read_text()), cfg, clock=clock)
