"""How heavy an embedder is on THIS machine: model load time, milliseconds per picture, and the process's memory afterwards.

    python -m pi_pipeline.vision.embed_bench [dinov2_small.onnx#cls]      (default: the gallery's own embedder, else histogram)

Run it on the Pi with the voice service STOPPED (the Pi has about 80 MB free while the service runs; a ViT needs more than that). It reads nothing but a few synthetic pictures and changes nothing.
"""
from __future__ import annotations

import resource
import sys
import time


def main(argv=None) -> int:
    key = (argv or sys.argv[1:] or ["histogram"])[0]
    import numpy as np
    from PIL import Image

    from .embedder import make_embedder, spec_for
    t0 = time.monotonic()
    e = make_embedder(spec_for(key))
    load_s = time.monotonic() - t0
    rng = np.random.default_rng(0)
    imgs = [Image.fromarray((rng.random((240, 240, 3)) * 255).astype("uint8")) for _ in range(6)]
    e.embed(imgs[0])                                              # the first call warms up the runtime
    t1 = time.monotonic()
    for im in imgs[1:]:
        e.embed(im)
    per = (time.monotonic() - t1) / (len(imgs) - 1)
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    print(f"{key}: load {load_s:.1f} s, {per * 1000:.0f} ms a picture, peak memory {rss_mb:.0f} MB, vector {getattr(e, 'dim', '?')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
