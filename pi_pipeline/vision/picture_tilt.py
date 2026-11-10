"""How far a picture is rolled from level, as an extra signal that the legs are sagging (owner, 2026-11-10: "if a picture is tilted when we expect it to be straight on, servo sagging is usually the reason").

The camera rides on the arm, so legs that have let go tilt every picture. The estimate needs no model: the strongest edge direction in a small grey thumbnail, folded to the nearest of the two axes (a floor line, a wall edge, a door frame
all sit on an axis when the camera is level). It returns the roll in degrees (+ = the picture turned clockwise) and a confidence (the share of edge strength that points that way). A picture with no strong edges says nothing.
Pure Pillow, about 5 ms on the Pi.
"""
from __future__ import annotations

import io
import math

THUMB = 96                     # the thumbnail's side in pixels
BIN_DEG = 3.0
MIN_CONFIDENCE = 0.22          # below this the edges do not agree on a direction: no reading
FLAG_DEG = 12.0                # a confident tilt this big counts as a sag hint (the IMU check uses SAG_TILT_DEG = 12 on the body)


def estimate(jpeg: bytes | None):
    """(tilt_deg, confidence) for a JPEG, or None when it cannot be read or has no dominant edge direction. Never raises."""
    if not jpeg:
        return None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(jpeg)).convert("L").resize((THUMB, THUMB))
        px = list(img.getdata())
    except Exception:  # noqa: BLE001
        return None
    n = THUMB
    nbins = int(90 / BIN_DEG)
    hist = [0.0] * nbins
    total = 0.0
    for y in range(1, n - 1):
        r0, r1, r2 = (y - 1) * n, y * n, (y + 1) * n
        for x in range(1, n - 1):
            gx = (px[r0 + x + 1] + 2 * px[r1 + x + 1] + px[r2 + x + 1]) - (px[r0 + x - 1] + 2 * px[r1 + x - 1] + px[r2 + x - 1])        # Sobel
            gy = (px[r2 + x - 1] + 2 * px[r2 + x] + px[r2 + x + 1]) - (px[r0 + x - 1] + 2 * px[r0 + x] + px[r0 + x + 1])
            w = gx * gx + gy * gy
            if w < 6400:                                 # ignore weak gradients (noise, smooth floor)
                continue
            edge = math.degrees(math.atan2(gy, gx)) + 90.0        # the edge runs across the gradient
            fold = (edge + 45.0) % 90.0 - 45.0                    # nearest axis: -45 .. +45
            hist[min(nbins - 1, int((fold + 45.0) / BIN_DEG))] += w
            total += w
    if total <= 0:
        return None
    # the peak with its two neighbours: a weighted mean of their centres, so a line between two bins is not pulled to a bin centre
    peak = max(range(nbins), key=lambda i: hist[i - 1] + hist[i] + hist[(i + 1) % nbins])
    ids = (peak - 1, peak, (peak + 1) % nbins)
    mass = sum(hist[i] for i in ids)
    conf = mass / (total or 1.0)
    if conf < MIN_CONFIDENCE:
        return None
    centres = [(-45.0 + (peak - 1 + 0.5) * BIN_DEG), (-45.0 + (peak + 0.5) * BIN_DEG), (-45.0 + (peak + 1 + 0.5) * BIN_DEG)]
    mean = sum(c * hist[i] for c, i in zip(centres, ids)) / (mass or 1.0)
    return round(mean, 1), round(min(1.0, conf), 2)


def flagged(reading) -> bool:
    """Whether a reading is a sag hint: confident and rolled FLAG_DEG or more."""
    return reading is not None and abs(reading[0]) >= FLAG_DEG
