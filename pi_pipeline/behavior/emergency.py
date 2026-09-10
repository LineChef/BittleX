"""Emergency stop -- the manual override that freezes G2 immediately.

This is the human "STOP" for when G2 is about to do something dangerous (walk
off a ledge, jam a leg, anything you need to halt *now*). It is deliberately
separate from:

  * `told_stop` -- transient: rouses from rest, stops roaming for a beat, then
    normal behaviour resumes.
  * `CliffGuard` / the safety reflexes -- automatic, sensor-driven, and only as
    good as the (not-yet-trained) edge model.

`EmergencyStop` is **latching**: once `halt()` is called G2 stays frozen and the
behaviour driver emits nothing but a stop + a single hold command until
`release()` is called. It sits at the very top of `BehaviorDriver.tick()`, above
enrollment / sleep / safety / mode -- nothing outranks it. `BehaviorRuntime`
also short-circuits to it, so no autonomous decision is even computed while
halted.

The hold command (`freeze_token`) defaults to `kbalance` -- settle into a
balanced stand, the least body translation. Set it to `ksit` (lower CoM) or `d`
(lie down + relax) once real behaviour on the robot says which is safest at an
edge.
"""
from __future__ import annotations

from .chirps import ChirpMood


class EmergencyStop:
    def __init__(self, *, freeze_token: str = "kbalance"):
        self.freeze_token = freeze_token
        self._halted = False
        self._announced = False   # emitted the entry burst for this latch yet?

    @property
    def halted(self) -> bool:
        return self._halted

    def halt(self) -> bool:
        """Latch the stop. Returns True if this call is what triggered it."""
        newly = not self._halted
        self._halted = True
        if newly:
            self._announced = False
        return newly

    def release(self) -> bool:
        """Clear the latch. Returns True if it had been halted."""
        was = self._halted
        self._halted = False
        self._announced = False
        return was

    def effects(self, reason: str = "emergency stop") -> list:
        """The effect list for a halted tick. First call after a `halt()` emits
        the entry burst (diag + alert chirp + stop + hold); later calls just
        re-assert the stop so nothing downstream drifts."""
        from .driver import Effect, EffectKind   # lazy: driver imports us
        if not self._announced:
            self._announced = True
            return [
                Effect(EffectKind.DIAG, ("safety", "emergency_halt"), reason),
                Effect(EffectKind.CHIRP, ChirpMood.ALERT, "emergency stop"),
                Effect(EffectKind.STOP, None, "emergency: halt locomotion"),
                Effect(EffectKind.SKILL, self.freeze_token, "emergency: hold stance"),
            ]
        return [Effect(EffectKind.STOP, None, "emergency: held")]
