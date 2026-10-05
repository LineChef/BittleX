import base64
import io
import json
import re

from PIL import Image

from pi_pipeline.vision.snapshot import (BUMP_MAX, BUMP_MIN, CameraSnapshotter, ExposureStats, exposure_score, exposure_stats,
                                         next_bump)


def make_jpeg(values) -> bytes:
    im = Image.new("L", (32, 32))
    im.putdata(values)
    buf = io.BytesIO(); im.convert("RGB").save(buf, "JPEG", quality=95); return buf.getvalue()


def scene(kind: str):
    """Scene radiance per pixel (it can exceed 255: a lamp). The camera's picture is radiance x gain, clipped."""
    n = 32 * 32
    if kind == "bright":                       # a lamp (15%) in a lit room
        return [600.0] * int(n * 0.15) + [150.0] * (n - int(n * 0.15))
    if kind == "dark":
        return [20.0] * n
    if kind == "fine":
        return [115.0] * n
    if kind == "lamp-only":                    # blown out whatever the exposure: nothing to gain
        return [2000.0] * n
    raise ValueError(kind)


class SimCamera:
    """A serial-like fake: tracks the exposure registers it is sent and answers each one-shot invoke with a picture whose brightness
    follows the exposure offset (gain = 2 ** (bump / 32)). The first picture after a register write is stale (auto-exposure lag)."""
    def __init__(self, kind, start_bump=32):
        self.kind, self.bump, self.stale = kind, start_bump, False
        self._lines, self.invokes, self.clock = [], 0, [0.0]
        self.written = []

    def reset_input_buffer(self):
        self._lines = []

    def write(self, b):
        s = b.decode()
        self.written.append(s)
        m = re.match(r'AT\+SETREG="0x3A0F","0x([0-9A-F]+)"', s)
        if m:
            self._pending = int(m.group(1), 16) - 0x32
        m2 = re.match(r'AT\+SETREG="0x3A1E"', s)
        if m2:                                    # all four registers written: the new target is now set (frames lag one behind)
            self.stale_bump, self.bump, self.stale = self.bump, self._pending, True
        if s.startswith("AT+INVOKE=1,0,0"):
            self.invokes += 1
            bump = self.stale_bump if self.stale else self.bump
            self.stale = False
            gain = 2 ** (bump / 32.0)
            vals = [min(255, int(v * gain)) for v in scene(self.kind)]
            data = {"count": 0, "resolution": [32, 32], "boxes": [], "image": base64.b64encode(make_jpeg(vals)).decode()}
            self._lines.append(json.dumps({"type": 1, "name": "INVOKE", "code": 0, "data": data}))

    def readline(self):
        if self._lines:
            return (self._lines.pop(0) + "\n").encode()
        self.clock[0] += 1.0
        return b""

    def close(self):
        pass


def make(kind, ae_bump=32, **kw):
    cam = SimCamera(kind)
    cam.bump = ae_bump
    cam._pending = ae_bump
    t = cam.clock

    def sleep(s):
        t[0] += s
    c = CameraSnapshotter("x", ae_bump=ae_bump, serial_factory=lambda: cam, sleep=sleep, clock=lambda: t[0], idle_close_s=0, **kw)
    return c, cam


def brightness(snap):
    return exposure_stats(snap.jpeg)


# ---- the pure decisions

def test_stats_see_blown_out_and_crushed_pixels():
    bright = exposure_stats(make_jpeg([255] * 1024))
    dark = exposure_stats(make_jpeg([2] * 1024))
    assert bright.clip_high > 0.95 and dark.clip_low > 0.95 and bright.mean > 240 > 20 > dark.mean


