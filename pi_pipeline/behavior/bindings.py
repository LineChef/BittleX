"""The binding layer -- maps `BehaviorDriver` `Effect`s onto real sinks.

`BehaviorDriver.tick()` returns abstract `Effect`s and touches no I/O. This is
the piece that actually does something with them on the robot:

  SKILL   -> actuator.perform(token)
  STOP    -> actuator.stop()
  WALK    -> walker.walk(turn_bias)          (falls back to actuator.walk)
  TURN    -> walker.turn(rad)                (falls back to a firmware turn token)
  HEAD    -> head.move(arg)
  SPEAK   -> tts.speak(text)                 (or tts.say)
  CAPTURE -> camera.set_capture(on, kind)
  CUE     -> cue.set(stage)
  CHIRP   -> actuator.perform(opencat.beep(...))  -- the buzzer melody for a mood
  POWER   -> power.set_profile(name)         (or power.profile / power.apply)
  DIAG    -> on_diag(name, reason)           (default: pi_pipeline.diag.event)

Every sink is optional. A missing sink means that effect kind is dropped and
logged once. `MockBindings` records every call so the whole driver loop can be
exercised end-to-end against a fake clock (see test_bindings.py).
"""
from __future__ import annotations

import logging

from ..link import opencat
from .chirps import CHIRP, ChirpMood
from .driver import DriverTick, Effect, EffectKind

log = logging.getLogger("g2.behavior.bindings")


def _call(obj, *names):
    """Return the first bound method found on obj from `names`, or None."""
    for n in names:
        m = getattr(obj, n, None)
        if callable(m):
            return m
    return None


class DriverBindings:
    def __init__(self, *, actuator=None, tts=None, camera=None, cue=None,
                 walker=None, head=None, power=None, on_diag=None):
        self.actuator = actuator
        self.tts = tts
        self.camera = camera
        self.cue = cue
        self.walker = walker
        self.head = head
        self.power = power
        self._on_diag = on_diag or _default_diag
        self._warned: set[str] = set()

    # -- routing ---------------------------------------------------------------
    def dispatch(self, tick_or_effects) -> list[str]:
        effects = (tick_or_effects.effects if isinstance(tick_or_effects, DriverTick)
                   else list(tick_or_effects))
        return [self._one(e) for e in effects]

    def _miss(self, kind: str) -> str:
        if kind not in self._warned:
            self._warned.add(kind)
            log.warning("no sink for Effect %s -- dropping", kind)
        return f"drop:{kind}"

    def _one(self, e: Effect) -> str:
        k = e.kind
        if k is EffectKind.SKILL:
            fn = self.actuator and _call(self.actuator, "perform")
            if not fn:
                return self._miss("skill")
            fn(e.payload)
            return f"skill:{e.payload}"
        if k is EffectKind.STOP:
            fn = self.actuator and _call(self.actuator, "stop")
            if not fn:
                return self._miss("stop")
            fn()
            return "stop"
        if k is EffectKind.WALK:
            fn = (self.walker and _call(self.walker, "walk")) \
                or (self.actuator and _call(self.actuator, "walk"))
            if not fn:
                return self._miss("walk")
            fn(float(e.payload or 0.0))
            return f"walk:{float(e.payload or 0.0):+.2f}"
        if k is EffectKind.TURN:
            rad = float(e.payload or 0.0)
            fn = (self.walker and _call(self.walker, "turn"))
            if fn:
                fn(rad)
                return f"turn:{rad:+.2f}"
            fn = self.actuator and _call(self.actuator, "perform")
            if not fn:
                return self._miss("turn")
            fn(opencat.WALK_RIGHT if rad >= 0 else opencat.WALK_LEFT)
            return f"turn_token:{'R' if rad >= 0 else 'L'}"
        if k is EffectKind.HEAD:
            fn = self.head and _call(self.head, "move", "set", "head")
            if not fn:
                return self._miss("head")
            fn(e.payload)
            return f"head:{e.payload}"
        if k is EffectKind.SPEAK:
            fn = self.tts and _call(self.tts, "speak", "say")
            if not fn:
                return self._miss("speak")
            fn(str(e.payload))
            return f"speak:{e.payload}"
        if k is EffectKind.CAPTURE:
            on, kind = (e.payload if isinstance(e.payload, (tuple, list)) else (e.payload, None))
            fn = self.camera and _call(self.camera, "set_capture", "capture")
            if not fn:
                return self._miss("capture")
            fn(on == "on" or on is True, kind)
            return f"capture:{on}/{kind}"
        if k is EffectKind.CUE:
            fn = self.cue and _call(self.cue, "set")
            if not fn:
                return self._miss("cue")
            fn(e.payload)
            return f"cue:{e.payload}"
        if k is EffectKind.CHIRP:
            mood = e.payload if isinstance(e.payload, ChirpMood) else ChirpMood(e.payload)
            fn = self.actuator and _call(self.actuator, "perform")
            if not fn:
                return self._miss("chirp")
            fn(opencat.beep(CHIRP[mood]))
            return f"chirp:{mood.value}"
        if k is EffectKind.POWER:
            fn = self.power and _call(self.power, "set_profile", "profile", "apply")
            if not fn:
                return self._miss("power")
            fn(str(e.payload))
            return f"power:{e.payload}"
        if k is EffectKind.DIAG:
            name, reason = (e.payload if isinstance(e.payload, (tuple, list)) else (e.payload, e.reason))
            self._on_diag(name, reason)
            return f"diag:{name}"
        return self._miss(str(k))


def _default_diag(name, reason) -> None:
    try:
        from ..diag import event
        event("behavior", "INFO", str(name), reason=str(reason))
    except Exception:
        pass


# ---------------------------------------------------------------- test double
class _Recorder:
    def __init__(self, calls, prefix):
        self._calls, self._p = calls, prefix

    def __getattr__(self, name):
        def _rec(*a, **kw):
            self._calls.append((f"{self._p}.{name}", a, kw))
        return _rec


class MockBindings(DriverBindings):
    """DriverBindings wired to recording stubs. `self.calls` is the ordered list
    of (dotted_name, args, kwargs) -- assert against it in a full-loop test."""

    def __init__(self):
        self.calls: list[tuple] = []
        super().__init__(
            actuator=_Recorder(self.calls, "actuator"),
            tts=_Recorder(self.calls, "tts"),
            camera=_Recorder(self.calls, "camera"),
            cue=_Recorder(self.calls, "cue"),
            walker=_Recorder(self.calls, "walker"),
            head=_Recorder(self.calls, "head"),
            power=_Recorder(self.calls, "power"),
            on_diag=lambda n, r: self.calls.append(("diag", (n, r), {})),
        )

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]
