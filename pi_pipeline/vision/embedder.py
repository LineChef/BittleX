"""Image embedders for the object recognition library (docs/vision/exploration-object-learning-plan.md, Phase 3).

An embedder turns one picture (a PIL image, JPEG bytes or a numpy array) into a unit-length vector; the `ObjectGallery` compares those vectors by cosine similarity. Two come with the code:

  HistogramEmbedder   colour, brightness, coarse layout and edge directions, numpy and PIL only. No model file, nothing to download: the baseline and the fallback, and a yardstick the
                      learned models have to beat on the same pictures (`tools/eval_embedder.py`).
  OnnxEmbedder        any image model exported to ONNX (a MobileNet-class classifier body, a small DINO or CLIP image encoder): resize, normalise, run, pool, normalise. Which model is a Phase 3 decision
                      made on G2's own pictures; the model file is fetched only with the user's yes (CLAUDE.md: nothing is downloaded without asking) and lives outside the repo.

`make_embedder("histogram")` / `make_embedder("onnx:/path/to/model.onnx")` pick one. A change of embedder starts the gallery over (the vectors live in different spaces); the pictures are kept, so
the gallery can be rebuilt from them.
"""
from __future__ import annotations

import io
from typing import Protocol

import numpy as np


def to_image(img):
    """PIL image from a PIL image, JPEG/PNG bytes or an HxWx3 uint8 array."""
    from PIL import Image
    if isinstance(img, Image.Image):
        return img.convert("RGB")
    if isinstance(img, (bytes, bytearray)):
        return Image.open(io.BytesIO(bytes(img))).convert("RGB")
    return Image.fromarray(np.asarray(img, dtype=np.uint8)).convert("RGB")


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, img) -> np.ndarray: ...


class HistogramEmbedder:
    """Colour + layout + edge fingerprint. Each block is normalised on its own so no single cue dominates; the blocks are concatenated and normalised again."""

    name = "histogram"

    def __init__(self, size: int = 96):
        self.size = size
        self.dim = 12 * 3 + 6 + 9 * 3 + 2 * 2 * 8

    def embed(self, img) -> np.ndarray:
        from PIL import Image
        im = to_image(img).resize((self.size, self.size), Image.BILINEAR)
        rgb = np.asarray(im, dtype=np.float32) / 255.0
        hsv = np.asarray(im.convert("HSV"), dtype=np.float32) / 255.0
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        # 1. hue x saturation histogram, weighted by saturation x value so a grey / dark pixel adds little to the hue bins
        hb = np.minimum((h * 12).astype(int), 11)
        sb = np.minimum((s * 3).astype(int), 2)
        hist = np.zeros((12, 3), dtype=np.float32)
        np.add.at(hist, (hb, sb), (s * v + 0.05))
        # 2. brightness histogram
        vh, _ = np.histogram(v, bins=6, range=(0, 1))
        # 3. coarse layout: the mean colour of a 3 x 3 grid
        g = self.size // 3
        grid = np.array([rgb[r * g:(r + 1) * g, c * g:(c + 1) * g].mean(axis=(0, 1)) for r in range(3) for c in range(3)], dtype=np.float32).ravel()
        grid = grid - grid.mean()
        # 4. edge directions in 2 x 2 cells, weighted by edge strength
        gray = rgb.mean(axis=2)
        gy, gx = np.gradient(gray)
        mag = np.hypot(gx, gy)
        ang = (np.arctan2(gy, gx) % np.pi) / np.pi
        ab = np.minimum((ang * 8).astype(int), 7)
        half = self.size // 2
        eh = []
        for r in range(2):
            for c in range(2):
                m, a = mag[r * half:(r + 1) * half, c * half:(c + 1) * half], ab[r * half:(r + 1) * half, c * half:(c + 1) * half]
                eh.append(np.bincount(a.ravel(), weights=m.ravel(), minlength=8))
        parts = [_unit(hist.ravel()), _unit(vh.astype(np.float32)), _unit(grid), _unit(np.concatenate(eh).astype(np.float32))]
        return _unit(np.concatenate(parts)).astype(np.float32)


class OnnxEmbedder:
    """An ONNX image model as an embedder. The output is pooled to one vector (a 4-D feature map is averaged over its spatial axes; a 3-D token output over tokens) and normalised."""

    def __init__(self, path: str, size: int = 224, mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225), providers=("CPUExecutionProvider",)):
        import onnxruntime as ort
        self.path, self.size = str(path), int(size)
        self.name = "onnx:" + self.path.rsplit("/", 1)[-1]
        self._mean = np.array(mean, dtype=np.float32).reshape(1, 1, 3)
        self._std = np.array(std, dtype=np.float32).reshape(1, 1, 3)
        self._sess = ort.InferenceSession(self.path, providers=list(providers))
        self._in = self._sess.get_inputs()[0].name
        self.dim = 0

    def embed(self, img) -> np.ndarray:
        from PIL import Image
        im = to_image(img).resize((self.size, self.size), Image.BICUBIC)
        x = (np.asarray(im, dtype=np.float32) / 255.0 - self._mean) / self._std
        x = np.transpose(x, (2, 0, 1))[None].astype(np.float32)
        out = self._sess.run(None, {self._in: x})[0]
        out = np.asarray(out, dtype=np.float32)
        if out.ndim == 4:
            out = out.mean(axis=(2, 3))
        elif out.ndim == 3:
            out = out.mean(axis=1)
        v = _unit(out.reshape(-1))
        self.dim = int(v.size)
        return v


def make_embedder(spec: str = "histogram"):
    spec = (spec or "histogram").strip()
    if spec == "histogram":
        return HistogramEmbedder()
    if spec.startswith("onnx:"):
        return OnnxEmbedder(spec[5:])
    raise ValueError(f"unknown embedder {spec!r}: use 'histogram' or 'onnx:/path/model.onnx'")
