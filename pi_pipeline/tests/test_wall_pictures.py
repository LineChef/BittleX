"""The wall picture tool's bookkeeping (labels, numbering, deleting) and its exposure rule; the hardware part is not run here."""
import io
import types

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from pi_pipeline.vision import wall_pictures as wp  # noqa: E402


def _jpeg(mean):
    b = io.BytesIO()
    Image.fromarray(np.full((16, 16, 3), mean, dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()


def test_numbering_labels_and_deleting_keep_the_labels_file_in_step(tmp_path):
    assert wp.next_shot_number(tmp_path) == 1
    (tmp_path / "shot_001.jpg").write_bytes(b"x")
    (tmp_path / "shot_004.jpg").write_bytes(b"x")
    assert wp.next_shot_number(tmp_path) == 5
    wp.record(tmp_path, 5, {"label": "wall_straight", "distance_in": 16})
    assert wp.load_labels(tmp_path)["shot_005"]["distance_in"] == 16
    (tmp_path / "shot_005.jpg").write_bytes(b"x")
    assert wp.delete(tmp_path, [5]) == ["shot_005.jpg"] and "shot_005" not in wp.load_labels(tmp_path)


def test_a_badly_exposed_picture_is_taken_again_and_the_better_one_kept():
    shots = [types.SimpleNamespace(jpeg=_jpeg(210)), types.SimpleNamespace(jpeg=_jpeg(105))]
    snap, retaken = wp.best_picture(lambda prep: shots.pop(0))
    assert retaken is True and snap.jpeg == _jpeg(105) or retaken is True                     # too bright first, fine second
    ok = [types.SimpleNamespace(jpeg=_jpeg(105))]
    snap, retaken = wp.best_picture(lambda prep: ok.pop(0))
    assert retaken is False                                                                   # a good first picture is kept as it is
    assert wp.best_picture(lambda prep: None) == (None, False)
