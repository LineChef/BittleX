"""Find the green ball in one picture from the claw camera (240 x 240 JPEG), by colour. No model, no network.

The treat ball is a pale lime green (RGB about 146, 213, 140), so what separates it from the wood floor, the walls and G2's own foot is that its green channel stands out from the red and blue ones
(`g - max(r, b)`: 55 to 85 on the ball, 19 or less on everything else in the 73 pictures of 2026-10-25). The green pixels are joined into blobs and the biggest round one is the ball. Distance
and direction come from the blob: the ball is 3 in across, and a picture of it at 6 / 12 / 24 / 36 in is 50 / 27 / 16 / 8 px across (area 1950 / 590 / 200 / 50 px).

Known limits (measured on the first picture set, docs/plan-detail/arm-policy-plan.md): a ball lying in direct sun goes pale (0 of 4 found), green things close to the ball's colour (a flat card, a ring) are
found now and then (3 false alarms in 19 pictures without the ball), and a ball under about 8 px across (farther than about 40 in) is not seen. The trained "ball" class is the fix for all three.
Every picture is taken with the camera's exposure balancing on; the thresholds are for those pictures."""
from __future__ import annotations

import dataclasses
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
# Close up in lamp light (2026-11-01): the ball filled half the picture right in front of the claw, but dim and washed out (green above red/blue by 9-24, median 17; green 90-131),
# so the thresholds above found nothing and he searched instead of punting; everything else in that picture scored 7 or less. A second, looser pass accepts only a BIG blob
# (a ball closer than about 5 in), where a false alarm would need a large lime-green patch.
CLOSE_DOM_MIN, CLOSE_G_MIN = 12, 60
CLOSE_MIN_AREA = 3000         # px: about 62 px across, the ball about 5 in away
# Dim at a few inches more (2026-11-01, lamp light, the ball about 8 in away: green above red/blue by 13 at the median, green about 112): a third pass for a round blob on the floor
# (its centre below the horizon), any size from about 20 px across. On 355 saved exploration pictures it added 7 real balls and 7 false finds (a green cup, a green lamp shade, 4 others).
DIM_DOM_MIN, DIM_G_MIN, DIM_MIN_AREA = 11, 80, 300
DIM_PALE = (14, 150, 65)      # (owner-approved 2026-11-16, from the pictures where he turned away from a ball right in front of him) a SECOND dim rule, tried after the first: dominance 14, minimum area 150, the blob's centre at least row 65. A pale ball (its brightest green about 139 to 147, dominance 14 to 49) 24 to 30 in away
                              # is only about 230 px and sits right at the horizon (rows 75 to 77), which the first rule rejects on both counts. Over 1237 real pictures it adds 14 detections and loses none (5 of them the missed ball); a dim sighting is confirmed by a second picture
CLOSE_PALE_MIN_AREA, CLOSE_PALE_MIN_Y = 900, 90   # a pale ball 5 to 9 in away is 1000 to 3400 px: the close-up rule wants 3000, so it fell through to nothing; this lowers the area but only for a blob whose centre is in the lower half of the frame (big green things high in the frame are walls and plants), and a sighting is confirmed like a dim one
DIM_MIN_Y = 80                # px from the top: the claw camera's horizon is about here


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
    via: str = "normal"       # which pass found it: "normal", "close" (a big blob right at the claw) or "dim" (the loose pass: it also takes round green things on the floor, so the chase wants a second picture)
    color: tuple | None = None  # the mean (r, g, b) of the blob's pixels, sampled where the ball is big (the chase keeps it from close up; the active look matches the ball by it, 2026-11-16)


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


def _find(rgb: np.ndarray, dom_min: int, g_min: int, min_area: int) -> BallReading | None:
    dom = rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2])
    return _best_blob(rgb, (dom >= dom_min) & (rgb[..., 1] >= g_min), min_area)


def _best_blob(rgb: np.ndarray, mask: np.ndarray, min_area: int) -> BallReading | None:
    """The biggest round blob of `mask` (closed over 1 px gaps), as a reading; the shape tests are the same whatever made the mask."""
    mask = mask.copy()
    mask[rgb.shape[0] - IGNORE_BOTTOM_PX:, :] = False
    for _ in range(2):                                     # close a 1 px gap or a highlight: grow, then shrink
        mask = _shift_or(mask)
    for _ in range(2):
        mask = _shift_and(mask)
    best: BallReading | None = None
    for ys, xs in _blobs(mask):
        if len(xs) < min_area:
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
        color = tuple(int(v) for v in rgb[ys, xs].mean(axis=0))
        reading = BallReading(cx, float(ys.mean()), int(area), w, h, diam, dist, math.degrees(math.atan2(side_in, dist)), edge, "normal", color)
        if best is None or reading.area > best.area:
            best = reading
    return best


