"""Place memory phase P1 (docs/plan-detail/place-memory-plan.md): record every survey stop, change nothing.

At a survey stop G2 stands still and takes one picture. `PlaceLog.record_stop(path, meta)` appends one JSON line for it to `<pictures root>/place_stops.jsonl` (so `g2pics pull` brings it to the Mac with the pictures):

    session        when this exploration session started (one id per run: yaw restarts every session, so it only means something inside one)
    n              the stop's number in the session, from 1
    picture        the picture's path under the pictures root (survey/<day>/after_bow_<time>.jpg), the key to rooms.json and the sidecar; null when the picture was a near-duplicate of one
                   already kept (the stop still counts: the same view again is a clue to the room)
    embedder, embedding    the picture as a unit vector (the histogram embedder; null when numpy / Pillow are missing on the Pi)
    wall           the newest wall reading (state, nearest inches, per-slice inches), a clue to the room's shape
    detections     what the camera detector saw (label, score, box), from the picture's sidecar
    yaw            the IMU yaw in degrees at the stop (relative, wanders), or null
    since_prev_s, yaw_change   the leg that led here: seconds since the previous stop and the turn (-180..180) between the two yaws; null for the first stop

Pure bookkeeping: it never moves G2, never calls the API, and a failure is logged and swallowed (a place record must never stop a survey). The work (one 96 x 96 embedding) happens while G2 is standing still.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("g2.place_log")

FILE_NAME = "place_stops.jsonl"


def _wrap_deg(d: float) -> float:
    return ((d + 180.0) % 360.0) - 180.0


def _histogram_embed(jpeg: bytes):
    from ..vision.embedder import make_embedder
    return make_embedder("histogram").embed(jpeg)


class PlaceLog:
    def __init__(self, root: str, *, yaw_fn=None, wall_fn=None, embed_fn=None, clock=time.time, session: str | None = None):
        self._root = Path(os.path.expanduser(str(root)))
        self._yaw_fn = yaw_fn                  # () -> degrees | None
        self._wall_fn = wall_fn                # () -> vision.wall_distance.WallReading | None
        self._embed_fn = embed_fn or _histogram_embed      # (jpeg bytes) -> unit vector
        self._clock = clock
        self.session = session or time.strftime("%Y%m%d_%H%M%S", time.localtime(clock()))
        self.n = 0
        self._prev: tuple[float, float | None] | None = None      # (time, yaw) of the previous stop
        self.path = self._root / FILE_NAME

    def _wall(self) -> dict | None:
        try:
            w = self._wall_fn() if self._wall_fn else None
        except Exception:  # noqa: BLE001
            return None
        if w is None:
            return None
        d = dict(vars(w)) if hasattr(w, "__dict__") else dict(w)
        return {k: v for k, v in d.items() if isinstance(v, (int, float, str, bool, list, tuple, type(None)))}

    def record_stop(self, path: str | None, meta: dict | None = None, jpeg: bytes | None = None) -> dict | None:
        """Append the record for the survey picture at `path` (None: a near-duplicate that was not kept; then `jpeg` is what the camera returned). Returns it, or None when it could not be written."""
        try:
            now = self._clock()
            p = Path(path) if path else None
            try:
                rel = str(p.relative_to(self._root)) if p else None
            except ValueError:
                rel = p.name
            try:
                yaw = None if self._yaw_fn is None else self._yaw_fn()
                yaw = None if yaw is None else round(float(yaw), 1)
            except Exception:  # noqa: BLE001
                yaw = None
            try:
                emb = [round(float(x), 4) for x in self._embed_fn(jpeg if jpeg is not None else p.read_bytes())]
            except Exception:  # noqa: BLE001 -- Pillow / numpy missing, or an unreadable file: the stop is still recorded
                log.debug("no embedding for %s", path, exc_info=True)
                emb = None
            since = yaw_change = None
            if self._prev is not None:
                since = round(now - self._prev[0], 1)
                if yaw is not None and self._prev[1] is not None:
                    yaw_change = round(_wrap_deg(yaw - self._prev[1]), 1)
            self.n += 1
            rec = {"session": self.session, "n": self.n, "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)), "picture": rel,
                   "embedder": "histogram" if emb is not None else None, "embedding": emb, "wall": self._wall(),
                   "detections": (meta or {}).get("detections", []), "yaw": yaw, "since_prev_s": since, "yaw_change": yaw_change}
            self._root.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            self._prev = (now, yaw)
            return rec
        except Exception:  # noqa: BLE001 -- never stop a survey for a place record
            log.exception("place record failed for %s", path)
            return None


def read_stops(path: str) -> list[dict]:
    """The records in a place_stops.jsonl, oldest first; unreadable lines are skipped."""
    out = []
    try:
        for line in Path(os.path.expanduser(path)).read_text().splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        pass
    return out
