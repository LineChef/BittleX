"""Picture stops only when something is worth a picture (user, 2026-10-09): replaces the pure timer behind the survey stops.

While he explores, a small background loop takes a cheap look every `every_s` seconds (a camera snapshot that is only ASSESSED, not saved), asks the `InterestScorer` whether an unknown
object or an unfinished named one is in view and no person is, and remembers the answer for `fresh_s` seconds. The survey asks `gate()` at the end of each leg (after its own cooldown):
yes when a fresh interesting sighting is waiting, or, as a slow fallback, when `fallback_s` have passed without any picture stop (so floor-level data still accumulates when the
localizer sees nothing). `GalleryFeeder` is the other half: every picture the survey saves is localized, fingerprinted and shown to the gallery, which keeps unnamed candidates,
grows named ones and locks them by the held-out rule (vision/object_gallery.py)."""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger("g2.interest")


class InterestWatch:
    def __init__(self, scorer, source, *, every_s: float = 10.0, fresh_s: float = 20.0, fallback_s: float = 300.0, active=lambda: True, clock=time.monotonic):
        self.scorer, self._source = scorer, source
        self.every_s, self.fresh_s, self.fallback_s = every_s, fresh_s, fallback_s
        self._active, self._clock = active, clock
        self._lock = threading.Lock()
        self.latest = None                           # (time, Interest) of the newest worthwhile sighting, until a picture stop uses it
        self._last_peek = float("-inf")
        self._last_stop = clock()                    # the fallback counts from the start of the session
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.peeks = self.vetoes = 0

    def peek_once(self, now: float | None = None):
        now = self._clock() if now is None else now
        self._last_peek = now
        try:
            snap = self._source.snapshot(settle=0)
        except TypeError:
            snap = self._source.snapshot()
        except Exception:  # noqa: BLE001
            log.debug("peek failed", exc_info=True)
            return None
        if snap is None:
            return None
        self.peeks += 1
        try:
            got = self.scorer.assess(snap)
        except Exception:  # noqa: BLE001 -- a bad frame must never take the loop down
            log.debug("assessing a peek failed", exc_info=True)
            return None
        if got.kind == "vetoed":
            self.vetoes += 1
        log.info("peek: %s (%s)", got.kind, got.reason)
        if got.kind in ("unknown", "reinforce"):
            with self._lock:
                self.latest = (now, got)
        return got

    def gate(self, now: float | None = None) -> bool:
        """For `Survey.gate`: True when a picture stop should happen now; using the answer consumes it."""
        now = self._clock() if now is None else now
        with self._lock:
            if self.latest is not None and now - self.latest[0] <= self.fresh_s:
                log.info("picture stop: %s", self.latest[1].reason)
                self.latest, self._last_stop = None, now
                return True
            if now - self._last_stop >= self.fallback_s:
                log.info("picture stop: the slow fallback (%.0f s without one)", self.fallback_s)
                self._last_stop = now
                return True
        return False

    def start(self) -> "InterestWatch":
        def loop() -> None:
            while not self._stop.wait(0.5):
                try:
                    if self._active() and self._clock() - self._last_peek >= self.every_s:
                        self.peek_once()
                except Exception:  # noqa: BLE001
                    log.debug("interest loop error", exc_info=True)
        self._thread = threading.Thread(target=loop, name="interest-watch", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)


class GalleryFeeder:
    """`ExplorationPictureSaver(on_saved=...)`: show each saved picture to the object gallery. Pictures with a person in them are not used (the sidecar's detector labels)."""

    def __init__(self, scorer, gallery, gallery_path: str, *, clock=time.time):
        self.scorer, self.gallery, self._path, self._clock = scorer, gallery, Path(gallery_path), clock
        self.added = self.skipped = 0

    def __call__(self, path) -> None:
        from .. vision.interest import crop_quality
        from ..vision.embedder import to_image
        try:
            p = Path(path)
            meta = {}
            try:
                meta = json.loads(p.with_suffix(".json").read_text())
            except (OSError, ValueError):
                pass
            veto = {str(x).lower() for x in self.scorer._veto()}
            if any(str(d.get("label", "")).lower() in veto and float(d.get("score", 0)) >= self.scorer.min_detection_score for d in meta.get("detections", [])):
                self.skipped += 1
                return
            im = to_image(p.read_bytes())
            w, h = im.size
            for cand in self.scorer.localizer.candidates(im)[:2]:
                x0, y0, x1, y1 = cand.box
                crop = im.crop((int(x0 * w), int(y0 * h), max(int(x0 * w) + 1, int(x1 * w)), max(int(y0 * h) + 1, int(y1 * h))))
                emb = [float(v) for v in self.scorer.embedder.embed(crop)]
                d = self.gallery.consider(emb, quality=crop_quality(crop), now=self._clock(), crop_ref=f"{p.name}@{x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}")
                self.added += 1
                log.info("gallery: %s (%s)", d.value, p.name)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self.gallery.save(self._path)
        except Exception:  # noqa: BLE001 -- the picture is saved either way
            log.debug("feeding the gallery failed", exc_info=True)