COLOR_TOL = 0.04              # how far (in normalized red/green share) a pixel's colour may be from the ball's own colour
COLOR_MIN_SUM = 150           # r + g + b: darker pixels have no reliable colour
COLOR_MIN_DOM = 8             # green above the larger of red and blue: a gray or brown floor is never the ball's colour
COLOR_MIN_AREA = 60           # a colour match is looser than the dominance rules, so it needs a bigger blob
COLOR_MIN_Y = 65              # the centre at least this far down: the floor (walls and plants are above the horizon)


def find_ball_color(jpeg: bytes, ref: tuple) -> BallReading | None:
    """The ball found by ITS OWN colour (2026-11-16: the fixed green thresholds miss a pale ball at a distance): pixels whose red and green share of the light is within COLOR_TOL of `ref`'s, bright
    enough, with green above red and blue, in a round blob of at least COLOR_MIN_AREA centred at row COLOR_MIN_Y or lower. `ref` is the (r, g, b) the chase sampled when the ball was close."""
    rgb = _decode(jpeg)
    if rgb is None or ref is None:
        return None
    s = np.maximum(rgb.sum(axis=2), 1)
    rs, gs = float(ref[0]) / max(sum(ref), 1), float(ref[1]) / max(sum(ref), 1)
    dom = rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2])
    mask = (np.abs(rgb[..., 0] / s - rs) <= COLOR_TOL) & (np.abs(rgb[..., 1] / s - gs) <= COLOR_TOL) & (s >= COLOR_MIN_SUM) & (dom >= COLOR_MIN_DOM)
    r = _best_blob(rgb, mask, COLOR_MIN_AREA)
    if r is None or r.y < COLOR_MIN_Y:
        return None
    return dataclasses.replace(r, via="color")


def diagnose(jpeg: bytes) -> dict | None:
    """Evidence for a picture where the finder found no ball (2026-11-16): the biggest round green blob at ANY size, as numbers only (nothing is saved): its pixel area, centre, size and the distance that size
    would mean. Tells whether a missed ball was too small for the finder's limits or not green enough."""
    rgb = _decode(jpeg)
    if rgb is None:
        return None
    best = None
    for name, dom, g in (("normal", DOM_MIN, G_MIN), ("dim", DIM_DOM_MIN, DIM_G_MIN)):
        r = _find(rgb, dom, g, 4)
        if r is not None and (best is None or r.area > best["area"]):
            best = {"pass": name, "area": r.area, "x": round(r.x), "y": round(r.y), "w": r.width, "h": r.height, "dist_in": round(r.distance_in, 1)}
    return best


def find_ball_array(rgb: np.ndarray) -> BallReading | None:
    """The normal pass, then (nothing found) the close-up pass for a big, dim ball right in front of the camera, then the dim pass for a round green blob on the floor."""
    found = _find(rgb, DOM_MIN, G_MIN, MIN_AREA)
    if found is None:
        found = _find(rgb, CLOSE_DOM_MIN, CLOSE_G_MIN, CLOSE_MIN_AREA)
        if found is not None:
            found = dataclasses.replace(found, via="close")
    if found is None:
        low = _find(rgb, CLOSE_DOM_MIN, CLOSE_G_MIN, CLOSE_PALE_MIN_AREA)
        if low is not None and low.y >= CLOSE_PALE_MIN_Y:
            found = dataclasses.replace(low, via="dim")
    if found is None:
        dim = _find(rgb, DIM_DOM_MIN, DIM_G_MIN, DIM_MIN_AREA)
        if dim is not None and dim.y >= DIM_MIN_Y:
            found = dataclasses.replace(dim, via="dim")
    if found is None:
        pale = _find(rgb, DIM_PALE[0], DIM_G_MIN, DIM_PALE[1])
        if pale is not None and pale.y >= DIM_PALE[2]:
            found = dataclasses.replace(pale, via="dim")
    return found


def find_ball_or_color(jpeg: bytes, color: tuple | None = None) -> BallReading | None:
    """The one look every mode uses (2026-11-17, owner-approved after far balls were missed): the fixed rules first, then the ball's own colour (sampled when it was close) when those find nothing."""
    ball = find_ball(jpeg) if jpeg else None
    if ball is None and jpeg and color is not None:
        ball = find_ball_color(jpeg, color)
    return ball


def find_ball(jpeg: bytes) -> BallReading | None:
    """The ball in this JPEG, or None (no picture, or nothing round and green)."""
    rgb = _decode(jpeg)
    return None if rgb is None else find_ball_array(rgb)
