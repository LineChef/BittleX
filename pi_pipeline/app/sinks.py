"""Real `DriverBindings` sinks -- serial + power backed.

`BehaviorDriver` emits abstract effects; `DriverBindings` routes each to a sink.
On a dev machine those sinks are `MockBindings`' recorders. On the robot they are
the classes below, wired by `build_bindings()`.

Every sink degrades safely: a down serial link logs and drops (the `SerialLink`
already reconnects on its own), and `dry_run` power calls don't touch the Pi.
"""
from __future__ import annotations

import logging
import math
import threading
import time

from ..behavior.bindings import DriverBindings
from ..link import opencat

log = logging.getLogger("g2.app.sinks")

# Bittle's head pan servo is joint 0 (no tilt DOF). Pan range is roughly ±45°.
_HEAD_IDX = 0
_HEAD_PAN_DEG = 45.0


from ..link.locked import LockedLink  # noqa: E402,F401 -- moved to link/locked.py so the voice service can share it


class SerialActuatorSink:
    """SKILL / STOP / CHIRP -> raw OpenCat serial. Accepts any *safe* command
    string (a `k<skill>` token, `d`, an `m0 <deg>` head move, a `b<tone>…`
    chirp); calibration / factory commands are refused by `opencat.is_safe`."""

    def __init__(self, link, *, policy_walker=None):
        self._link = link
        self._policy = policy_walker

    def perform(self, command: str) -> None:
        cmd = str(command).strip()
        if not cmd:
            return
        if not opencat.is_safe(cmd):
            log.warning("refusing unsafe serial command %r", cmd)
            return
        if self._policy is not None and self._policy.busy and cmd[0] in ("k", "d"):
            self._policy.stop(rest=False)            # a skill replaces a running learned walk (chirps and head moves do not)
        self._link.send(cmd, read_reply=False)

    def stop(self) -> None:
        if self._policy is not None:
            self._policy.stop(rest=True)
        self._link.send(opencat.REST, read_reply=False)


class HeadSink:
    """HEAD effect -> head-pan serial. Payload is "center" | "up" | "pan_sweep"
    | a float bearing in radians (+ = right)."""

    def __init__(self, link, *, pan_deg: float = _HEAD_PAN_DEG):
        self._link = link
        self._pan = pan_deg

    def _m(self, deg: float) -> None:
        deg = max(-self._pan, min(self._pan, float(deg)))
        self._link.send(opencat.move_joints([(_HEAD_IDX, int(round(deg)))]),
                        read_reply=False)

    def move(self, arg) -> None:
        if arg in ("center", "up", "down", None):
            self._m(0.0)
        elif arg == "pan_sweep":
            for d in (-self._pan * 0.8, self._pan * 0.8, 0.0):
                self._m(d)
        else:
            try:
                import math
                self._m(math.degrees(float(arg)))
            except (TypeError, ValueError):
                log.debug("HEAD: ignoring unknown payload %r", arg)


class WalkerSink:
    """WALK / TURN -> firmware walk gaits (the bring-up default; the RL gait
    loop is `gait/run_gait.py`, run separately). `walk(bias)` goes forward;
    `turn(rad)` is a TIMED firmware curved walk: the L/R token turns G2 only while it runs, so it runs for as long as the angle needs at G2's measured firmware turn
    rates (left about 11 deg/s, right about 18 deg/s, 2026-10-06) and `walk()` leaves it alone until it ends (2026-10-07: the old turn lasted one tick, the next WANDER tick
    handed the walk back to the straight policy, so "heading off in a new direction" never changed direction)."""

    TURN_RATE_DPS = {"left": 11.0, "right": 18.0}     # measured yaw rates of the firmware wkL / wkR gaits on G2
    TURN_GAIN = 0.85                                  # turn a bit less than asked: the heading hold and the next bearing check finish the job
    TURN_MIN_RAD = 0.12                               # a smaller turn is not worth a gait change
    TURN_MAX_S = 6.0

    def __init__(self, link, *, turn_threshold: float = 0.15, policy_walker=None, clock=time.monotonic):
        self._link = link
        self._thr = turn_threshold
        self._last = ""
        self._policy = policy_walker         # straight-ahead walking uses the learned policy when given; turns stay firmware tokens
        self._clock = clock
        self._turn_until = 0.0               # a timed turn is running until this time

    def _send_once(self, token: str) -> None:
        if token != self._last:            # firmware gaits are continuous
            self._link.send(token, read_reply=False)
            self._last = token

    def _firmware(self) -> None:
        if self._policy is not None and self._policy.busy:
            self._policy.stop(rest=False)       # hand over to a firmware gait without lying down in between
            self._last = ""

    def turning(self) -> bool:
        return self._clock() < self._turn_until

    def walk(self, bias: float = 0.0) -> None:
        if self.turning():
            return                              # a timed turn is running: let it finish before walking on
        if self._turn_until:                    # it just ended: the next command (re)starts cleanly
            self._turn_until, self._last = 0.0, ""
        if self._policy is not None and -self._thr < bias < self._thr:
            if not self._policy.busy:
                self._last = ""
                self._policy.walk(None)
            return
        self._firmware()
        if bias >= self._thr:
            self._send_once(opencat.WALK_RIGHT)
        elif bias <= -self._thr:
            self._send_once(opencat.WALK_LEFT)
        else:
            self._send_once(opencat.skill("wkF"))

    def turn(self, rad: float) -> None:
        r = float(rad)
        if abs(r) < self.TURN_MIN_RAD or self.turning():
            return                              # too small to bother, or a turn is already running
        side = "right" if r >= 0 else "left"
        dur = min(self.TURN_MAX_S, math.degrees(abs(r)) * self.TURN_GAIN / self.TURN_RATE_DPS[side])
        self._firmware()
        self._last = ""
        self._send_once(opencat.WALK_RIGHT if r >= 0 else opencat.WALK_LEFT)
        self._turn_until = self._clock() + dur
        log.info("timed turn %s %.0f deg for %.1f s", side, math.degrees(abs(r)), dur)

    def stop(self) -> None:
        self._turn_until = 0.0
        if self._policy is not None:
            self._policy.stop(rest=True)
        self._link.send(opencat.REST, read_reply=False)
        self._last = ""


