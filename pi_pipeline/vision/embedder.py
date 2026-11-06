"""Image embedders for the object recognition library (docs/planned/exploration-object-learning-plan.md, Phase 3).

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

    def __init__(self, path: str, size: int = 224, mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225), providers=("CPUExecutionProvider",), pool: str = "auto"):
        import onnxruntime as ort
        self.path, self.size, self.pool = str(path), int(size), pool
        self.name = "onnx:" + self.path.rsplit("/", 1)[-1]
        self.key = self.path.rsplit("/", 1)[-1] + (f"#{pool}" if pool != "auto" else "")          # the same on every machine: the gallery file records it
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
        out = np.asarray(self._sess.run(None, {self._in: x})[0], dtype=np.float32)
        v = pool_output(out, self.pool)
        self.dim = int(v.size)
        return v


class LazyOnnxEmbedder:
    """An ONNX embedder that holds its model in memory only while it is being used (user, 2026-11-06: the Pi has about 75 MB free beside the voice service, and the model needs about 100 MB).
    The first `embed` loads the model; `idle_s` seconds after the last one it is released again (the next call loads it, about a second on the Pi). Same interface as OnnxEmbedder."""

    def __init__(self, path: str, *, pool: str = "auto", idle_s: float = 90.0, factory=None, clock_timer=None):
        import threading
        self._path, self._pool, self.idle_s = str(path), pool, float(idle_s)
        self._factory = factory or (lambda: OnnxEmbedder(self._path, pool=self._pool))
        self._timer_cls = clock_timer or threading.Timer
        self._lock = threading.RLock()
        self._inner = None
        self._timer = None
        self.loads = 0
        self.name = "onnx:" + self._path.rsplit("/", 1)[-1]
        self.key = self._path.rsplit("/", 1)[-1] + (f"#{pool}" if pool != "auto" else "")
        self.dim = 0

    @property
    def loaded(self) -> bool:
        return self._inner is not None

    def embed(self, img):
        with self._lock:
            if self._inner is None:
                self._inner = self._factory()
                self.loads += 1
            v = self._inner.embed(img)
            self.dim = int(getattr(v, "size", 0) or self.dim)
            if self.idle_s > 0:
                if self._timer is not None:
                    self._timer.cancel()
                self._timer = self._timer_cls(self.idle_s, self.unload)
                self._timer.daemon = True
                self._timer.start()
            return v

    def unload(self) -> None:
        with self._lock:
            self._inner = None
            self._timer = None
            import gc
            gc.collect()


def pool_output(out: np.ndarray, pool: str = "auto") -> np.ndarray:
    """One unit vector from a model output: a 2-D (1, D) output is used as is; a 4-D feature map is averaged over its spatial axes; a 3-D token output (1, tokens, D) with a leading class token
    (a ViT / DINO encoder) is pooled as 'cls' (token 0), 'mean' (the other tokens averaged) or 'cls+mean' (both, each normalised, joined; the default for 3-D)."""
    out = np.asarray(out, dtype=np.float32)
    if out.ndim == 4:
        return _unit(out.mean(axis=(2, 3)).reshape(-1))
    if out.ndim == 3:
        mode = "cls+mean" if pool == "auto" else pool
        cls, mean = out[0, 0], out[0, 1:].mean(axis=0)
        if mode == "cls":
            return _unit(cls)
        if mode == "mean":
            return _unit(mean)
        if mode == "cls+mean":
            return _unit(np.concatenate([_unit(cls), _unit(mean)]))
        raise ValueError(f"unknown pool {pool!r}")
    return _unit(out.reshape(-1))


def models_dir() -> str:
    """Where the embedder model files live: G2_MODELS_DIR, else ~/g2_data/models on the Mac (outside the repo, docs/vision/downloaded-models.md), else ~/.local/share/g2/models on the Pi."""
    import os
    d = os.environ.get("G2_MODELS_DIR")
    if d:
        return os.path.expanduser(d)
    mac = os.path.expanduser("~/g2_data/models")
    return mac if os.path.isdir(mac) else os.path.expanduser("~/.local/share/g2/models")


def spec_for(key: str) -> str:
    """The embedder spec for a gallery's recorded key: 'histogram', or 'dinov2_small.onnx#cls' -> 'onnx:<models dir>/dinov2_small.onnx#cls'."""
    key = (key or "histogram").strip()
    return "histogram" if key == "histogram" else "onnx:" + models_dir() + "/" + key


def embedder_for(gallery, default: str = "histogram"):
    """The embedder a gallery's fingerprints belong to. A gallery that records one uses it; one that has entries and records none predates the record and is histogram; an empty one takes
    `default` (G2_EMBEDDER). Fingerprints from different models cannot be compared, so the gallery, not the environment, decides once it holds any."""
    key = getattr(gallery, "embedder", None)
    if key:
        return make_embedder(spec_for(key))
    e = make_embedder("histogram" if getattr(gallery, "entries", None) else default)
    try:
        gallery.embedder = e.key                                   # recorded from now on, so a later change of the environment cannot mix two models in one file
    except AttributeError:
        pass
    return e


def make_embedder(spec: str = "histogram"):
    spec = (spec or "histogram").strip()
    if spec == "histogram":
        e = HistogramEmbedder()
        e.key = "histogram"
        return e
    if spec.startswith("onnx:"):
        path, _, pool = spec[5:].partition("#")            # 'onnx:/path/model.onnx#cls' picks the token pooling of a ViT / DINO encoder
        import os
        import sys
        idle = float(os.environ.get("G2_EMBEDDER_IDLE_S", "90" if sys.platform == "linux" else "0"))       # >0: hold the model only while it is used (the Pi, Linux: 90 s); 0 = keep it loaded (the Mac tools)
        if idle > 0:
            return LazyOnnxEmbedder(path, pool=pool or "auto", idle_s=idle)
        return OnnxEmbedder(path, pool=pool or "auto")
    raise ValueError(f"unknown embedder {spec!r}: use 'histogram' or 'onnx:/path/model.onnx'")
