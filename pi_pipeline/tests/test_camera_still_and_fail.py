"""Camera: wait for stillness, warm up per picture, retake a badly exposed one; and the wrong-answer signal when a command fails."""
import io
import types

import pytest

np = pytest.importorskip("numpy")
PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from pi_pipeline.gait.stillness import StillnessWaiter  # noqa: E402
from pi_pipeline.vision.exploration_pictures import ExplorationPictureSaver  # noqa: E402


def imu_line(roll, pitch):
    return f"ICM: 0.00 0.00 1.00 0.0 {pitch:.1f} {roll:.1f}"


class Clock:
    def __init__(self): self.t = 0.0
    def __call__(self): return self.t
    def sleep(self, s): self.t += s


def test_it_waits_for_new_still_frames_and_gives_up_without_blocking_when_there_are_none_or_it_keeps_swaying():
    clk = Clock()
    frames = [[imu_line(2.0 + 3.0 * (i % 2), -1.0) for i in range(3)]] * 4 + [[imu_line(1.0, -1.0)] * 3] * 20      # a sway first, then steady
    it = iter(frames)
    w = StillnessWaiter(lambda: next(it, []), clock=clk, sleep=clk.sleep)
    assert w.wait(timeout_s=10.0) is True and 0.0 < clk.t < 10.0                      # still once five NEW steady frames are in
    clk2 = Clock()
    assert StillnessWaiter(lambda: [], clock=clk2, sleep=clk2.sleep).wait(timeout_s=3.0) is None and clk2.t >= 3.0      # no IMU: the picture is taken anyway
    clk3 = Clock()
    n = [0]

    def sway():
        n[0] += 1
        return [imu_line(4.0 if n[0] % 2 else -4.0, 0.0)]                                 # +4, -4, +4 ...: a steady 4 degree swing
    swaying = StillnessWaiter(sway, clock=clk3, sleep=clk3.sleep)
    assert swaying.wait(timeout_s=2.0) is False                                         # still swaying at the timeout


def _jpeg(mean):
    b = io.BytesIO()
    Image.fromarray(np.full((32, 32, 3), mean, dtype=np.uint8)).save(b, "JPEG")
    return b.getvalue()


class Source:
    def __init__(self, means): self.means, self.calls = list(means), []
    def snapshot(self, timeout_s=6.0, settle=None):
        self.calls.append(settle)
        return types.SimpleNamespace(jpeg=_jpeg(self.means.pop(0)), width=32, height=32, detections=[])


def test_each_picture_waits_for_stillness_warms_the_camera_up_and_a_badly_exposed_one_is_taken_again_keeping_the_better(tmp_path):
    order = []
    src = Source([200, 105])                                                           # too bright first, fine on the retake
    saver = ExplorationPictureSaver(src, str(tmp_path), prep_every_s=0.0, wait_still=lambda: order.append("still") or True)
    p = saver("survey")
    assert order == ["still"] and src.calls == [None, None]                           # prepped (settle not forced to 0) both times
    import json
    meta = json.loads(open(p[:-4] + ".json").read())
    assert meta["still"] is True and meta["retaken"] is True and 90 < meta["exposure"]["mean"] < 120      # the retake was kept


def test_no_picture_calls_the_failure_hook(tmp_path):
    fails = []
    src = types.SimpleNamespace(snapshot=lambda *a, **k: None)
    saver = ExplorationPictureSaver(src, str(tmp_path), on_failure=fails.append)
    assert saver("survey") is None and len(fails) == 1 and "no picture" in fails[0]


def test_a_motion_command_that_cannot_be_sent_plays_the_wrong_answer_signal_but_a_background_read_does_not(monkeypatch):
    from pi_pipeline.link.serial_link import SerialLink
    from pi_pipeline.voice import fail_sound, prompt_tones
    lk = SerialLink("/dev/null-nothing", baud=115200, auto_reconnect=False) if "auto_reconnect" in SerialLink.__init__.__code__.co_varnames else SerialLink("/dev/null-nothing", baud=115200)
    fails = []
    lk.on_failure = fails.append
    lk.send("kwkF", read_reply=False)                                                  # not connected: dropped
    lk.send("gb", read_reply=False)                                                    # a balance toggle: no horn
    lk.send("P", read_reply=False)
    assert len(fails) == 1 and fails[0].startswith("kwkF")
    played = []
    monkeypatch.setattr(prompt_tones, "play_refuse", lambda wait=False: played.append(wait))
    monkeypatch.setattr(prompt_tones, "_HORN_LAST", {})
    fail_sound.command_failed("x")
    fail_sound.command_failed("y")                                                     # inside the 8 s cooldown: one horn
    assert played == [False]
    monkeypatch.setenv("G2_FAIL_SOUND", "0")
    monkeypatch.setattr(prompt_tones, "_HORN_LAST", {})
    fail_sound.command_failed("z")
    assert played == [False]


def test_the_survey_stand_settle_is_3_3_seconds():
    from pi_pipeline.behavior.survey import SurveyConfig
    assert SurveyConfig().stand_settle_s == 3.3
