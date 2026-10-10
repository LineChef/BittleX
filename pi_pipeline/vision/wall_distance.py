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


def base_rows(img, localizer: ForegroundLocalizer | None = None, *, groups: int = GROUPS, need_rows: int = 2, group_frac: float = 0.6, min_rise: int = 6):
    """Per column group, the picture row (a fraction 0..1, the lower edge of the obstacle's base) where the floor ends, or None when the floor runs to the top of the picture.
    A wall RISES: the obstacle must be at least `min_rise` consecutive grid rows tall (a quarter of the picture), so a bright sheen, a reflection or a floor-grain patch (2 to 4 rows, with floor above it)
    is skipped and the search goes on upward to the wall behind it (user, 2026-10-10: a wall 10 ft away read as 9 in because of a floor sheen). Returns (rows, floor_visible):
    `floor_visible` False when almost the whole picture differs from the floor strip (the obstacle is right in front of him)."""
    import numpy as np
    loc = localizer or ForegroundLocalizer()
    mask = loc.foreground_mask(img)
    g = loc.grid
    rows = []
    for i in range(groups):
        c0, c1 = int(i * g / groups), max(int((i + 1) * g / groups), int(i * g / groups) + 1)
        fg = mask[:, c0:c1].mean(axis=1) >= group_frac                      # per row: is most of this column group not floor
        found = None
        r = g - 1
        while r >= 0:                                                        # from the bottom of the picture upward, one run of obstacle rows at a time
            if not fg[r]:
                r -= 1
                continue
            t = r
            while t - 1 >= 0 and fg[t - 1]:
                t -= 1                                                       # [t..r] is a run of consecutive obstacle rows; its lower edge is the candidate base
            if r - t + 1 < need_rows:                                        # a single stray row is not an obstacle
                r = t - 1
                continue
            if r - t + 1 >= min_rise:                                        # tall enough to be a wall: it rises at least a quarter of the picture without a gap
                found = r + 1                                                # the lower edge of the lowest wall-height obstacle
                break
            r = t - 1                                                        # too short (a sheen, a floor-grain patch): keep looking above it
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


NEAR_IN = 12.0                    # "near" for the log: the nearest wall base at or inside 12 in (30 cm is the turn threshold of `estimate`)
PICS_DIR = os.path.expanduser(os.environ.get("G2_WALL_PICS", "~/.local/share/g2/wall_pics"))


def state_of(est: "WallEstimate") -> str:
    """One word for the log and the statistics: blocked / near / far / clear (open floor to the top of the picture)."""
    if est.blocked:
        return "blocked"
    if est.nearest_cm is None:
        return "clear"
    return "near" if est.nearest_cm / IN_TO_CM <= NEAR_IN else "far"


