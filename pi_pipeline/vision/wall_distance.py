"""How far away is the wall ahead, from one floor-level picture (user, 2026-10-09: "teach him what a wall looks like and roughly how close he is, so he can turn away").

Geometry, not a learned model. G2's camera sits at a fixed height and tilt near the floor, so the row of the picture where the floor ends and an obstacle begins (the obstacle's base)
maps to a distance on the floor: the lower in the picture, the closer. The floor is modelled from the strip at the bottom of the picture (`ForegroundLocalizer.foreground_mask`);
for each of five column groups across the picture the obstacle base is the lowest row, scanning upward, where the group stops looking like floor. A calibration (a few boxes at
tape-measured distances, `python -m pi_pipeline.vision.wall_distance calibrate`) turns base rows into centimetres. The result per column group says which side is more open, so a
turn-away direction falls out. DRY RUN ONLY: nothing here moves G2; the exploration session logs what he WOULD do (`~/.local/share/g2/wall_dryrun.jsonl`) until the user says to wire it in.
Limits: a wall the colour of the floor, a glossy floor, a very dim room, and a wall so close that it fills the floor strip itself (reported as `blocked`)."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .localizer import ForegroundLocalizer

GROUPS = 5
CAL_PATH = os.path.expanduser(os.environ.get("G2_WALL_CAL", "~/.local/share/g2/wall_calibration.json"))
LOG_PATH = os.path.expanduser(os.environ.get("G2_WALL_LOG", "~/.local/share/g2/wall_dryrun.jsonl"))


def base_rows(img, localizer: ForegroundLocalizer | None = None, *, groups: int = GROUPS, need_rows: int = 2, group_frac: float = 0.6):
    """Per column group, the picture row (a fraction 0..1, the lower edge of the obstacle's base) where the floor ends, or None when the floor runs to the top of the picture.
    Returns (rows, floor_visible): `floor_visible` False when almost the whole picture differs from the floor strip (the obstacle is right in front of him)."""
    import numpy as np
    loc = localizer or ForegroundLocalizer()
    mask = loc.foreground_mask(img)
    g = loc.grid
    rows = []
    for i in range(groups):
        c0, c1 = int(i * g / groups), max(int((i + 1) * g / groups), int(i * g / groups) + 1)
        fg = mask[:, c0:c1].mean(axis=1) >= group_frac                      # per row: is most of this column group not floor
        found = None
        run = 0
        for r in range(g - 1, -1, -1):                                       # from the bottom of the picture upward
            run = run + 1 if fg[r] else 0
            if run >= need_rows:
                found = r + need_rows                                        # the lower edge of the lowest obstacle row of that run
                break
        rows.append(None if found is None else min(1.0, found / g))
    covered = float(mask.mean())
    return rows, covered < 0.9


@dataclass
class Calibration:
    points: list = field(default_factory=list)           # [(row_fraction, distance_cm)] sorted by row (a lower row = a closer obstacle = a smaller distance)

    def distance_cm(self, row: float) -> float:
        pts = sorted(self.points)
        if not pts:
            raise ValueError("no calibration points")
        if row <= pts[0][0]:
            return pts[0][1] * (1.0 if row == pts[0][0] else max(0.5, 1.0 + (pts[0][0] - row) * 6.0))      # above the farthest calibrated point: at least that far
        if row >= pts[-1][0]:
            return pts[-1][1]                                                                              # at or below the closest: no closer than that can be told
        for (r0, d0), (r1, d1) in zip(pts, pts[1:]):
            if r0 <= row <= r1:
                return d0 + (d1 - d0) * (row - r0) / (r1 - r0)
        return pts[-1][1]

    def save(self, path: str = CAL_PATH) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"points": self.points, "time": time.strftime("%Y-%m-%d %H:%M:%S")}))

    @classmethod
    def load(cls, path: str = CAL_PATH) -> "Calibration | None":
        try:
            d = json.loads(Path(path).read_text())
            return cls([tuple(p) for p in d["points"]])
        except (OSError, ValueError, KeyError):
            return None


@dataclass
class WallEstimate:
    nearest_cm: float | None            # the closest obstacle base across the picture (None = open floor to the top of the picture)
    group_cm: list                      # per column group (left to right), None where the floor is open
    blocked: bool                       # the obstacle fills the floor strip itself: closer than the calibration can tell
    turn: str | None                    # "left" / "right": toward the more open side; None when nothing is close
    reason: str


def estimate(img, calibration: Calibration, *, near_cm: float = 30.0, localizer: ForegroundLocalizer | None = None) -> WallEstimate:
    rows, floor_visible = base_rows(img, localizer)
    if not floor_visible:
        return WallEstimate(0.0, [0.0] * GROUPS, True, None, "blocked: almost the whole picture differs from the floor")
    cm = [None if r is None else round(calibration.distance_cm(r), 1) for r in rows]
    seen = [c for c in cm if c is not None]
    nearest = min(seen) if seen else None
    if nearest is None or nearest > near_cm:
        return WallEstimate(nearest, cm, False, None, "clear" if nearest is None else f"nearest {nearest:.0f} cm: not close")
    half = GROUPS // 2
    left = [c if c is not None else 1e9 for c in cm[:half]]                    # the two outer groups on each side; the centre group is straight ahead and belongs to neither
    right = [c if c is not None else 1e9 for c in cm[half + 1:]]
    if min(left) != min(right):
        side = "left" if min(left) > min(right) else "right"                   # turn toward the side whose nearest obstacle is farther away
    else:
        side = "left" if sum(left) >= sum(right) else "right"                  # a tie: the side with more room overall
    return WallEstimate(nearest, cm, False, side, f"nearest {nearest:.0f} cm: would turn {side}")


def log_dry_run(est: WallEstimate, path: str = LOG_PATH, *, extra: dict | None = None) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "nearest_cm": est.nearest_cm, "group_cm": est.group_cm, "blocked": est.blocked, "turn": est.turn,
                                "reason": est.reason, **(extra or {})}) + "\n")
    except OSError:
        pass


def calibrate(distances_cm=(20, 30, 40, 60, 100), source=None) -> Calibration:
    """Interactive, on the Pi with the camera: for each distance, place a flat obstacle (a box or a book on its edge, wider than the picture's centre) squarely in front of him,
    press Enter, and the base row is recorded (the median of a few snapshots)."""
    import statistics
    from .embedder import to_image
    if source is None:
        from ..app.__main__ import _make_vision_source
        source = _make_vision_source()
    pts = []
    for d in distances_cm:
        input(f"Place the obstacle's base {d} cm in front of G2's camera, squarely, then press Enter ")
        got = []
        for _ in range(4):
            snap = source.snapshot(settle=0) if hasattr(source, "snapshot") else None
            if snap is None:
                continue
            rows, visible = base_rows(to_image(snap.jpeg))
            centre = [r for r in rows[1:4] if r is not None]
            if centre:
                got.append(statistics.median(centre))
        if got:
            pts.append((round(statistics.median(got), 4), float(d)))
            print(f"  {d} cm -> base row {pts[-1][0]:.3f} of the picture height ({len(got)} readings)")
        else:
            print(f"  {d} cm -> no obstacle base found in the picture; skipped")
    cal = Calibration(sorted(pts))
    if len(cal.points) >= 2:
        cal.save()
        print(f"saved {len(cal.points)} points to {CAL_PATH}")
    return cal


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["calibrate"]:
        calibrate()
    else:
        print("usage: python -m pi_pipeline.vision.wall_distance calibrate")
