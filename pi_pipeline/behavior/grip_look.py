"""The grip look: one claw-camera picture right after the pick-up, to see whether the cylinder is held (the basket goal, docs/plan-detail/basket-goal-plan.md). LOG ONLY: the throw always goes ahead whatever it says.

A cylinder held in the claw fills the bottom centre of the picture between the jaws as a large block of its saturated colours. `classify` measures that block (its pixel count and centre) in the bottom region of the frame and says `good` when it matches the
good grips, `none` when there is almost nothing there, and `unclear` when something is there but it does not look like a good grip (a bad grab, or the cylinder on the floor touching the claw). THE NUMBERS ARE PROVISIONAL: they come from three good-grip pictures
(1,719 to 1,860 pixels, centred near column 135 and row 222) and one bad grab (5,114 pixels, centred near row 208), a cylinder on the floor at the claw (2,510 pixels, row 177) and a sliver at claw lift 120 (180 pixels); more bad-grab pictures are to be taken
(docs/plan-detail/basket-goal-plan.md) and the thresholds set from them.

`GripLooker` opens the camera and takes a throwaway picture in a background thread while G2 stands up, so the real picture right after the pick-up is fast; `take_grip_look` never raises: a camera that does not answer is logged as an error and the throw goes on.
"""
from __future__ import annotations

import io
import os
import threading
import time

import numpy as np

REGION = (120, 240, 40, 200)                 # rows 120 to 240, columns 40 to 200: the bottom of the frame between the jaws
SAT_MIN, VAL_MIN = 0.30, 70
NONE_BELOW_PX = 300
GOOD_PX = (1200, 3200)                       # the good grips were 1,719 to 1,860; the one bad grab (5,114) is outside
GOOD_ROW_MIN = 205
GOOD_COL = (100, 170)
SAVE_DIR = "~/g2_runs/grip_looks"


def classify(jpeg_or_rgb) -> dict:
    """{"verdict": "good" | "unclear" | "none", "n", "cx", "cy"} for a picture (jpeg bytes or an RGB array)."""
    if isinstance(jpeg_or_rgb, (bytes, bytearray)):
        from PIL import Image
        rgb = np.asarray(Image.open(io.BytesIO(bytes(jpeg_or_rgb))).convert("RGB")).astype(int)
    else:
        rgb = np.asarray(jpeg_or_rgb).astype(int)
    r0, r1, c0, c1 = REGION
    crop = rgb[r0:r1, c0:c1]
    mx, mn = crop.max(axis=2), crop.min(axis=2)
    sat = (mx - mn) / np.maximum(mx, 1)
    ys, xs = np.nonzero((sat > SAT_MIN) & (mx > VAL_MIN))
    n = int(len(xs))
    if n < NONE_BELOW_PX:
        return {"verdict": "none", "n": n, "cx": None, "cy": None}
    cx, cy = round(float(xs.mean()) + c0), round(float(ys.mean()) + r0)
    good = GOOD_PX[0] <= n <= GOOD_PX[1] and cy >= GOOD_ROW_MIN and GOOD_COL[0] <= cx <= GOOD_COL[1]
    return {"verdict": "good" if good else "unclear", "n": n, "cx": cx, "cy": cy}


CAMERA_TIMEOUT_S = 3.0           # a stalled camera costs the throw's wait at most this per request (2026-11-23: the 8 s default held him standing with the puck until his legs sagged); the first picture after a cold open can take 10 s, so the run opens and checks the camera while he is still at rest


class GripLooker:
    """The camera, warmed up in the background. `factory()` makes the camera (default: the claw camera on the Pi); it needs `.snapshot()` (a picture with `.jpeg`, or None) and may have `.close()`."""

    def __init__(self, factory=None, clock=time.monotonic, sleep=time.sleep, save_dir: str = SAVE_DIR):
        self._factory, self._clock, self._sleep = factory or self._default_factory, clock, sleep
        self._dir = os.path.expanduser(save_dir)
        self._cam = None
        self._error = None
        self._ready = threading.Event()
        self._thread = None

    @staticmethod
    def _default_factory():
        from ..config import settings
        from ..vision.snapshot import CameraSnapshotter
        return CameraSnapshotter(settings.vision_serial_port, labels=settings.vision_labels, sensor_opt=0, ae_bump=settings.vision_ae_bump, exposure_check=True, idle_close_s=0, timeout_s=CAMERA_TIMEOUT_S)

    def warm(self) -> None:
        """Open the camera and take one throwaway picture in the background (it meters the light), so the real one is quick."""
        def work():
            try:
                self._cam = self._factory()
                self._cam.snapshot()
            except Exception as e:  # noqa: BLE001
                self._error = f"{type(e).__name__}: {e}"
            finally:
                self._ready.set()
        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()

    def look(self, name: str, since: float | None = None, after_s: float = 1.5, timeout_s: float = 6.0) -> dict:
        """The grip look: wait for the camera (at most `timeout_s`), for `after_s` seconds after `since` (claw frames are about 1 s old), take the picture, save it and classify it. Returns the classification plus `file`; an error says why."""
        if not self._ready.wait(timeout_s):
            return {"error": "the camera did not warm up in time"}
        if self._error or self._cam is None:
            return {"error": self._error or "no camera"}
        if since is not None:
            wait = after_s - (self._clock() - since)
            if wait > 0:
                self._sleep(wait)
        snap = self._cam.snapshot()
        if snap is None:
            return {"error": "the camera gave no picture"}
        out = classify(snap.jpeg)
        try:
            os.makedirs(self._dir, exist_ok=True)
            path = os.path.join(self._dir, f"{time.strftime('%Y%m%d_%H%M%S')}_{name}.jpg")
            with open(path, "wb") as f:
                f.write(snap.jpeg)
            out["file"] = path
        except OSError as e:
            out["file_error"] = str(e)
        return out

    def close(self) -> None:
        try:
            if self._cam is not None and hasattr(self._cam, "close"):
                self._cam.close()
        except Exception:  # noqa: BLE001
            pass


def take_grip_look(looker: GripLooker | None, name: str, since: float | None = None, say=print) -> dict | None:
    """The grip look for a run, never raising; None when there is no looker. Prints one line."""
    if looker is None:
        return None
    try:
        r = looker.look(name, since=since)
    except Exception as e:  # noqa: BLE001
        r = {"error": f"{type(e).__name__}: {e}"}
    if "error" in r:
        say(f"grip look: no picture ({r['error']}); the throw goes ahead")
    else:
        say(f"grip look: {r['verdict']} (colour block {r['n']} px, centre column {r['cx']} row {r['cy']}); the throw goes ahead" if r["verdict"] != "none"
            else f"grip look: nothing held in view ({r['n']} px); the throw goes ahead")
    return r
