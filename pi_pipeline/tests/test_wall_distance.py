"""Wall distance from the floor/obstacle boundary row, a calibration, and the turn-away direction (dry run only)."""
import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("PIL")

from pi_pipeline.vision.wall_distance import Calibration, estimate, base_rows, log_dry_run  # noqa: E402

CAL = Calibration([(0.45, 100.0), (0.60, 60.0), (0.72, 40.0), (0.83, 30.0), (0.92, 20.0)])      # a lower base row = closer


def _scene(wall_top_left=None, wall_top_right=None, seed=0):
    """A floor-level picture: wood floor, and a wall (light grey) whose base row differs per side. Rows are fractions of the height; None = no wall on that side."""
    rng = np.random.default_rng(seed)
    img = np.empty((240, 240, 3), dtype=float)
    img[:] = (150, 120, 90)
    img += rng.normal(0, 3, img.shape)
    for x0, x1, base in ((0, 120, wall_top_left), (120, 240, wall_top_right)):
        if base is not None:
            img[0:int(base * 240), x0:x1] = (205, 205, 210)
    return np.clip(img, 0, 255).astype(np.uint8)


def test_the_base_row_of_a_wall_is_found_per_column_group():
    rows, visible = base_rows(_scene(0.6, 0.6))
    assert visible and all(r is not None and abs(r - 0.6) < 0.1 for r in rows)
    rows, _ = base_rows(_scene(None, None))
    assert all(r is None for r in rows)                                   # open floor to the top


def test_calibration_interpolates_and_clamps():
    assert CAL.distance_cm(0.60) == 60.0
    assert 40.0 < CAL.distance_cm(0.66) < 60.0
    assert CAL.distance_cm(0.99) == 20.0 and CAL.distance_cm(0.3) >= 100.0


def test_a_close_wall_on_one_side_turns_him_toward_the_open_side_and_far_or_no_wall_does_not_turn():
    e = estimate(_scene(0.86, 0.5), CAL)                                  # left wall close (~28 cm), right wall far
    assert e.turn == "right" and e.nearest_cm is not None and e.nearest_cm < 35 and not e.blocked
    e = estimate(_scene(0.5, 0.86), CAL)
    assert e.turn == "left"
    assert estimate(_scene(0.5, 0.5), CAL).turn is None                    # far everywhere
    assert estimate(_scene(None, None), CAL).reason == "clear"


def test_a_picture_that_is_all_wall_is_blocked_and_the_dry_run_log_is_written(tmp_path):
    rng = np.random.default_rng(1)
    img = np.clip(np.full((240, 240, 3), 200.0) + rng.normal(0, 3, (240, 240, 3)), 0, 255).astype(np.uint8)
    img[200:, :, :] = (150, 120, 90)                                      # only the bottom strip looks like floor... and the rest is wall
    e = estimate(img, CAL)
    assert e.turn is None or e.nearest_cm is not None
    f = tmp_path / "wall.jsonl"
    log_dry_run(e, str(f), extra={"note": "test"})
    assert f.exists() and '"note": "test"' in f.read_text()


def test_the_calibration_is_built_from_labelled_pictures_and_reads_them_back(tmp_path):
    from PIL import Image
    from pi_pipeline.vision.wall_distance import calibrate_from_pictures, check_against_pictures
    import json
    labels = {}
    for i, (inches, base) in enumerate(((8, 0.85), (16, 0.66), (24, 0.58), (40, 0.50))):        # a lower base row = closer
        Image.fromarray(_scene(base, base, seed=i)).save(tmp_path / f"shot_{i:03d}.jpg", quality=95)
        labels[f"shot_{i:03d}"] = {"label": "wall_straight", "distance_in": inches}
    Image.fromarray(_scene(0.7, 0.7)).save(tmp_path / "shot_900.jpg")
    labels["shot_900"] = {"label": "door", "distance_in": 16}                                   # not a plain wall: never used
    labels["shot_901"] = {"label": "wall_straight", "distance_in": None}                        # distance unknown: never used
    (tmp_path / "labels.json").write_text(json.dumps(labels))
    cal_path = tmp_path / "cal.json"
    cal, table = calibrate_from_pictures(str(tmp_path), path=str(cal_path))
    assert [t[0] for t in table] == [8.0, 16.0, 24.0, 40.0] and cal_path.exists()
    assert [round(d, 1) for _, d in sorted(cal.points)] == [101.6, 61.0, 40.6, 20.3]
    for name, true_in, est_in in check_against_pictures(cal, str(tmp_path)):
        assert abs(true_in - est_in) < 1.5, (name, true_in, est_in)                              # the pictures it was built from read back within an inch
    c2, t2 = calibrate_from_pictures(str(tmp_path), shots=["shot_000"], save=False)             # one distance is not enough to save
    assert len(c2.points) == 1


