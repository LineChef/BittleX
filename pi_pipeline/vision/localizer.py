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


# ---- v1: a foreground cut-out from the floor-level view (plan Phase 4; user, 2026-10-09: "interesting" = a clear object that is not a person and not in the library)

@dataclass(frozen=True)
class Candidate:
    box: tuple[float, float, float, float]     # x0, y0, x1, y1 as fractions of the picture
    score: float                               # 0..1: how object-like (size, compactness, contrast with the floor)
    area: float                                # fraction of the picture the cut-out covers


class ForegroundLocalizer:
    """Finds object-like blobs by what differs from the floor in front of G2.

    G2's camera is at floor level, so the bottom strip of every picture is the floor right ahead of him. That strip gives a colour model of the floor (median and spread of
    each block's colour); blocks that differ from it clearly, or that carry a lot more edge than the floor does, are foreground. Connected foreground blocks that are big
    enough, not frame-wide (a wall or a sofa front is background, not an object), reasonably compact and standing on the floor become candidates. No ML, no downloads; it is a
    first filter whose false alarms (rug patterns, shadows, cables) the embedding match and the rate limits absorb. Pure numpy on a block grid."""

    def __init__(self, grid: int = 24, floor_rows: int = 3, min_area: float = 0.025, max_area: float = 0.5, max_width: float = 0.9, min_fill: float = 0.45, contrast: float = 3.0,
                 min_score: float = 0.25):
        self.grid, self.floor_rows = grid, floor_rows
        self.min_area, self.max_area, self.max_width, self.min_fill = min_area, max_area, max_width, min_fill
        self.contrast, self.min_score = contrast, min_score

    def _blocks(self, img):
        import numpy as np
        im = to_image(img).convert("RGB").resize((self.grid * 8, self.grid * 8))
        a = np.asarray(im, dtype=float)                                       # (H, W, 3)
        g = self.grid
        col = a.reshape(g, 8, g, 8, 3).mean(axis=(1, 3))                       # (g, g, 3) mean colour per block
        lum = a.mean(axis=2)
        gy = np.abs(np.diff(lum, axis=0, prepend=lum[:1])).reshape(g, 8, g, 8).mean(axis=(1, 3))
        gx = np.abs(np.diff(lum, axis=1, prepend=lum[:, :1])).reshape(g, 8, g, 8).mean(axis=(1, 3))
        return col, gx + gy

    def foreground_mask(self, img):
        """(g x g bool mask of blocks that differ from the floor strip, the floor-strip colour model ok flag)."""
        import numpy as np
        col, edge = self._blocks(img)
        g = self.grid
        strip = col[g - self.floor_rows:, g // 5: g - g // 5].reshape(-1, 3)         # the floor right ahead of him, centre of the frame
        med = np.median(strip, axis=0)
        mad = np.median(np.abs(strip - med), axis=0) * 1.4826
        scale = np.maximum(mad, 6.0)                                                   # never trust a floor that looks perfectly flat
        dist = np.sqrt((((col - med) / scale) ** 2).sum(axis=2) / 3.0)
        e_strip = edge[g - self.floor_rows:, g // 5: g - g // 5]
        e_lim = float(np.median(e_strip) + 3.0 * (np.median(np.abs(e_strip - np.median(e_strip))) * 1.4826 + 2.0))
        return (dist > self.contrast) | (edge > e_lim * 1.5)

    def candidates(self, img) -> list[Candidate]:
        import numpy as np
        mask = self.foreground_mask(img)
        g = self.grid
        seen = np.zeros_like(mask, dtype=bool)
        out: list[Candidate] = []
        for r in range(g):
            for c in range(g):
                if not mask[r, c] or seen[r, c]:
                    continue
                stack, cells = [(r, c)], []
                seen[r, c] = True
                while stack:
                    y, x = stack.pop()
                    cells.append((y, x))
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < g and 0 <= xx < g and mask[yy, xx] and not seen[yy, xx]:
                            seen[yy, xx] = True
                            stack.append((yy, xx))
                ys, xs = [p[0] for p in cells], [p[1] for p in cells]
                y0, y1, x0, x1 = min(ys), max(ys) + 1, min(xs), max(xs) + 1
                area = len(cells) / (g * g)
                width, fill = (x1 - x0) / g, len(cells) / ((y1 - y0) * (x1 - x0))
                if not (self.min_area <= area <= self.max_area) or width > self.max_width or fill < self.min_fill:
                    continue
                if y1 < g - self.floor_rows and not mask[y1:, x0:x1].size:               # nothing below it at all: cannot be standing on the floor
                    continue
                score = min(1.0, area / 0.12) * 0.5 + fill * 0.3 + (0.2 if y1 >= g - self.floor_rows - 2 else 0.1)
                if score >= self.min_score:
                    out.append(Candidate((x0 / g, y0 / g, x1 / g, y1 / g), round(float(score), 3), round(area, 4)))
        return sorted(out, key=lambda k: -k.score)

    def views(self, img) -> list[tuple[View, object]]:
        """The same shape as `GridLocalizer.views`: the whole picture first, then one padded crop per candidate."""
        im = to_image(img)
        w, h = im.size
        out = [(View((0.0, 0.0, 1.0, 1.0), True), im)]
        for k in self.candidates(im)[:3]:
            x0, y0, x1, y1 = k.box
            px, py = 0.04, 0.04                                                           # a little context around the cut-out
            bx = (max(0.0, x0 - px), max(0.0, y0 - py), min(1.0, x1 + px), min(1.0, y1 + py))
            out.append((View(bx, False), im.crop((int(bx[0] * w), int(bx[1] * h), max(int(bx[0] * w) + 1, int(bx[2] * w)), max(int(bx[1] * h) + 1, int(bx[3] * h))))))
        return out
