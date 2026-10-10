"""Promoted pictures are learned by the robot's gallery automatically (vision/promoted_loader.py)."""
import io
import json

from PIL import Image

from pi_pipeline.vision import promoted_loader as pl
from pi_pipeline.vision.object_gallery import ObjectGallery, ObjectGalleryConfig


class FlatEmbedder:
    """A trivial embedder: the mean colour, so two different colours are different objects."""
    def embed(self, img):
        px = img.convert("RGB").resize((1, 1)).getpixel((0, 0))
        n = (sum(c * c for c in px) ** 0.5) or 1.0
        return [c / n for c in px]


def _jpg(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", (96, 96), color)
    import random
    r = random.Random(sum(color))
    im.putdata([tuple(min(255, max(0, c + r.randint(-40, 40))) for c in color) for _ in range(96 * 96)])
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    path.write_bytes(buf.getvalue())


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(pl, "PENDING", tmp_path / "pending.json")
    monkeypatch.setattr(pl, "exploring", lambda: False)
    return tmp_path / "pics", tmp_path / "gallery.json"


def test_a_promoted_picture_is_learned_under_its_label_and_the_queue_empties(monkeypatch, tmp_path):
    root, gpath = setup(monkeypatch, tmp_path)
    _jpg(root / "named/red-mug/mug_1.jpg", (200, 30, 30))
    out = pl.add(["named/red-mug/mug_1.jpg"], gallery_path=str(gpath), pictures_root=str(root), embedder=FlatEmbedder())
    assert out["deferred"] is False and [x["path"] for x in out["loaded"]] == ["named/red-mug/mug_1.jpg"]
    gal = ObjectGallery.load(gpath, ObjectGalleryConfig(lock_by_holdout=True))
    assert [e.name for e in gal.entries.values()] == ["red mug"]
    assert pl._pending() == []


def test_a_look_alike_with_a_different_name_is_a_conflict_not_an_overwrite(monkeypatch, tmp_path):
    root, gpath = setup(monkeypatch, tmp_path)
    _jpg(root / "named/red-mug/a.jpg", (200, 30, 30))
    _jpg(root / "named/red-cup/b.jpg", (205, 32, 28))
    pl.add(["named/red-mug/a.jpg"], gallery_path=str(gpath), pictures_root=str(root), embedder=FlatEmbedder())
    out = pl.add(["named/red-cup/b.jpg"], gallery_path=str(gpath), pictures_root=str(root), embedder=FlatEmbedder())
    assert out["loaded"] == [] and out["conflicts"][0]["path"] == "named/red-cup/b.jpg" and out["conflicts"][0]["conflict"][0] == "red mug"


def test_while_an_exploration_runs_the_picture_waits_in_the_queue_and_survey_or_missing_paths_are_skipped(monkeypatch, tmp_path):
    root, gpath = setup(monkeypatch, tmp_path)
    monkeypatch.setattr(pl, "exploring", lambda: True)
    out = pl.add(["named/mug/x.jpg"], gallery_path=str(gpath), pictures_root=str(root), embedder=FlatEmbedder())
    assert out["deferred"] is True and pl._pending() == ["named/mug/x.jpg"] and not gpath.exists()
    monkeypatch.setattr(pl, "exploring", lambda: False)
    _jpg(root / "named/mug/x.jpg", (30, 200, 30))
    pl._save_pending(["named/mug/x.jpg", "survey/20261010/a.jpg", "named/mug/gone.jpg"])
    out = pl.process(gallery_path=str(gpath), pictures_root=str(root), embedder=FlatEmbedder())
    assert [x["path"] for x in out["loaded"]] == ["named/mug/x.jpg"] and sorted(out["missing"]) == ["named/mug/gone.jpg", "survey/20261010/a.jpg"]