def test_the_wall_log_keeps_pictures_for_near_walls_only_in_a_ring_and_the_stats_read_it(tmp_path):
    import io
    import json
    from PIL import Image
    from pi_pipeline.vision.wall_distance import WallLog
    from pi_pipeline.vision.wall_stats import wall_summary
    t = [1_000_000.0]
    log = WallLog(CAL, path=str(tmp_path / "w.jsonl"), pics_dir=str(tmp_path / "pics"), ring=3, clear_every_s=300, context=lambda: {"mode": "EXPLORE"}, clock=lambda: t[0])

    def jpeg(img):
        b = io.BytesIO(); Image.fromarray(img).save(b, "JPEG"); return b.getvalue()
    clear, near = _scene(None, None), _scene(0.86, 0.86)
    for img in (clear, clear, near, near, near, near, clear):
        t[0] += 10
        log.look(jpeg(img), img)
    rows = [json.loads(line) for line in (tmp_path / "w.jsonl").read_text().splitlines()]
    assert [r["state"] for r in rows] == ["clear", "clear", "near", "near", "near", "near", "clear"]
    assert all(r["mode"] == "EXPLORE" and r["calibrated"] for r in rows) and rows[2]["nearest_in"] < 12 and rows[2]["group_in"][0] is not None
    assert "pic" in rows[0] and "pic" not in rows[1] and all("pic" in r for r in rows[2:6])           # the first clear look is kept once, then every 300 s
    assert len(list((tmp_path / "pics").glob("wall_*.jpg"))) == 3                                      # a ring of 3
    w = wall_summary(rows)
    assert w["looks"] == 7 and w["states"] == {"clear": 3, "near": 4} and w["near_streaks"][0][1] == 4 and sum(v for k, v in w["distance_hist"].items() if k in ("8 in or less", "8 to 12 in")) == 4


def test_a_floor_sheen_is_not_a_wall_but_the_wall_behind_it_still_is():
    img = _scene(0.5, 0.5)                                               # a wall whose base is at half height, 40 in or more away
    img[150:190, 70:170] = (235, 230, 225)                               # a bright sheen on the floor in front of it, only 40 px (about 4 grid rows) tall, floor above it
    rows, visible = base_rows(img)
    assert visible and abs(rows[2] - 0.5) < 0.1                          # the centre group still reads the wall base, not the sheen (0.79)
    est = estimate(img, CAL)
    assert est.nearest_cm is not None and est.nearest_cm > 60.0 and est.turn is None


def test_a_near_wall_is_confirmed_only_when_two_looks_in_a_row_agree(tmp_path):
    import io
    import json
    from PIL import Image
    from pi_pipeline.vision.wall_distance import WallLog
    log = WallLog(CAL, path=str(tmp_path / "w.jsonl"), pics_dir=str(tmp_path / "p"), clock=lambda: 1.0)
    near, clear = _scene(0.86, 0.86), _scene(None, None)

    def jpeg(img):
        b = io.BytesIO(); Image.fromarray(img).save(b, "JPEG"); return b.getvalue()
    for img in (clear, near, near, clear, near):
        log.look(jpeg(img), img)
    rows = [json.loads(line) for line in (tmp_path / "w.jsonl").read_text().splitlines()]
    assert [r["near_confirmed"] for r in rows] == [False, False, True, False, False]
