"""Saves the pictures G2 takes while exploring, with a JSON sidecar each, for building a training / recognition set.

    ~/.local/share/g2/explore_pictures/survey/<YYYYMMDD>/<pose>_<time>.jpg (+ .json)      the survey stops (look down, look up)
    ~/.local/share/g2/explore_pictures/named/<name>/<name>_<time>.jpg (+ .json)           a picture you named by voice ("this is a mug")

`ExplorationPictureSaver(source, root)` is the callable the camera binding calls with a kind: "look_down", "look_up" or "name:<name>". `source` has a
`snapshot()` that returns a `vision.snapshot.Snapshot` (the detection feed's own port, see `BackgroundFrameSource.snapshot`). One USB request to the
camera; no network and no API call. The pictures stay on the Pi; `tools/curate_exploration.py` processes them on the Mac after you copy them.
The sidecar carries the pose, the time, what the on-camera detector saw (label, score, box) and the picture's brightness, so the processing step can
filter without opening every picture."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

log = logging.getLogger("g2.exploration_pictures")

DEFAULT_ROOT = "~/.local/share/g2/explore_pictures"
_SLUG = re.compile(r"[^a-z0-9\-]+")


def slug(text: str) -> str:
    return _SLUG.sub("_", (text or "").lower().replace(" ", "-")).strip("_") or "x"


class ExplorationPictureSaver:
    def __init__(self, source, root: str = DEFAULT_ROOT, *, clock=time.time, warn_mb: float = 500.0, on_saved=None):
        self._source = source
        self._root = Path(os.path.expanduser(root))
        self._clock = clock
        self._warn_mb = warn_mb
        self._on_saved = on_saved                  # called with the saved path (a shutter tick, a counter)
        self.count = 0
        self.last_path: str | None = None
        self.last_kind: str | None = None

    def folder_for(self, kind: str, now: float) -> Path:
        if kind.startswith("name:"):
            return self._root / "named" / slug(kind[5:])
        return self._root / "survey" / time.strftime("%Y%m%d", time.localtime(now))

    def __call__(self, kind) -> str | None:
        kind = str(kind or "picture")
        snap = self._source.snapshot()
        if snap is None:
            log.warning("no picture for %s (the camera did not answer)", kind)
            return None
        now = self._clock()
        folder = self.folder_for(kind, now)
        folder.mkdir(parents=True, exist_ok=True)
        pose = "named" if kind.startswith("name:") else kind
        base = (slug(kind[5:]) if kind.startswith("name:") else pose) + time.strftime("_%H%M%S", time.localtime(now)) + f"_{int((now % 1) * 1000):03d}"
        path = folder / (base + ".jpg")
        path.write_bytes(snap.jpeg)
        meta = {"file": path.name, "kind": kind, "pose": pose, "name": kind[5:] if kind.startswith("name:") else None,
                "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "width": snap.width, "height": snap.height,
                "detections": [{"label": d[0], "score": round(float(d[1]), 3), "cx": round(float(d[2]), 3), "cy": round(float(d[3]), 3),
                                "w": round(float(d[4]), 3), "h": round(float(d[5]), 3)} for d in (snap.detections or [])]}
        try:
            from .snapshot import exposure_stats
            st = exposure_stats(snap.jpeg)
            meta["exposure"] = None if st is None else {"mean": round(st.mean, 1), "clip_high": round(st.clip_high, 4), "clip_low": round(st.clip_low, 4)}
        except Exception:  # noqa: BLE001 -- Pillow may be missing on the Pi
            meta["exposure"] = None
        path.with_suffix(".json").write_text(json.dumps(meta))
        self.count += 1
        self.last_path, self.last_kind = str(path), kind
        log.info("picture saved: %s (%s)", path, kind)
        self._check_size()
        if self._on_saved:
            try:
                self._on_saved(str(path))
            except Exception:  # noqa: BLE001
                log.debug("on_saved hook failed", exc_info=True)
        return str(path)

    def _check_size(self) -> None:
        if self.count % 25:
            return
        try:
            total = sum(f.stat().st_size for f in self._root.rglob("*") if f.is_file()) / 1e6
            if total > self._warn_mb:
                log.warning("exploration pictures use %.0f MB (warning at %.0f MB): copy them off and clear %s", total, self._warn_mb, self._root)
        except OSError:
            pass
