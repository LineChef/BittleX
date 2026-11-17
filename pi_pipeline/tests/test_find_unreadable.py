"""tools/find_unreadable.py: only undecodable pictures, never people or calibration pictures, a cut-short picture is fine."""
import importlib.util
import io
import os

import numpy as np
from PIL import Image

spec = importlib.util.spec_from_file_location("find_unreadable", os.path.join(os.path.dirname(__file__), "..", "..", "tools", "find_unreadable.py"))
fu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fu)


def jpeg(seed=1):
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 255, (240, 240), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(np.stack([a, a, a], axis=2)).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def put(root, rel, data):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    p.with_suffix(".json").write_text("{}")


def test_only_undecodable_pictures_are_listed_and_never_people_or_calibration(tmp_path, monkeypatch):
    root = tmp_path / "g2_pictures"
    good = jpeg()
    put(root, "explore/named/greenball/ok.jpg", good)
    put(root, "explore/named/greenball/cut_short.jpg", good[:-12])             # cut short by a few bytes: still decodes
    put(root, "explore/named/greenball/empty.jpg", b"")
    put(root, "watch/watch_1/frag.jpg", good[:300])
    put(root, "wall/shot_001.jpg", b"")                                         # calibration: never looked at
    put(root, "capture/person/p.jpg", b"")                                      # people: never looked at
    bad, scanned, skipped = fu.scan({"g2_pictures": str(root)})
    names = sorted(os.path.basename(p) for _, p, _ in bad)
    assert names == ["empty.jpg", "frag.jpg"] and skipped == 1 and scanned == 4
    monkeypatch.setenv("G2_REVIEW_DIR", str(tmp_path / "review"))
    monkeypatch.delenv("G2_PI", raising=False)
    out = fu.delete(bad, str(root))
    assert out["deleted_files"] == 4 and not (root / "explore/named/greenball/empty.jpg").exists() and (root / "wall/shot_001.jpg").exists() and (root / "capture/person/p.jpg").exists()
    import g2_review_queue as rq
    mods = {e["module"]: e["args"] for e in rq.pending()}
    assert mods["pi_pipeline.vision.exploration_pictures"][1] == "named/greenball/empty.jpg" and mods["pi_pipeline.vision.claw_pictures"][1] == "watch_1/frag.jpg"
