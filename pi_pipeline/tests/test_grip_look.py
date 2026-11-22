"""The grip look (behavior/grip_look.py): the classification on pictures made up in code with the recorded geometry, the camera warm-up, and that a failing camera never stops a throw."""
import numpy as np

from pi_pipeline.behavior import grip_look as gl
from pi_pipeline.behavior import scripted_skill


def picture(*boxes):
    img = np.full((240, 240, 3), 105, dtype=np.int16)
    for x0, y0, x1, y1, c in boxes:
        img[y0:y1, x0:x1] = c
    return img


GREEN, RED = (70, 170, 80), (200, 60, 50)


def test_a_block_like_the_good_grips_is_good_and_the_recorded_odd_cases_are_not():
    good = picture((105, 203, 155, 240, GREEN), (115, 199, 145, 203, RED))                   # about 2,000 px centred low in the frame
    r = gl.classify(good)
    assert r["verdict"] == "good" and gl.GOOD_PX[0] <= r["n"] <= gl.GOOD_PX[1] and r["cy"] >= gl.GOOD_ROW_MIN
    assert gl.classify(picture((60, 150, 180, 240, GREEN)))["verdict"] == "unclear"             # a very large block (the one bad grab was 5,114 px)
    assert gl.classify(picture((105, 150, 155, 190, GREEN)))["verdict"] == "unclear"            # a block of the right size but higher up: the cylinder on the floor at the claw
    assert gl.classify(picture())["verdict"] == "none" and gl.classify(picture((120, 215, 135, 225, GREEN)))["verdict"] == "none"      # nothing, or a sliver


class Cam:
    def __init__(self, jpeg_fn=None, fail=False):
        self.n, self.fail, self.closed = 0, fail, False

    def snapshot(self):
        self.n += 1
        if self.fail:
            raise RuntimeError("no camera")
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.fromarray(picture((105, 203, 155, 240, GREEN)).astype("uint8")).save(buf, "JPEG")

        class S:
            jpeg = buf.getvalue()
        return S()

    def close(self):
        self.closed = True


def test_the_looker_warms_the_camera_waits_for_the_frame_and_saves_the_picture(tmp_path):
    cam, slept = Cam(), []
    lk = gl.GripLooker(factory=lambda: cam, clock=lambda: 10.0, sleep=slept.append, save_dir=str(tmp_path))
    lk.warm()
    r = lk.look("lob_soft", since=9.5)                                                             # 0.5 s since the pick ended: waits the other second
    assert cam.n == 2 and r["verdict"] in ("good", "unclear") and abs(slept[0] - 1.0) < 1e-9 and r["file"].endswith("_lob_soft.jpg") and list(tmp_path.glob("*.jpg"))
    lk.close()
    assert cam.closed


def test_a_camera_that_fails_is_logged_and_the_throw_goes_on(tmp_path):
    said = []
    lk = gl.GripLooker(factory=lambda: Cam(fail=True), save_dir=str(tmp_path))
    lk.warm()
    r = gl.take_grip_look(lk, "lob_soft", since=0.0, say=said.append)
    assert "error" in r and said and "the throw goes ahead" in said[0]
    assert gl.take_grip_look(None, "x") is None
    assert gl.GripLooker(factory=lambda: Cam(), save_dir=str(tmp_path)).look("x", timeout_s=0.01) == {"error": "the camera did not warm up in time"}        # never warmed: no wait forever


def test_the_runner_accepts_the_switch_and_a_dry_run_touches_nothing(capsys):
    scripted_skill.main(["lob_soft", "--amount", "1", "--pick", "--grip-look", "--dry-run"])
    assert "bow" in capsys.readouterr().out
