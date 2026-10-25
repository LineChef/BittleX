"""Find the green ball in one picture from the claw camera (240 x 240 JPEG), by colour. No model, no network.

The treat ball is a pale lime green (RGB about 146, 213, 140), so what separates it from the wood floor, the walls and G2's own foot is that its green channel stands out from the red and blue ones
(`g - max(r, b)`: 55 to 85 on the ball, 19 or less on everything else in the 73 pictures of 2026-10-25). The green pixels are joined into blobs and the biggest round one is the ball. Distance
and direction come from the blob: the ball is 3 in across, and a picture of it at 6 / 12 / 24 / 36 in is 50 / 27 / 16 / 8 px across (area 1950 / 590 / 200 / 50 px).

Known limits (measured on the first picture set, docs/plan-detail/arm-policy-plan.md): a ball lying in direct sun goes pale (0 of 4 found), green things close to the ball's colour (a flat card, a ring) are
found now and then (3 false alarms in 19 pictures without the ball), and a ball under about 8 px across (farther than about 40 in) is not seen. The trained "ball" class is the fix for all three.
Every picture is taken with the camera's exposure balancing on; the thresholds are for those pictures."""
from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np

BALL_IN = 3.0                 # the ball's diameter, inches
DIST_K = 330.0                # distance (in) x ball diameter (px): 300 to 380 across the set; the camera sees the ball 330 / D px across at D inches
FRAME_PX = 240
DOM_MIN, G_MIN = 30, 140      # green channel above the larger of red and blue by this much, and at least this bright
MIN_AREA = 25                 # px (a ball about 6 px across: about 55 in away, though the finder is only tested to 36 in)
ASPECT = (0.65, 1.5)          # blob width / height of a round thing
FILL_MIN = 0.6                # blob pixels / bounding box (a disc is 0.785)
IGNORE_BOTTOM_PX = 24         # the jaws, the foot and the edge of the frame are down here


@dataclass(frozen=True)
class BallReading:
    x: float                  # blob centre, px from the left (0..240)
    y: float
    area: int                 # px
    width: int
    height: int
    diameter_px: float
    distance_in: float        # from the camera, by the ball's size
    bearing_deg: float        # + = the ball is to G2's right, - = left (0 = straight ahead)
    touches_edge: bool        # the blob reaches the frame's edge: the ball is partly out of view, so size and distance are low estimates


def _decode(jpeg: bytes) -> np.ndarray | None:
    try:
        from PIL import Image, ImageFile
        ImageFile.LOAD_TRUNCATED_IMAGES = True       # the camera often drops the last 16 bytes: the bottom rows go grey, nothing else
        return np.asarray(Image.open(io.BytesIO(jpeg)).convert("RGB")).astype(np.int16)
    except Exception:  # noqa: BLE001
        return None


def _shift_or(m: np.ndarray) -> np.ndarray:
    out = m.copy()
    out[1:, :] |= m[:-1, :]; out[:-1, :] |= m[1:, :]; out[:, 1:] |= m[:, :-1]; out[:, :-1] |= m[:, 1:]
    return out


def _shift_and(m: np.ndarray) -> np.ndarray:
    return ~_shift_or(~m)


def _blobs(mask: np.ndarray):
    """4-connected blobs of a boolean mask as (ys, xs) arrays (plain numpy and a stack: the Pi has no scipy)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    ys0, xs0 = np.nonzero(mask)
    for y0, x0 in zip(ys0.tolist(), xs0.tolist()):
        if seen[y0, x0]:
            continue
        stack, ys, xs = [(y0, x0)], [], []
        seen[y0, x0] = True
        while stack:
            y, x = stack.pop()
            ys.append(y); xs.append(x)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        yield np.array(ys), np.array(xs)


def find_ball_array(rgb: np.ndarray) -> BallReading | None:
    dom = rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2])
    mask = (dom >= DOM_MIN) & (rgb[..., 1] >= G_MIN)
    mask[rgb.shape[0] - IGNORE_BOTTOM_PX:, :] = False
    for _ in range(2):                                     # close a 1 px gap or a highlight: grow, then shrink
        mask = _shift_or(mask)
    for _ in range(2):
        mask = _shift_and(mask)
    best: BallReading | None = None
    for ys, xs in _blobs(mask):
        if len(xs) < MIN_AREA:
            continue
        w, h = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        # a round thing is filled between its left and right edge on every row (this also fills the highlight): its area is the span sum
        area = 0
        for row in np.unique(ys):
            cols = xs[ys == row]
            area += int(cols.max() - cols.min() + 1)
        edge = bool(xs.min() == 0 or xs.max() == rgb.shape[1] - 1 or ys.min() == 0)
        if not edge and (not (ASPECT[0] <= w / h <= ASPECT[1]) or area / (w * h) < FILL_MIN):
            continue                                       # a flat card, a stick, a ring: not round
        diam = float(max(w, h)) if edge else 2.0 * math.sqrt(area / math.pi)      # cut off by the frame: the longer side is the better size
        dist = DIST_K / max(diam, 1.0)
        cx = float(xs.mean())
        side_in = (cx - rgb.shape[1] / 2) * BALL_IN / max(diam, 1.0)
        reading = BallReading(cx, float(ys.mean()), int(area), w, h, diam, dist, math.degrees(math.atan2(side_in, dist)), edge)
        if best is None or reading.area > best.area:
            best = reading
    return best


def find_ball(jpeg: bytes) -> BallReading | None:
    """The ball in this JPEG, or None (no picture, or nothing round and green)."""
    rgb = _decode(jpeg)
    return None if rgb is None else find_ball_array(rgb)
