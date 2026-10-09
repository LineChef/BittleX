"""The exploration pictures prep the camera (the throwaway frames that settle auto-exposure) for the first picture and again after `prep_every_s`, not for every picture."""
from pi_pipeline.vision import exploration_pictures as EP


class Snap:
    jpeg = b"\xff\xd8jpg"
    width = height = 240
    detections = []


class Src:
    def __init__(self):
        self.calls = []

    def snapshot(self, timeout_s=6.0, settle=None):
        self.calls.append(settle)
        s = Snap()
        s.jpeg = b"\xff\xd8" + bytes([len(self.calls)]) * 40          # distinct pictures, so none is dropped as a near-duplicate
        return s


def test_prep_on_the_first_picture_and_again_half_way(tmp_path):
    t = [1000.0]
    src = Src()
    saver = EP.ExplorationPictureSaver(src, str(tmp_path), clock=lambda: t[0], prep_every_s=300.0, survey_distance=-1)
    for _ in range(4):
        saver("after_bow")
        t[0] += 60.0
    assert src.calls == [None, 0, 0, 0]                    # the first prepped, the next three not
    t[0] += 100.0                                           # now 340 s after the first
    saver("after_bow")
    assert src.calls[-1] is None                           # prepped again half way
    saver("name:mug")
    assert src.calls[-1] is None                           # a picture the user named is always prepped


def test_without_prep_every_s_every_picture_is_prepped(tmp_path):
    src = Src()
    saver = EP.ExplorationPictureSaver(src, str(tmp_path), survey_distance=-1)
    saver("after_bow")
    saver("after_bow")
    assert src.calls == [None, None]


def test_a_cut_off_jpeg_is_not_kept(tmp_path):
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 90, 60)).save(buf, "JPEG")
    good = buf.getvalue()

    class One:
        def __init__(self, jpeg):
            self.jpeg = jpeg

        def snapshot(self, timeout_s=6.0, settle=None):
            s = Snap()
            s.jpeg = self.jpeg
            return s
    assert EP.ExplorationPictureSaver(One(good), str(tmp_path), survey_distance=-1)("after_bow") is not None
    cut = EP.ExplorationPictureSaver(One(good[: len(good) // 2]), str(tmp_path / "cut"), survey_distance=-1)
    assert cut("after_bow") is None and cut.truncated == 1
