import base64
import json
import types

from pi_pipeline.tests.conftest import Block, Resp
from pi_pipeline.vision.snapshot import CameraSnapshotter, Snapshot, parse_invoke_line
from pi_pipeline.voice.conversation import Conversation
from pi_pipeline.voice.loop import VoiceLoop, asks_what_g2_sees

JPEG = b"\xff\xd8\xff\xe0fake-jpeg-bytes\xff\xd9"


def invoke_line(boxes=None, res=(240, 240), image=True):
    data = {"count": 1, "resolution": list(res), "boxes": boxes or []}
    if image:
        data["image"] = base64.b64encode(JPEG).decode()
    return json.dumps({"type": 1, "name": "INVOKE", "code": 0, "data": data})


# ---- what counts as asking what G2 sees

def test_phrases_that_ask_what_g2_sees():
    for text in ("what do you see", "What can you see right now?", "what are you looking at", "look around",
                 "can you see the dog", "do you see me", "what's in front of you", "describe what you see", "tell me what you see"):
        assert asks_what_g2_sees(text), text


def test_ordinary_requests_do_not_trigger_the_camera():
    for text in ("walk forward", "how are you", "what time is it", "tell me a joke", "I see", "sit down please", ""):
        assert not asks_what_g2_sees(text), text


# ---- the snapshot module

def test_parse_invoke_line_gives_the_jpeg_and_detection_hint():
    snap = parse_invoke_line(invoke_line(boxes=[[60, 120, 120, 200, 92, 0], [200, 50, 30, 30, 20, 1]]), ["person_a", "dog", "cat"])
    assert snap.jpeg == JPEG and (snap.width, snap.height) == (240, 240)
    hint = snap.hint()
    assert "person_a 92% (left, mid-distance)" in hint and "dog" not in hint          # the 20% box is below the hint cutoff


def test_hint_when_nothing_is_detected():
    assert "nothing" in Snapshot(JPEG, 240, 240).hint()


def test_parse_ignores_lines_without_a_picture_or_that_are_not_results():
    assert parse_invoke_line(invoke_line(image=False)) is None
    assert parse_invoke_line(json.dumps({"type": 0, "name": "INVOKE", "code": 0})) is None
    assert parse_invoke_line("not json") is None and parse_invoke_line("") is None


class FakeSerial:
    clock = None                                  # set by make_cam: an empty read costs one second, like the real 1 s timeout

    def __init__(self, reply_lines):
        self.written, self._lines, self.closed = [], list(reply_lines), False

    def reset_input_buffer(self):
        pass

    def write(self, b):
        self.written.append(b)

    def readline(self):
        if self._lines:
            return (self._lines.pop(0) + "\n").encode()
        if self.clock is not None:
            self.clock[0] += 1.0
        return b""

    def close(self):
        self.closed = True


def make_cam(ser, **kw):
    t = [0.0]
    ser.clock = t
    def sleep(s): t[0] += s
    return CameraSnapshotter("x", labels=["person_a"], serial_factory=lambda: ser, sleep=sleep, clock=lambda: t[0], idle_close_s=0, **kw)


def test_snapshot_sends_one_shot_invoke_and_returns_the_frame():
    ser = FakeSerial([json.dumps({"type": 0, "name": "INVOKE", "code": 0}), invoke_line(boxes=[[120, 120, 100, 100, 80, 0]])])
    snap = make_cam(ser, sensor_opt=0).snapshot()
    assert snap.jpeg == JPEG and "person_a" in snap.hint()
    assert b"AT+INVOKE=1,0,0\r\n" in ser.written and b"AT+SENSOR=1,1,0\r\n" in ser.written


def test_snapshot_returns_none_on_timeout_and_never_raises():
    assert make_cam(FakeSerial([])).snapshot() is None
    def boom():
        raise OSError("no camera")
    cam = CameraSnapshotter("x", serial_factory=boom, sleep=lambda s: None, idle_close_s=0)
    assert cam.snapshot() is None


# ---- the conversation: the picture goes to Claude once and is not kept

def test_picture_is_sent_to_claude_but_replaced_by_a_placeholder_in_history(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("text", text="I see a desk.")))
    conv = Conversation(cfg)
    turn = conv.send("what do you see", image=JPEG, image_note="[Picture from G2's camera.] hint")
    sent = fake_anthropic.calls[-1]["messages"][-1]["content"]
    img = [b for b in sent if b.get("type") == "image"]
    assert len(img) == 1 and base64.b64decode(img[0]["source"]["data"]) == JPEG and img[0]["source"]["media_type"] == "image/jpeg"
    assert any("Picture from G2's camera" in b.get("text", "") for b in sent)
    assert turn.speech == "I see a desk."
    stored = conv._history[0]["content"]
    assert not any(b.get("type") == "image" for b in stored)                       # never kept or resent
    assert any("picture from G2's camera was shown here" in b.get("text", "") for b in stored)


def test_system_prompt_tells_claude_about_pictures(cfg, fake_anthropic):
    fake_anthropic.set_reply(Resp(Block("text", text="ok")))
    Conversation(cfg).send("hi")
    assert "small picture from your own camera" in fake_anthropic.calls[-1]["system"]


# ---- the voice loop

class _Conv:
    def __init__(self):
        self.calls = []

    def send(self, text, memory_context=None, **kw):
        self.calls.append((text, kw))
        return types.SimpleNamespace(speech="ok", actions=[], facts=[])

    def set_mood_hint(self, hint):
        pass

    def set_narration_hint(self, hint):
        pass


class _Cam:
    def __init__(self, snap):
        self.snap, self.snapshots, self.warms = snap, 0, 0

    def snapshot(self):
        self.snapshots += 1
        return self.snap

    def warm_async(self):
        self.warms += 1


def make_loop(camera, script):
    stt = types.SimpleNamespace(listen=lambda timeout_s=None: script.pop(0) if script else "")
    wake = types.SimpleNamespace(wait=lambda: None)
    tts = types.SimpleNamespace(speak=lambda t: None)
    act = types.SimpleNamespace(perform=lambda s, **k: None, stop=lambda: None, close=lambda: None)
    cue = types.SimpleNamespace(set=lambda s: None)
    conv = _Conv()
    return VoiceLoop(wake_word=wake, stt=stt, conversation=conv, tts=tts, actuator=act, cue=cue, follow_up_s=0.0, camera=camera), conv


def test_asking_what_g2_sees_attaches_a_picture_and_the_detector_hint():
    cam = _Cam(Snapshot(JPEG, 240, 240, [("person_a", 0.9, 0.5, 0.5, 0.6, 0.6)]))
    lp, conv = make_loop(cam, ["what do you see"])
    lp._one_turn()
    text, kw = conv.calls[0]
    assert kw["image"] == JPEG and "person_a 90% (center, close)" in kw["image_note"] and cam.snapshots == 1 and cam.warms == 1


def test_other_requests_take_no_picture():
    cam = _Cam(Snapshot(JPEG, 240, 240))
    lp, conv = make_loop(cam, ["walk forward"])
    lp._one_turn()
    assert conv.calls[0][1] == {} and cam.snapshots == 0


def test_a_broken_camera_still_answers_with_a_note_so_claude_does_not_invent():
    lp, conv = make_loop(_Cam(None), ["what do you see"])
    lp._one_turn()
    kw = conv.calls[0][1]
    assert "image" not in kw and "could not take a picture" in kw["image_note"]


def test_no_camera_means_no_picture_and_no_note():
    lp, conv = make_loop(None, ["what do you see"])
    lp._one_turn()
    assert conv.calls[0][1] == {}
