import numpy as np

from pi_pipeline.voice import camera_sounds as cs
from pi_pipeline.vision.snapshot import CameraSnapshotter


def dominant_hz(y, rate=48000, t0=0.0, t1=None):
    seg = y[int(t0 * rate):int((t1 or len(y) / rate) * rate)].astype(float)
    sp = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), 1 << 16))
    return np.fft.rfftfreq(1 << 16, 1 / rate)[np.argmax(sp)]


def test_each_sound_has_its_own_length_and_the_requested_level():
    lens = {n: len(cs.render(n)) / 48000 for n in ("shutter", "recording", "recording_stop")}
    assert lens["shutter"] < 0.1 and 0.2 < lens["recording"] < 0.35 and abs(lens["recording"] - lens["recording_stop"]) < 1e-6
    for n in lens:
        assert abs(np.abs(cs.render(n, peak=0.045)).max() / 32767 - 0.045) < 0.002


def test_recording_rises_and_recording_stop_falls():
    up, down = cs.render("recording"), cs.render("recording_stop")
    assert dominant_hz(up, t0=0.0, t1=0.09) < dominant_hz(up, t0=0.12, t1=0.25)
    assert dominant_hz(down, t0=0.0, t1=0.09) > dominant_hz(down, t0=0.12, t1=0.25)


def test_unknown_sound_is_an_error():
    import pytest
    with pytest.raises(ValueError):
        cs.render("beep")


def test_indicator_plays_start_then_reminders_then_stop():
    played = []
    ind = cs.CameraActivityIndicator(reminder_s=0.05, play=played.append).start()
    import time
    time.sleep(0.2)
    ind.stop(); ind.stop()                                   # a second stop does nothing
    assert played[0] == "recording" and played[-1] == "recording_stop" and played.count("recording") >= 2
    assert played.count("recording_stop") == 1


def test_indicator_without_reminders_plays_just_start_and_stop():
    played = []
    cs.CameraActivityIndicator(reminder_s=0, play=played.append).start().stop()
    assert played == ["recording", "recording_stop"]


def test_snapshot_calls_on_capture_once_per_picture_and_not_on_failure():
    from pi_pipeline.tests.test_vision_describe import FakeSerial, invoke_line, make_cam
    calls = []
    ok = make_cam(FakeSerial([invoke_line()]), on_capture=lambda: calls.append(1))
    assert ok.snapshot() is not None and calls == [1]
    bad = make_cam(FakeSerial([]), on_capture=lambda: calls.append(1))
    assert bad.snapshot() is None and calls == [1]