def log_dry_run(est: WallEstimate, path: str = LOG_PATH, *, extra: dict | None = None) -> None:
    """One JSON line per look: centimetres (as measured) and the same in inches, the state, the turn it would make and whatever `extra` adds (mode, picture name, ...)."""
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        inch = lambda c: None if c is None else round(c / IN_TO_CM, 1)  # noqa: E731
        row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), "state": state_of(est), "nearest_in": inch(est.nearest_cm), "group_in": [inch(c) for c in est.group_cm],
               "nearest_cm": est.nearest_cm, "group_cm": est.group_cm, "blocked": est.blocked, "turn": est.turn, "reason": est.reason, **(extra or {})}
        with open(path, "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass


@dataclass
class WallReading:
    """The latest wall look as the behaviour driver sees it (user, 2026-10-10: let the wall estimate steer him): `t` is `time.monotonic()` of the look, `nearest_in` the closest wall
    base in inches (None = clear), `state` clear / far / near / blocked, `turn` the side with more room ("left" / "right"), `confirmed` true when this and the previous look were both
    near or blocked."""
    t: float
    state: str
    nearest_in: float | None
    turn: str | None
    confirmed: bool


class WallLog:
    """What the wall estimator logs while G2 explores (user, 2026-10-10: log when walls are seen and at what distance, for debugging). Every look is one line in `wall_dryrun.jsonl`;
    a picture is kept for every near / blocked look, and one clear look every `clear_every_s` for comparison, in a ring of `ring` files (`wall_pics`); each line that has a picture
    names it. `context()` returns extra fields (the exploration mode, whether he is walking). Never raises, never moves G2."""

    def __init__(self, calibration: "Calibration | None", *, path: str = LOG_PATH, pics_dir: str = PICS_DIR, ring: int = 20, clear_every_s: float = 300.0,
                 context=lambda: {}, clock=time.time):
        self.cal, self.path, self.pics_dir, self.ring, self.clear_every_s = calibration, path, pics_dir, ring, clear_every_s
        self.context, self._clock = context, clock
        self._last_clear = float("-inf")
        self._prev_state = None
        self.last: WallReading | None = None                          # the newest look, read by the behaviour driver

    def look(self, jpeg: bytes, img) -> WallEstimate:
        if self.cal is None:                                              # not calibrated: keep the raw base rows so a calibration can be checked against them
            rows, visible = base_rows(img)
            est = WallEstimate(None, [None if r is None else round(r, 3) for r in rows], not visible, None, "uncalibrated: base rows only")
        else:
            est = estimate(img, self.cal)
        try:
            extra = dict(self.context() or {})
        except Exception:  # noqa: BLE001
            extra = {}
        st = state_of(est)
        now = self._clock()
        if st in ("near", "blocked") or (st in ("clear", "far") and now - self._last_clear >= self.clear_every_s):
            if st in ("clear", "far"):
                self._last_clear = now
            pic = self._keep(jpeg, st, now)
            if pic:
                extra["pic"] = pic
        near_now = st in ("near", "blocked")
        extra["near_confirmed"] = bool(near_now and self._prev_state in ("near", "blocked"))     # two looks in a row agree: a one-off reading is not yet a wall
        self._prev_state = st
        if self.cal is not None:                                      # an uncalibrated look is never acted on
            self.last = WallReading(time.monotonic(), st, None if est.nearest_cm is None else round(est.nearest_cm / IN_TO_CM, 1), est.turn, extra["near_confirmed"])
        log_dry_run(est, self.path, extra=extra | {"calibrated": self.cal is not None})
        return est

    def _keep(self, jpeg: bytes, state: str, now: float) -> str | None:
        try:
            d = Path(self.pics_dir)
            d.mkdir(parents=True, exist_ok=True)
            name = time.strftime("wall_%Y%m%d_%H%M%S", time.localtime(now)) + f"_{state}.jpg"
            (d / name).write_bytes(jpeg)
            for old in sorted(d.glob("wall_*.jpg"))[:-self.ring]:           # a ring: only the newest `ring` pictures stay
                old.unlink(missing_ok=True)
            return name
        except OSError:
            return None


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


IN_TO_CM = 2.54


def calibrate_from_pictures(pictures_dir: str, labels: dict | None = None, *, shots: list | None = None, save: bool = True, path: str = CAL_PATH) -> tuple[Calibration, list]:
    """Build the calibration from labelled wall pictures instead of moving a box (user, 2026-10-10: wall recognition pictures first). `pictures_dir` holds `shot_NNN.jpg` and a
    `labels.json` mapping each shot name to {"label": "wall_straight", "distance_in": 16, ...}; only `wall_straight` shots with a distance are used (and only `shots`, if given). Each
    shot gives the median of the three middle column groups' base rows (as `calibrate` does); shots at the same distance are averaged; the distance is converted to centimetres here
    and nowhere in what the user sees. Returns (calibration, the list of (distance_in, row, shots used) rows)."""
    import statistics
    from .embedder import to_image
    labels = labels if labels is not None else json.loads((Path(pictures_dir) / "labels.json").read_text())
    per_distance: dict[float, list] = {}
    used: dict[float, list] = {}
    for name, info in sorted(labels.items()):
        if shots is not None and name not in shots:
            continue
        if info.get("label") != "wall_straight" or not info.get("distance_in"):
            continue
        jpg = Path(pictures_dir) / f"{name}.jpg"
        if not jpg.exists():
            continue
        rows, _ = base_rows(to_image(jpg.read_bytes()))
        centre = [r for r in rows[1:4] if r is not None]
        if not centre:
            continue
        d = float(info["distance_in"])
        per_distance.setdefault(d, []).append(statistics.median(centre))
        used.setdefault(d, []).append(name)
    pts = [(round(sum(v) / len(v), 4), round(d * IN_TO_CM, 1)) for d, v in sorted(per_distance.items())]
    cal = Calibration(sorted(pts))
    table = [(d, round(sum(v) / len(v), 4), used[d]) for d, v in sorted(per_distance.items())]
    if save and len(cal.points) >= 2:
        cal.save(path)
    return cal, table


def check_against_pictures(cal: Calibration, pictures_dir: str, labels: dict | None = None, *, skip: list | None = None) -> list:
    """For every wall_straight picture with a distance (except `skip`): (shot, distance_in, estimated_in) using the same centre-group rule as the calibration."""
    import statistics
    from .embedder import to_image
    labels = labels if labels is not None else json.loads((Path(pictures_dir) / "labels.json").read_text())
    out = []
    for name, info in sorted(labels.items()):
        if name in (skip or []) or info.get("label") != "wall_straight" or not info.get("distance_in"):
            continue
        jpg = Path(pictures_dir) / f"{name}.jpg"
        if not jpg.exists():
            continue
        rows, _ = base_rows(to_image(jpg.read_bytes()))
        centre = [r for r in rows[1:4] if r is not None]
        if centre:
            out.append((name, float(info["distance_in"]), round(cal.distance_cm(statistics.median(centre)) / IN_TO_CM, 1)))
    return out


if __name__ == "__main__":
    import sys
    if sys.argv[1:2] == ["calibrate"]:
        calibrate()
    elif sys.argv[1:2] == ["pictures"] and len(sys.argv) > 2:
        c, table = calibrate_from_pictures(sys.argv[2], shots=sys.argv[3:] or None)
        for d, row, names in table:
            print(f"{d:g} in -> row {row:.3f}  ({', '.join(names)})")
        print(f"saved {len(c.points)} points to {CAL_PATH}" if len(c.points) >= 2 else "need at least 2 distances: nothing saved")
    else:
        print("usage: python -m pi_pipeline.vision.wall_distance calibrate | pictures DIR [shot_007 shot_008 ...]")
