"""The localizer: which parts of a picture are worth embedding (plan Phase 4).

v0 (here): no object detector. The whole picture plus an overlapping tile grid: every view is embedded and the gallery's own duplicate handling collapses repeats. A named object that fills part of
the frame matches through the tile that contains it. v1, only if v0 turns out too coarse on G2's real pictures, would add a foreground cut-out from the floor-level view.
"""
from __future__ import annotations

from dataclasses import dataclass

from .embedder import to_image


@dataclass(frozen=True)
class View:
    box: tuple[float, float, float, float]      # x0, y0, x1, y1 as fractions of the picture (0..1)
    whole: bool                                 # the whole picture rather than a tile


def grid_boxes(grid: int = 3, overlap: float = 0.5) -> list[tuple[float, float, float, float]]:
    """`grid` x `grid` tiles whose size is chosen so neighbours overlap by `overlap` of a tile (0 = touching, 0.5 = half shared)."""
    if grid <= 1:
        return []
    tile = 1.0 / (grid - (grid - 1) * overlap)
    step = tile * (1.0 - overlap)
    return [(c * step, r * step, c * step + tile, r * step + tile) for r in range(grid) for c in range(grid)]


class GridLocalizer:
    def __init__(self, grid: int = 3, overlap: float = 0.5):
        self.boxes = grid_boxes(grid, overlap)

    def views(self, img) -> list[tuple[View, object]]:
        """[(View, PIL image)]: the whole picture first, then each tile."""
        im = to_image(img)
        w, h = im.size
        out = [(View((0.0, 0.0, 1.0, 1.0), True), im)]
        for (x0, y0, x1, y1) in self.boxes:
            out.append((View((x0, y0, x1, y1), False), im.crop((int(x0 * w), int(y0 * h), max(int(x0 * w) + 1, int(x1 * w)), max(int(y0 * h) + 1, int(y1 * h))))))
        return out
