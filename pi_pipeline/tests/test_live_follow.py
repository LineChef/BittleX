"""Live follow (behavior/live_follow.py): steer from where the claw pointed when the picture was taken, never from where it points now."""
import time

import pytest

from pi_pipeline import focus
from pi_pipeline.behavior import live_follow as lf


@pytest.fixture(autouse=True)
def _focus_file(tmp_path, monkeypatch):
    monkeypatch.setenv("G2_FOCUS_FILE", str(tmp_path / "focus.json"))


def ball(cx, w=0.1):
    return ("ball", 1.0, cx, 0.6, w, w)


def test_the_pan_log_interpolates_a_move_and_holds_between_moves():
    log = lf.PanLog(0.0, 0.0)
    log.move(10.0, 11.0, 0.0, -20.0)
    assert log.at(5.0) == 0.0 and log.at(10.5) == pytest.approx(-10.0) and log.at(11.0) == -20.0 and log.at(30.0) == -20.0
    log.move(20.0, 20.0, -20.0, 5.0)                                                    # an instant move
    assert log.at(19.9) == -20.0 and log.at(20.0) == 5.0


def test_a_picture_taken_before_a_move_is_corrected_from_the_pan_it_was_taken_at():
    """The ball is 20 deg right in a picture taken at pan 0; the claw has since gone to -10. The correction is -10 from 0 (gain .5), not -10 more from -10: an old picture must not make it overshoot."""
    cfg = lf.LiveConfig(gain=0.5)
    log = lf.PanLog(0.0, 0.0)
    log.move(5.0, 5.2, 0.0, -10.0)
    f = lf.LiveFollower(cfg, "left", log)
    off_cx = 0.5 + 20.0 / (2 * cfg.fov_half_deg)                                        # a ball 20 deg to the right
    assert f.decide(t_capture=4.0, dets=[ball(off_cx)], now=5.8, pan_now=-10.0) is None and "already there" in f.reason       # the claw is already where this picture says: no more
    f2 = lf.LiveFollower(cfg, "left", log)
    want = f2.decide(t_capture=4.0, dets=[ball(off_cx)], now=5.8, pan_now=-4.0)                                                  # mid-move at -4: the target is still -10, from 0
    assert want == pytest.approx(-10.0, abs=0.1)
    assert f2.decide(t_capture=4.0, dets=[ball(off_cx)], now=5.9, pan_now=-10.0) is None  # the same picture is never used twice


def test_the_deadband_the_stale_picture_the_no_new_picture_and_the_pan_limit():
    cfg = lf.LiveConfig()
    f = lf.LiveFollower(cfg, "left", lf.PanLog())
    assert f.decide(1.0, [ball(0.52)], 1.2, 0.0) is None and "centred" in f.reason
    assert f.decide(2.0, [ball(0.9)], 6.0, 0.0) is None and f.reason == "picture too old"
    assert f.decide(7.0, [], 7.1, 0.0) is None and f.reason == "nothing in view"
    far = f.decide(8.0, [ball(0.99)], 8.1, 34.0)                                        # a big offset: clamped at the pan limit
    assert far is not None and abs(far) <= cfg.pan_max_deg
    right = lf.LiveFollower(cfg, "right", lf.PanLog()).decide(1.0, [ball(0.9)], 1.1, 0.0)
    assert right > 0                                                                    # the other pan sign flips the direction


def test_the_summary_counts_pictures_detections_and_reversals():
    rows = [{"grab_s": 0.4, "det": [("ball", 0.5)]}, {"grab_s": 0.5, "det": []}, {"grab_s": 0.3, "det": [("ball", 0.4)]}]
    s = lf.summarize(rows, [{"age_s": 0.8}, {"age_s": 0.6}], reversals=1, seconds=2.0)
    assert s["pictures"] == 3 and s["pictures_per_s"] == 1.5 and s["with_target"] == 2 and s["moves"] == 2 and s["reversals"] == 1 and s["use_age_s_mean"] == 0.7


class Snap:
    jpeg = b"x"


class FakeRobot:
    def __init__(self, tilt=(0.0, 0.0)):
        self.calls, self.sent, self._roll, self._pitch, self.tilt = [], [], [], [], tilt

    def _tilt(self, *a, **k):
        return self.tilt

    def relax(self):
        self.calls.append("relax")
        return "ok"

    def claw_pose(self, pan, lift):
        self.calls.append(("claw", round(pan, 1), lift))
        return "ok"

    def _fell(self):
        return False

    def _tx(self, c):
        self.sent.append(c)

    def stand_up(self):
        self.calls.append("stand_up")
        return "ok"


