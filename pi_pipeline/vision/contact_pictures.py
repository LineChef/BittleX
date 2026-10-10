"""Contact pictures: what the camera sees at the moment G2 seems to be pushing into something (user, 2026-10-10: "make contact pictures instant and see what we capture").

On 2026-10-10 two walk legs showed the stall signature in the IMU while the wall estimator said "clear", and nothing recorded what he saw. When the IMU stall suspect fires
(`gait/imu_stall.py`, the short-window version) or the hit-the-wall sequence starts, this grabs the newest camera frame at once and a second one 0.6 s later (a plain
`snapshot(settle=0)`: no warm-up, no wait for stillness, because he is shaking against the wall). Frames are for DIAGNOSIS only: they are never offered to the object gallery, the recognition
set or the wall calibration. Each is saved with a JSON sidecar (reason, time, the IMU numbers, the last wall look). A ring of the newest `cap` frames stays. It runs in its own thread, never raises,
and never changes what G2 does.

    ~/.local/share/g2/contact_pictures/contact_<YYYYMMDD_HHMMSS>_<reason>_<n>.jpg (+ .json)        (`G2_CONTACT_PICS_DIR`)   `G2_CONTACT_PICS=0` turns it off
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("g2.contact_pictures")

DEFAULT_DIR = "~/.local/share/g2/contact_pictures"


class ContactPictures:
    def __init__(self, source, root: str | None = None, *, cap: int = 30, cooldown_s: float = 4.0, second_after_s: float = 0.6,
                 context=lambda: {}, clock=time.monotonic, sleep=time.sleep, threaded: bool = True):
        self._source = source
        self._root = Path(os.path.expanduser(root or os.environ.get("G2_CONTACT_PICS_DIR", DEFAULT_DIR)))
        self.cap, self.cooldown_s, self.second_after_s = cap, cooldown_s, second_after_s
        self._context, self._clock, self._sleep, self._threaded = context, clock, sleep, threaded
        self._last = float("-inf")
        self._lock = threading.Lock()
        self.enabled = os.environ.get("G2_CONTACT_PICS", "1") != "0"
        self.saved: list[str] = []

    def capture(self, reason: str, extra: dict | None = None) -> bool:
        """Start a capture (returns False if disabled or inside the cooldown). Safe to call from the walk loop: the camera work happens in a thread."""
        if not self.enabled or self._source is None:
            return False
        now = self._clock()
        with self._lock:
            if now - self._last < self.cooldown_s:
                return False
            self._last = now
        if self._threaded:
            threading.Thread(target=self._run, args=(reason, dict(extra or {})), name="contact-pictures", daemon=True).start()
        else:
            self._run(reason, dict(extra or {}))
        return True

    def _frame(self):
        try:
            return self._source.snapshot(settle=0)
        except TypeError:
            return self._source.snapshot()

    def _run(self, reason: str, extra: dict) -> None:
        try:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            self._root.mkdir(parents=True, exist_ok=True)
            try:
                ctx = dict(self._context() or {})
            except Exception:  # noqa: BLE001
                ctx = {}
            for n in (1, 2):
                if n == 2:
                    self._sleep(self.second_after_s)
                snap = self._frame()
                if snap is None or not getattr(snap, "jpeg", None):
                    continue
                base = self._root / f"contact_{stamp}_{reason}_{n}"
                base.with_suffix(".jpg").write_bytes(snap.jpeg)
                base.with_suffix(".json").write_text(json.dumps({"reason": reason, "frame": n, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "extra": extra, "context": ctx,
                                                                 "detections": [list(d) for d in (getattr(snap, "detections", None) or [])]}, default=str))
                self.saved.append(str(base.with_suffix(".jpg")))
            self._trim()
            log.info("contact pictures (%s): %s", reason, ", ".join(Path(p).name for p in self.saved[-2:]))
        except Exception:  # noqa: BLE001
            log.exception("contact pictures failed")

    def _trim(self) -> None:
        jpgs = sorted(self._root.glob("contact_*.jpg"))
        for old in jpgs[:-self.cap]:
            old.unlink(missing_ok=True)
            old.with_suffix(".json").unlink(missing_ok=True)
