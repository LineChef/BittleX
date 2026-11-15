"""The lift calibration and the stream probe: what they compute and when they stop."""
import pytest

from pi_pipeline.behavior import lift_cal as lc
from pi_pipeline.vision import stream_probe as sp


def test_the_shift_per_degree_comes_from_consecutive_steps_with_the_ball_in_both():
    rows = [{"lift": 120, "cy": 0.40}, {"lift": 105, "cy": 0.48}, {"lift": 90, "cy": None}, {"lift": 75, "cy": 0.70}]
    s = lc.shift_per_degree(rows)
    assert len(s) == 1 and s[0]["from"] == 120 and s[0]["to"] == 105 and s[0]["view_deg_per_lift_deg"] == pytest.approx(0.08 * lc.FOV_DEG / 15, abs=0.01)


class Robot:
    def __init__(self, tilts):
        self.calls, self.tilts = [], list(tilts)

    def _tilt(self, *a, **k):
        return self.tilts.pop(0) if len(self.tilts) > 1 else self.tilts[0]

    def relax(self):
        return "ok"

    def _fell(self):
        return False

    def claw_pose(self, pan, lift):
        self.calls.append(("claw", pan, lift))
        return "ok"

    def stand_up(self):
        self.calls.append("stand_up")


def test_the_calibration_steps_down_and_stops_at_the_first_tilt_and_puts_everything_back():
    r = Robot([(0.0, 0.0), (0.0, 0.0), (1.0, 1.0), (2.0, 8.0)])                         # check, base, step 1, step 2 tilts 8 deg: stop
    n = {"i": 0}

    def look():
        n["i"] += 1
        return (0.5, 0.4 + 0.01 * n["i"], 0.1, 0.1)
    res = lc.run_lift_cal(r, look, lifts=(120.0, 105.0, 90.0), say=lambda *_: None, sleep=lambda s: None)
    assert res["ended"] == "tilt" and [x["lift"] for x in res["rows"]] == [120.0, 105.0]
    assert r.calls[-2:] == [("claw", 0.0, 0.0), "stand_up"]


def test_a_silent_board_and_a_lost_ball_stop_the_calibration():
    r = Robot([None])
    assert lc.run_lift_cal(r, lambda: None, say=lambda *_: None, sleep=lambda s: None)["ended"] == "no_board" and r.calls == []
    r2 = Robot([(0.0, 0.0)])
    assert lc.run_lift_cal(r2, lambda: None, lifts=(120.0, 105.0, 90.0), say=lambda *_: None, sleep=lambda s: None)["ended"] == "lost"


def test_the_probe_counts_pictures_gaps_and_other_lines():
    r = sp.analyze([(0.5, 4000, 0), (0.7, 4100, 1), (0.9, 3900, 0), (1.5, 4000, 0)], ["{\"type\":0}"], 2.0)
    assert r["pictures"] == 4 and r["pictures_per_s"] == 2.0 and r["gap_median_s"] == 0.2 and r["gap_max_s"] == 0.6 and r["with_boxes"] == 1 and r["other_lines"] == 1


class Ser:
    def __init__(self, lines):
        self.lines, self.written = list(lines), []

    def reset_input_buffer(self):
        pass

    def write(self, b):
        self.written.append(b)

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def test_the_probe_starts_the_loop_with_pictures_and_always_breaks_at_the_end(tmp_path):
    class S:
        jpeg = b"jpg"
        detections = []
    t = {"now": 0.0}

    def clock():
        t["now"] += 0.25
        return t["now"]
    ser = Ser([b"x\n", b"y\n"])
    res = sp.run_probe(ser, 1.5, tmp_path, clock=clock, parse=lambda line, labels: S() if line.startswith("x") else None, sleep=lambda s: None)
    assert ser.written[0] == sp.BREAK and sp.LOOP_WITH_PICTURE in ser.written and ser.written[-1] == sp.BREAK
    assert res["pictures"] == 1 and (tmp_path / "frame_1.jpg").exists()


def test_the_attentive_looks_take_pictures_without_the_shutter_click_and_other_modes_keep_it(monkeypatch):
    """2026-11-15 (registered mode exception): the bout, live follow, camera checks and lift calibration build their camera with click=False; the default stays on."""
    from pi_pipeline.vision import snapshot as snap
    from pi_pipeline.voice import shutter
    clicks = []
    monkeypatch.setattr(shutter, "click", lambda: clicks.append(1))

    class Ser:
        def reset_input_buffer(self):
            pass

        def write(self, b):
            pass

        def readline(self):
            return b""
    for click, want in ((False, 0), (True, 1)):
        cam = snap.CameraSnapshotter("x", click=click, serial_factory=Ser, sleep=lambda s: None, exposure_check=False)
        cam._ser = Ser()
        cam._grab_one = lambda: snap.Snapshot(b"jpg", 240, 240, [])
        cam._arm_idle_close = lambda: None
        cam._save = lambda s: None
        monkeypatch.setattr("pi_pipeline.vision.picture_tilt.estimate", lambda jpeg: None, raising=False)
        clicks.clear()
        assert cam.snapshot() is not None and len(clicks) == want
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for f in ("behavior/attentive_bout.py", "behavior/gallery_target.py", "behavior/lift_cal.py", "vision/stream_probe.py"):
        assert "click=False" in (root / f).read_text() and f in (root.parent / "docs/specification/mode-exceptions.md").read_text()