def test_next_bump_goes_down_when_too_bright_up_when_too_dark_and_stays_when_fine():
    assert next_bump(32, ExposureStats(220, 0.5, 0.0)) == -16                  # badly blown out: the biggest step (48)
    assert next_bump(32, ExposureStats(146, 0.206, 0.0)) == -12                # the measured desk-lamp case: 20.6% blown out -> about -14, in one move
    assert next_bump(32, ExposureStats(150, 0.12, 0.0)) == 12                  # mildly: a gentle one
    assert next_bump(0, ExposureStats(20, 0.0, 0.7)) == 16 or next_bump(0, ExposureStats(20, 0.0, 0.7)) == 32
    assert next_bump(0, ExposureStats(10, 0.0, 0.95)) == 32                    # very dark: a big step up
    assert next_bump(10, ExposureStats(115, 0.01, 0.02)) is None               # fine
    assert next_bump(BUMP_MIN, ExposureStats(250, 0.9, 0.0)) is None           # no room left
    assert next_bump(BUMP_MAX, ExposureStats(5, 0.0, 0.99)) is None


def test_score_prefers_fewer_blown_out_pixels_over_a_perfect_mean():
    assert exposure_score(ExposureStats(115, 0.3, 0.0)) > exposure_score(ExposureStats(150, 0.01, 0.0))


# ---- the camera loop

def test_a_well_lit_scene_takes_one_picture_and_leaves_the_exposure_alone():
    c, cam = make("fine", ae_bump=0)
    assert c.snapshot() is not None
    assert cam.invokes == 1 and c._bump == 0


def test_a_bright_scene_is_retaken_with_a_lower_exposure_and_the_better_frame_wins():
    c, cam = make("bright", ae_bump=32)
    first_stats = exposure_stats(make_jpeg([min(255, int(v * 2)) for v in scene("bright")]))     # what the camera sees at bump 32
    snap = c.snapshot()
    assert cam.invokes > 1 and c._bump < 32
    assert exposure_score(brightness(snap)) < exposure_score(first_stats)
    assert brightness(snap).clip_high < first_stats.clip_high


def test_a_dark_scene_is_retaken_with_a_higher_exposure():
    c, cam = make("dark", ae_bump=0)
    snap = c.snapshot()
    assert cam.invokes > 1 and c._bump > 0
    assert brightness(snap).mean > 40                                            # it was 20 before


def test_retries_are_limited_and_a_hopeless_scene_stops_early():
    c, cam = make("lamp-only", ae_bump=32)
    assert c.snapshot() is not None
    assert cam.invokes <= 1 + 2 * 2                                              # first frame + at most 2 retries of 2 grabs each


def test_the_learned_exposure_carries_to_the_next_look_and_resets_when_the_camera_closes():
    c, cam = make("dark", ae_bump=0)
    c.snapshot()
    learned = c._bump
    assert learned > 0
    before = cam.invokes
    c.snapshot()                                                                  # same room: starts from the learned setting
    assert cam.invokes - before == 1 and c._bump == learned
    c.close()
    assert c._bump == 0                                                           # a closed camera forgets the room


def test_the_check_can_be_turned_off():
    c, cam = make("bright", ae_bump=32, exposure_check=False)
    assert c.snapshot() is not None and cam.invokes == 1 and c._bump == 32


# ---- a dark frame the sensor cannot fix is lifted in software

def test_brighten_lifts_a_dark_frame_toward_the_target_and_leaves_normal_frames_alone():
    from pi_pipeline.vision.snapshot import brighten
    dark = make_jpeg([40] * 1024)
    lifted = brighten(dark, exposure_stats(dark).mean)
    assert 80 < exposure_stats(lifted).mean < 130
    fine = make_jpeg([115] * 1024)
    assert brighten(fine, 115.0) is fine
    assert brighten(b"not a jpeg", 20.0) == b"not a jpeg"


def test_a_scene_too_dark_for_any_exposure_setting_is_brightened_in_software():
    SimCamera_scene = scene
    import pi_pipeline.tests.test_exposure as me
    me.scene = lambda kind: [5.0] * 1024 if kind == "very-dark" else SimCamera_scene(kind)   # radiance so low even bump +64 stays dark
    try:
        c, cam = make("very-dark", ae_bump=0)
        snap = c.snapshot()
    finally:
        me.scene = SimCamera_scene
    assert exposure_stats(snap.jpeg).mean > 60                                      # lifted from ~13 at the best exposure setting
