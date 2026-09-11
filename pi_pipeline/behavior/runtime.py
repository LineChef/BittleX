"""`BehaviorRuntime` -- the loop that actually runs `BehaviorDriver`.

`driver.py` decides, `bindings.py` acts, and this is the thing in the middle
that ticks the driver at a fixed rate and feeds it its inputs each tick:

  * **discrete events** -- pushed in by external producers (the voice loop, a
    mic-energy watcher, an IMU tap detector) via `post(**events)` and drained
    once per tick. Booleans OR together between ticks; `meet_name` is last-wins.
  * **the latest detection frame** -- from a `frame_source()` callable (wrap a
    `DetectionFeed` with `latest_frame_source`).
  * **continuous sensor state** -- from a `sensors()` callable returning a dict
    of `imu_level` / `imu_stable` / `held` / `person_present` / `recovering`.
  * **interaction recency** -- from a `recency()` callable (`Memory.recency`),
    for the mood model.

Nothing here is hardware-specific: pass a `MockBindings` + the defaults and the
whole loop runs on a dev machine (that's what `test_runtime.py` and
`python -m pi_pipeline.behavior` do). On the robot, pass a `DriverBindings`
wired to the real sinks and real sources -- the loop itself doesn't change.

This is the Phase 10 integration seam. It deliberately does NOT spawn threads or
own the voice loop: the voice loop stays a separate loop that just `post()`s
`wake_word` / `conversation_ended` / `say_hi` / ... events here, and the driver's
own CONVERSE handling keeps G2 attentive while a conversation runs.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .bindings import DriverBindings
from .driver import BehaviorDriver, DriverInputs, DriverTick

log = logging.getLogger("g2.behavior.runtime")

# the DriverInputs fields the event queue accepts (discrete, per-tick)
_EVENT_BOOLS = (
    "halt", "release", "ack",
    "wake_word", "conversation_ended", "told_stop", "told_stay", "told_sleep",
    "shutdown", "arm_explore", "disarm_explore",
    "rebuffed", "picked_up", "loud_sound", "imu_tap", "nearby_motion",
    "cancel_enroll", "say_hi",
)
# continuous sensor keys a `sensors()` callable may return
_SENSOR_KEYS = (
    "imu_level", "imu_stable", "held", "recovering", "person_present",
    "face_quality", "good_frames_this_step",
)


def latest_frame_source(feed):
    """Adapt a `DetectionFeed` (yields frames from `.frames()`) into a zero-arg
    `frame_source()` that returns the most recent frame, non-blocking."""
    it = feed.frames()
    last: list = []

    def _src():
        nonlocal last
        try:
            last = next(it)
        except StopIteration:
            pass
        return last

    return _src


def _default_sensors() -> dict:
    return {"imu_level": True, "imu_stable": True, "held": False,
            "recovering": False, "person_present": False}


@dataclass
class _Pending:
    """Discrete events accumulated since the last tick."""
    bools: dict = field(default_factory=dict)
    meet_name: str | None = None

    def merge(self, **events) -> None:
        for k, v in events.items():
            if k == "meet_name":
                if v:
                    self.meet_name = str(v)
            elif k in _EVENT_BOOLS:
                self.bools[k] = self.bools.get(k, False) or bool(v)
            else:
                raise KeyError(f"unknown runtime event {k!r}")

    def drain(self) -> dict:
        out = dict(self.bools)
        if self.meet_name is not None:
            out["meet_name"] = self.meet_name
        self.bools = {}
        self.meet_name = None
        return out


class BehaviorRuntime:
    def __init__(self, driver: BehaviorDriver, bindings: DriverBindings, *,
                 frame_source=None, sensors=None, recency=None, roster=None,
                 hz: float = 10.0, clock=time.monotonic, sleep=time.sleep):
        self.driver = driver
        self.bindings = bindings
        self._frame_source = frame_source or (lambda: [])
        self._sensors = sensors or _default_sensors
        self._recency = recency or (lambda: (None, 0))
        # bonded-person labels (from personality/bonds) -> the recognition hop
        self._roster = roster or (lambda: ())
        self._period = 1.0 / hz if hz > 0 else 0.0
        self._clock = clock
        self._sleep = sleep
        self._pending = _Pending()
        self._paused = False
        self._stop = False
        self.last_tick: DriverTick | None = None

    # -- external producers push events in here --------------------------------
    def post(self, **events) -> None:
        """Queue discrete events for the next tick. e.g.
        `rt.post(wake_word=True)`, `rt.post(meet_name="Sam")`."""
        self._pending.merge(**events)

    def pause(self) -> None:
        """Stop ticking (e.g. while the mic is mid-utterance and the serial link
        shouldn't be contended). Queued events survive until resume().
        An emergency `halt()` still gets through."""
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def halt(self) -> None:
        """EMERGENCY STOP -- freeze G2 now. Latches the driver's stop and
        immediately dispatches it, ignoring `pause`. Call `release()` to clear."""
        self.driver.estop.halt()
        try:
            self.bindings.dispatch(self.driver.tick(self._assemble(self._clock())))
        except Exception:  # noqa: BLE001 -- a halt must never raise
            log.exception("emergency halt dispatch failed")
        log.warning("EMERGENCY STOP -- behaviour runtime halted")

    def release(self) -> None:
        """Clear a latched emergency stop; normal behaviour resumes next tick."""
        self.driver.estop.release()
        log.warning("emergency stop released -- behaviour runtime resuming")

    def stop(self) -> None:
        self._stop = True

    # -- one control step ----------------------------------------------------
    def _assemble(self, now: float) -> DriverInputs:
        evt = self._pending.drain()
        sensors = {k: v for k, v in (self._sensors() or {}).items()
                   if k in _SENSOR_KEYS}
        age, n_recent = self._recency()
        return DriverInputs(
            now=now, frame=list(self._frame_source() or []),
            last_interaction_s=age, exchanges_recent=n_recent,
            known_person_labels=frozenset(self._roster() or ()),
            **sensors, **evt,
        )

    def tick(self, now: float | None = None) -> DriverTick | None:
        if self._paused and not self.driver.estop.halted:
            return None
        now = self._clock() if now is None else now
        i = self._assemble(now)
        t = self.driver.tick(i)
        self.bindings.dispatch(t)
        self.last_tick = t
        return t

    def run_forever(self, *, max_ticks: int | None = None) -> None:
        """Tick at `hz` until `stop()`. `max_ticks` bounds it for tests / demos."""
        self._stop = False
        n = 0
        log.info("behavior runtime up (%.1f Hz)", 1.0 / self._period if self._period else 0.0)
        while not self._stop and (max_ticks is None or n < max_ticks):
            self.tick()
            n += 1
            if self._period:
                self._sleep(self._period)
        log.info("behavior runtime stopped after %d ticks", n)
