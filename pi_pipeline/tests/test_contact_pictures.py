"""Instant contact pictures (vision/contact_pictures.py): frames at a stall suspect or a hit, for diagnosis only."""
import json
import types

from pi_pipeline.behavior.bindings import DriverBindings
from pi_pipeline.behavior.driver import Effect, EffectKind
from pi_pipeline.vision.contact_pictures import ContactPictures


class Cam:
    def __init__(self, frames=2):
        self.calls, self.n = [], frames

    def snapshot(self, settle=None):
        self.calls.append(settle)
        self.n -= 1
        return types.SimpleNamespace(jpeg=b"\xff\xd8jpegdata", detections=[("box", 0.5, 0.5, 0.2, 0.2, 0.1)]) if self.n >= 0 else None


def mk(tmp_path, cam=None, **kw):
    return ContactPictures(cam or Cam(), str(tmp_path), threaded=False, sleep=lambda s: None, **kw)


def test_two_instant_frames_with_a_sidecar(tmp_path):
    cam = Cam()
    c = mk(tmp_path, cam, context=lambda: {"mode": "EXPLORE"})
    assert c.capture("hit", {"x": 1})
    assert cam.calls == [0, 0]                                   # settle=0: no warm-up, no waiting for stillness
    names = sorted(p.name for p in tmp_path.glob("*.jpg"))
    assert len(names) == 2 and names[0].endswith("_hit_1.jpg")
    meta = json.loads(next(tmp_path.glob("*_1.json")).read_text())
    assert meta["reason"] == "hit" and meta["extra"] == {"x": 1} and meta["context"] == {"mode": "EXPLORE"}


def test_cooldown_ring_off_switch_and_a_camera_that_fails(tmp_path, monkeypatch):
    t = [0.0]
    c = mk(tmp_path, clock=lambda: t[0], cap=2)
    assert c.capture("a") and not c.capture("b")                 # inside the cooldown
    t[0] = 10.0
    c._source = Cam()
    assert c.capture("c")
    assert len(list(tmp_path.glob("*.jpg"))) == 2                # the ring keeps the newest 2
    monkeypatch.setenv("G2_CONTACT_PICS", "0")
    assert not mk(tmp_path / "off").capture("x")
    monkeypatch.delenv("G2_CONTACT_PICS")
    broken = types.SimpleNamespace(snapshot=lambda settle=None: (_ for _ in ()).throw(RuntimeError("usb")))
    assert mk(tmp_path / "bad", broken).capture("x") is True      # never raises


def test_the_driver_asks_for_contact_pictures_and_the_binding_calls_the_camera_hook():
    asked = []
    b = DriverBindings(contact=lambda reason: asked.append(reason))
    assert b.dispatch([Effect(EffectKind.CAPTURE, ("contact", "hit"))]) == ["contact:hit"] and asked == ["hit"]
    assert DriverBindings().dispatch([Effect(EffectKind.CAPTURE, ("contact", "hit"))]) == ["drop:contact"]