def test_a_short_live_run_follows_puts_everything_back_and_reports(tmp_path):
    held = []

    def snap():
        time.sleep(0.01)
        return Snap()
    r = FakeRobot()
    res = lf.run_live(r, snap, lambda jpeg: [ball(0.85)], lf.LiveConfig(seconds=0.4, tick_s=0.02), say=lambda *_: None, stopped=lambda: bool(held))
    assert res["ended"] == "time" and res["summary"]["pictures"] > 3 and res["summary"]["with_target"] > 3
    moves = [c for c in r.calls if isinstance(c, tuple) and c[1] != 0.0 and c[2] == 120.0]
    assert moves and all(c[1] < 0 for c in moves)                                       # the ball is on his right: the camera turns right, a negative pan
    assert r.calls[0] == "relax" and r.calls[-2:] == [("claw", 0.0, 0.0), "stand_up"]
    assert not focus.held()
    p = lf.write_log(res, str(tmp_path))
    assert p and p.endswith("live_log.json")


def test_a_silent_board_moves_nothing_and_a_stop_ends_the_run():
    r = FakeRobot()
    r._tilt = lambda *a, **k: None
    res = lf.run_live(r, lambda: Snap(), lambda j: [], lf.LiveConfig(seconds=5), say=lambda *_: None)
    assert res["ended"] == "no_board" and r.calls == []
    r2 = FakeRobot()
    res2 = lf.run_live(r2, lambda: Snap(), lambda j: [], lf.LiveConfig(seconds=5, tick_s=0.01), say=lambda *_: None, stopped=lambda: True)
    assert res2["ended"] == "stopped" and r2.calls[-2:] == [("claw", 0.0, 0.0), "stand_up"]


def test_the_step_report_finds_when_a_fixed_target_settled_and_counts_reversals():
    rows = [{"t_capture": 0.0 + i * 0.5, "det": [("ball", 0.9 if i < 3 else 0.54 if i < 6 else 0.5)]} for i in range(10)]
    moves = [{"from": 0, "to": -10}, {"from": -10, "to": -15}, {"from": -15, "to": -13}]
    r = lf.step_report(rows, moves)
    assert r["first_offset_deg"] == pytest.approx(0.4 * 2 * 44.0, abs=0.1) and r["settled_after_s"] == 1.5 and r["reversals"] == 1
    assert r["final_offset_deg"] == 0.0 and r["worst_offset_after_settling_deg"] <= 4.0
    assert lf.step_report([{"t_capture": 0.0, "det": []}], [])["pictures_with_target"] == 0


def _real_jpeg():
    import io

    import numpy as np
    from PIL import Image
    b = io.BytesIO()
    Image.fromarray(np.random.default_rng(3).integers(0, 255, (96, 96, 3), dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()


def test_the_stream_grabber_reads_pictures_skips_bad_frames_and_always_breaks_at_the_end():
    from pi_pipeline.vision import stream_probe as sp
    good = _real_jpeg()

    class S:
        def __init__(self, jpeg):
            self.jpeg, self.detections = jpeg, []

    class Ser:
        def __init__(self, lines):
            self.lines, self.written = list(lines), []

        def reset_input_buffer(self):
            pass

        def write(self, b):
            self.written.append(b)

        def readline(self):
            if self.lines:
                return self.lines.pop(0)
            time.sleep(0.005)
            return b""
    ser = Ser([b"g\n", b"g\n", b"x\n", b"g\n", b"g\n", b"g\n"])               # "x" is a frame cut short
    g = lf.StreamGrabber(ser, lambda jpeg: [ball(0.7)], lf.LiveConfig(), parse=lambda line, labels: S(good if line.startswith("g") else good[:200]), latency_s=0.25, sleep=lambda s: None)
    g.start()
    deadline = time.time() + 3.0
    while len([r for r in g.rows if not r.get("bad")]) < 5 and time.time() < deadline:
        time.sleep(0.01)
    g.stop_flag.set()
    g.join(timeout=3.0)
    ok = [r for r in g.rows if not r.get("bad")]
    assert len(ok) == 5 and g.bad == 1 and ok[0]["t_call"] - ok[0]["t_capture"] == pytest.approx(0.25, abs=0.01) and g.take()[2] == 5     # the cut frame is neither a sighting nor a miss
    assert ser.written[0] == sp.BREAK and sp.LOOP_WITH_PICTURE in ser.written and ser.written[-1] == sp.BREAK
    assert lf.summarize(g.rows, [], 0, 2.0)["bad_frames"] == 1 and lf.valid_jpeg(good) and not lf.valid_jpeg(good[:200])


def test_run_live_can_use_another_grabber():
    made = []

    class Fake(lf.Grabber):
        def run(self):
            made.append(1)
            self.stop_flag.wait(0.3)
    r = FakeRobot()
    res = lf.run_live(r, lambda: None, lambda j: [], lf.LiveConfig(seconds=0.2, tick_s=0.02), say=lambda *_: None, make_grabber=lambda find, cfg, clock, save: Fake(lambda: None, find, cfg, clock=clock))
    assert made == [1] and res["ended"] == "time"
