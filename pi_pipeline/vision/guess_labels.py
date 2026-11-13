"""A suggested label for each survey picture (owner, 2026-11-12: "label the objects it finds based on what it thinks it is, and then I can review and modify as needed later").

When the exploration saves a survey picture, this looks at it once in the background and writes a `guess` into the picture's sidecar:
  - the closest NAMED object in the gallery (the embedding of each object-like region against what you have named: a read-only match, the gallery is never changed), or
  - the label of the camera's own detector when it fired (it only knows a few classes, so mostly it does not),
  - or nothing: "unknown", with the closest name and its similarity kept so you can see how near it was.
The Pictures tab of g2pics shows it as "G2 thinks: ..." with Accept; naming a picture there is still what feeds the gallery (survey pictures never do by themselves, 2026-10-10). A picture with a person
in it gets no guess. Nothing here calls the API; the work runs on one background thread so a look is never held up by it.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path

log = logging.getLogger("g2.guess_labels")

MIN_SIM = float(os.environ.get("G2_GUESS_MIN_SIM", "0.55"))     # the closest named object counts as a guess at this cosine similarity or more (the gallery calls 0.80 "the same thing")
PEOPLE = frozenset({"person", "face", "human"})
DETECTOR_MIN = 0.30                                              # the camera detector's own score for its label to count


def make_guess(meta: dict, regions: list[dict], *, min_sim: float = MIN_SIM) -> dict:
    """The guess for one picture. `meta` is its sidecar; `regions` the object-like regions already matched: [{"box": [x0, y0, x1, y1], "closest": name or None, "sim": float or None}]."""
    guess = {"label": None, "score": None, "source": None, "objects": regions, "made": time.strftime("%Y-%m-%d %H:%M:%S")}
    best = max((r for r in regions if r.get("closest") and r.get("sim") is not None), key=lambda r: r["sim"], default=None)
    if best is not None and best["sim"] >= min_sim:
        guess.update(label=best["closest"], score=round(float(best["sim"]), 2), source="gallery")
        return guess
    dets = [d for d in (meta.get("detections") or []) if str(d.get("label", "")) and float(d.get("score", 1.0)) >= DETECTOR_MIN]
    if dets:
        top = max(dets, key=lambda d: float(d.get("score", 0.0)))
        guess.update(label=str(top["label"]).lower(), score=round(float(top.get("score", 0.0)), 2), source="detector")
    return guess


def _person_in(meta: dict) -> bool:
    return any(str(d.get("label", "")).lower() in PEOPLE and float(d.get("score", 1.0)) >= DETECTOR_MIN for d in (meta.get("detections") or []))


class GuessLabeler:
    """`ExplorationPictureSaver(on_survey=...)`: queue each saved survey picture and write its guess into the sidecar from one background thread."""

    def __init__(self, scorer, gallery, *, min_sim: float | None = None, threaded: bool = True):
        self.scorer, self.gallery = scorer, gallery
        self.min_sim = MIN_SIM if min_sim is None else min_sim
        self._q: queue.Queue = queue.Queue()
        self._threaded, self._thread = threaded, None
        self.done = self.skipped = self.failed = 0

    def __call__(self, path) -> None:
        if not self._threaded:
            self.guess_for(path)
            return
        self._q.put(str(path))
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._run, name="guess-labels", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        while True:
            try:
                path = self._q.get(timeout=30)
            except queue.Empty:
                return
            try:
                self.guess_for(path)
            finally:
                self._q.task_done()

    def wait(self, timeout: float = 30.0) -> bool:
        """Until the queue is worked off (tests). True when it is."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self._q.unfinished_tasks == 0:
                return True
            time.sleep(0.05)
        return False

    def guess_for(self, path) -> dict | None:
        """Work out and save the guess of one picture. Never raises."""
        try:
            p = Path(path)
            js = p.with_suffix(".json")
            try:
                meta = json.loads(js.read_text())
            except (OSError, ValueError):
                meta = {}
            if _person_in(meta):
                self.skipped += 1                                                       # a person is in it: no guess, and nothing is looked at
                return None
            from .embedder import to_image
            from .interest import crop_quality
            im = to_image(p.read_bytes())
            w, h = im.size
            regions = []
            for cand in self.scorer.localizer.candidates(im)[:2]:
                x0, y0, x1, y1 = cand.box
                crop = im.crop((int(x0 * w), int(y0 * h), max(int(x0 * w) + 1, int(x1 * w)), max(int(y0 * h) + 1, int(y1 * h))))
                if crop_quality(crop) < self.scorer.min_quality:
                    continue
                emb = [float(v) for v in self.scorer.embedder.embed(crop)]
                entry, sim = self.gallery.match(emb, named_only=True)
                regions.append({"box": [round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2)], "closest": getattr(entry, "name", None), "sim": None if entry is None else round(float(sim), 2)})
            g = make_guess(meta, regions, min_sim=self.min_sim)
            meta["guess"] = g
            tmp = js.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(meta))
            os.replace(tmp, js)                                                         # the sidecar is replaced whole: a reader never sees half of it
            self.done += 1
            log.info("guess for %s: %s", p.name, f"{g['label']} ({g['score']}, {g['source']})" if g["label"] else "unknown")
            return g
        except Exception:  # noqa: BLE001 -- the picture is saved either way
            self.failed += 1
            log.debug("guessing a label failed", exc_info=True)
            return None
