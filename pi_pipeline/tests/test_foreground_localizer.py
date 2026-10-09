"""ForegroundLocalizer v1: object-like blobs that differ from the floor strip at the bottom of a floor-level picture."""
import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")

from pi_pipeline.vision.localizer import ForegroundLocalizer, GridLocalizer  # noqa: E402


def _floor(rng, size=240):
    img = np.empty((size, size, 3), dtype=float)
    img[:] = (150, 120, 90)                                   # a wooden floor colour
    img += rng.normal(0, 3, img.shape)                        # a little grain
    img += np.linspace(-8, 8, size)[:, None, None]            # and a soft light gradient
    return img


def _with_box(img, x0, y0, x1, y1, color):
    img = img.copy()
    img[y0:y1, x0:x1] = color
    return img


def test_empty_floor_has_no_candidates():
    rng = np.random.default_rng(0)
    assert ForegroundLocalizer().candidates(np.clip(_floor(rng), 0, 255).astype(np.uint8)) == []


def test_an_object_standing_on_the_floor_is_found_with_a_box_around_it():
    rng = np.random.default_rng(1)
    img = _with_box(_floor(rng), 90, 100, 150, 205, (30, 60, 160))        # a blue box standing in the middle of the frame
    cands = ForegroundLocalizer().candidates(np.clip(img, 0, 255).astype(np.uint8))
    assert len(cands) == 1
    x0, y0, x1, y1 = cands[0].box
    assert x0 < 0.4 < x1 and y0 < 0.6 < y1 and 0.08 < cands[0].area < 0.15 and 0.3 < x0 and x1 < 0.7


def test_a_frame_wide_band_is_background_not_an_object():
    rng = np.random.default_rng(2)
    img = _with_box(_floor(rng), 0, 0, 240, 90, (200, 200, 205))          # a wall across the whole top
    assert ForegroundLocalizer().candidates(np.clip(img, 0, 255).astype(np.uint8)) == []


def test_a_speck_is_ignored_and_views_start_with_the_whole_picture():
    rng = np.random.default_rng(3)
    img = np.clip(_with_box(_floor(rng), 100, 150, 108, 158, (0, 0, 0)), 0, 255).astype(np.uint8)
    assert ForegroundLocalizer().candidates(img) == []
    big = np.clip(_with_box(_floor(rng), 60, 90, 130, 200, (180, 40, 40)), 0, 255).astype(np.uint8)
    views = ForegroundLocalizer().views(big)
    assert views[0][0].whole and len(views) >= 2 and not views[1][0].whole
    assert len(GridLocalizer().views(big)) == 10                          # the v0 grid is untouched
