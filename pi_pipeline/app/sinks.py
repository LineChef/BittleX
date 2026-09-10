"""Real `DriverBindings` sinks -- serial + power backed.

`BehaviorDriver` emits abstract effects; `DriverBindings` routes each to a sink.
On a dev machine those sinks are `MockBindings`' recorders. On the robot they are
the classes below, wired by `build_bindings()`.

Every sink degrades safely: a down serial link logs and drops (the `SerialLink`
already reconnects on its own), and `dry_run` power calls don't touch the Pi.
"""
from __future__ import annotations

import logging
import threading

from ..behavior.bindings import DriverBindings
from ..link import opencat

log = logging.getLogger("g2.app.sinks")

# Bittle's head pan servo is joint 0 (no tilt DOF). Pan range is roughly ±45°.
_HEAD_IDX = 0
_HEAD_PAN_DEG = 45.0


class LockedLink:
    """Serialises access to a `SerialLink` shared by the voice loop and the
    behaviour runtime (they run on separate threads). Pass-through otherwise."""

    def __init__(self, link):
        self._link = link
        self._lock = threading.Lock()

    def send(self, command: str, **kw) -> str:
        with self._lock:
            return self._link.send(command, **kw)

    def read_line(self) -> str:
        with self._lock:
            return self._link.read_line()

    @property
    def is_connected(self) -> bool:
        return getattr(self._link, "is_connected", False)

    def close(self) -> None:
        with self._lock:
            self._link.close()


class SerialActuatorSink:
    """SKILL / STOP / CHIRP -> raw OpenCat serial. Accepts any *safe* command
    string (a `k<skill>` token, `d`, an `m0 <deg>` head move, a `b<tone>…`
    chirp); calibration / factory commands are refused by `opencat.is_safe`."""

    def __init__(self, link):
        self._link = link

    def perform(self, command: str) -> None:
        cmd = str(command).strip()
        if not cmd:
            return
        if not opencat.is_safe(cmd):
            log.warning("refusing unsafe serial command %r", cmd)
            return
        self._link.send(cmd, read_reply=False)

    def stop(self) -> None:
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
    `turn(rad)` uses the curved-walk L/R tokens."""

    def __init__(self, link, *, turn_threshold: float = 0.15):
        self._link = link
        self._thr = turn_threshold
        self._last = ""

    def _send_once(self, token: str) -> None:
        if token != self._last:            # firmware gaits are continuous
            self._link.send(token, read_reply=False)
            self._last = token

    def walk(self, bias: float = 0.0) -> None:
        if bias >= self._thr:
            self._send_once(opencat.WALK_RIGHT)
        elif bias <= -self._thr:
            self._send_once(opencat.WALK_LEFT)
        else:
            self._send_once(opencat.skill("wkF"))

    def turn(self, rad: float) -> None:
        self._send_once(opencat.WALK_RIGHT if float(rad) >= 0 else opencat.WALK_LEFT)

    def stop(self) -> None:
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

    def __init__(self, on_toggle=None):
        self._on_toggle = on_toggle
        self.capturing = False

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
                   camera_toggle=None) -> DriverBindings:
    """Wire a `DriverBindings` to the real sinks. `link` is a `SerialLink` /
    `LockedLink` (or None -> serial sinks become no-ops via a null link)."""
    link = link or _NullLink()
    act = SerialActuatorSink(link)
    return DriverBindings(
        actuator=act,
        tts=None,                       # the voice loop owns TTS; SPEAK effects are rare here
        camera=CameraSink(camera_toggle),
        cue=None,
        walker=WalkerSink(link),
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