class PowerSink:
    """POWER effect -> `pi_pipeline.power` profile. "headless" = power-save for
    autonomous ops, "interactive" = full power."""

    def __init__(self, *, dry_run: bool | None = None):
        self._dry = dry_run

    def set_profile(self, name: str) -> None:
        from .. import power
        if name == "headless":
            power.apply_headless_profile(self._dry)
        elif name == "interactive":
            power.apply_interactive_profile(self._dry)
        else:
            log.warning("POWER: unknown profile %r", name)


class CameraSink:
    """CAPTURE effect -> start/stop frame capture and (on sleep) camera power.
    The vision module's own power line is hardware-specific, so this records the
    intent and calls an injected `on_toggle(on: bool, kind)` hook if given."""

    def __init__(self, on_toggle=None, snap=None):
        self._on_toggle = on_toggle
        self._snap = snap                    # injected: takes and saves one picture, snap(kind) (vision/exploration_pictures.py)
        self.capturing = False

    def snapshot(self, kind=None) -> None:
        log.info("camera snapshot (%s)", kind)
        if self._snap:
            try:
                self._snap(kind)
            except Exception:  # noqa: BLE001
                log.exception("camera snapshot hook failed")

    def set_capture(self, on: bool, kind=None) -> None:
        self.capturing = bool(on)
        log.info("camera capture %s%s", "on" if on else "off",
                 f" ({kind})" if kind else "")
        if self._on_toggle:
            try:
                self._on_toggle(bool(on), kind)
            except Exception:  # noqa: BLE001
                log.exception("camera on_toggle hook failed")


def build_bindings(link, *, dry_run_power: bool | None = None,
                   camera_toggle=None, policy_walker=None, camera_snapshot=None) -> DriverBindings:
    """Wire a `DriverBindings` to the real sinks. `link` is a `SerialLink` /
    `LockedLink` (or None -> serial sinks become no-ops via a null link)."""
    link = link or _NullLink()
    act = SerialActuatorSink(link, policy_walker=policy_walker)
    return DriverBindings(
        actuator=act,
        tts=None,                       # the voice loop owns TTS; SPEAK effects are rare here
        camera=CameraSink(camera_toggle, camera_snapshot),
        cue=None,
        walker=WalkerSink(link, policy_walker=policy_walker),
        head=HeadSink(link),
        power=PowerSink(dry_run=dry_run_power),
        on_diag=_diag_event,
    )


class _NullLink:
    is_connected = False

    def send(self, *_a, **_k) -> str:
        return ""

    def read_line(self) -> str:
        return ""

    def poll_imu(self) -> list:
        return []

    def close(self) -> None:
        pass


def _diag_event(name, reason) -> None:
    try:
        from ..diag import event
        sub = name[0] if isinstance(name, (tuple, list)) else "behavior"
        nm = name[1] if isinstance(name, (tuple, list)) and len(name) > 1 else str(name)
        event(str(sub), "INFO", str(nm), reason=str(reason))
    except Exception:  # noqa: BLE001
        pass
