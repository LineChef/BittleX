"""The Actuator interface and its implementations.

`Actuator.perform(skill_name)` is the only thing the conversation loop calls to
make G2 move. On a dev machine that's `MockActuator` (logs what it would send);
on the robot it's `SerialActuator` (writes OpenCat commands to the BiBoard over
serial).
"""
from __future__ import annotations

import logging
import threading
from typing import Protocol

from . import skills

log = logging.getLogger("g2.actuator")


class Actuator(Protocol):
    def perform(self, skill_name: str, seconds: float | None = None) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class MockActuator:
    """Logs the command instead of sending it. Default on a dev machine."""

    def perform(self, skill_name: str, seconds: float | None = None) -> None:
        if not skills.is_valid(skill_name):
            log.warning("unknown skill %r -- ignoring", skill_name)
            return
        cmd = skills.serial_command(skill_name)
        loop = " (continuous)" if skills.SKILLS[skill_name].continuous else ""
        for_s = f" for {skills.clamp_seconds(seconds):.1f}s" if (seconds and loop and skills.clamp_seconds(seconds)) else ""
        log.info("[mock] G2 would perform %s -> serial %r%s%s", skill_name, cmd, loop, for_s)

    def stop(self) -> None:
        log.info("[mock] G2 would stop (serial 'd')")

    def send_token(self, token: str) -> None:
        log.info("[mock] G2 would send %r", token)

    def read_voltage(self) -> float | None:
        return None                      # no robot, no battery

    def close(self) -> None:  # nothing to release
        pass


class SerialActuator:
    """Sends OpenCat skill commands to the BiBoard over a resilient SerialLink.

    The link opens lazily and reconnects on drop, so a yanked cable logs a
    warning instead of crashing the loop. Not exercised until hardware is
    connected (needs pyserial).

    Pass an existing `link` (e.g. `pi_pipeline.app`'s shared `LockedLink`) to
    reuse one connection across callers instead of opening a second one on the
    same port; omit it to open a private `SerialLink` as before.

    `max_continuous_s` (default off) bounds a looping gait: after a continuous
    skill starts, a timer sends the stop command that many seconds later unless
    another skill or `stop()` arrives first. A per-call `seconds` (from Claude's
    `perform_skill`) sets a shorter or longer walk, but never beyond this cap
    when it is on, and never beyond `skills.MAX_GAIT_SECONDS`.
    """

    def __init__(self, port: str, baud: int, *, link=None, max_continuous_s: float = 0.0):
        from ..link import opencat

        self._max_continuous_s = max_continuous_s
        self._cap_timer: threading.Timer | None = None
        self._gait_active = False     # a looping gait was started and not yet stopped

        self._opencat = opencat
        self._owns_link = link is None   # only close a link we opened ourselves
        if link is not None:
            self._link = link
            return
        from ..link.serial_link import SerialLink
        self._link = SerialLink(port, baud)
        if self._link.connect():
            log.info("serial actuator connected on %s @ %d", port, baud)
        else:
            log.warning("serial actuator: %s not open yet (will retry on send)", port)

    def perform(self, skill_name: str, seconds: float | None = None) -> None:
        if not skills.is_valid(skill_name):
            log.warning("unknown skill %r -- ignoring", skill_name)
            return
        cmd = skills.serial_command(skill_name)
        log.info("G2 perform %s -> %r", skill_name, cmd)
        self._cancel_cap()
        self._link.send(cmd, read_reply=False)
        self._gait_active = skills.SKILLS[skill_name].continuous
        if skills.SKILLS[skill_name].continuous:
            # a requested duration bounds the walk; if a standing cap is set it is a hard ceiling on top
            duration = skills.clamp_seconds(seconds)
            if self._max_continuous_s > 0:
                duration = min(duration, self._max_continuous_s) if duration else self._max_continuous_s
            if duration:
                self._cap_timer = threading.Timer(duration, self._cap_expired, args=(skill_name, duration))
                self._cap_timer.daemon = True
                self._cap_timer.start()

    def _cancel_cap(self) -> None:
        if self._cap_timer is not None:
            self._cap_timer.cancel()
            self._cap_timer = None

    def _cap_expired(self, skill_name: str, duration: float) -> None:
        log.warning("G2 %s ran its %.1fs -- stopping", skill_name, duration)
        self._cap_timer = None
        self._gait_active = False
        self._link.send(self._opencat.REST, read_reply=False)

    def stop(self) -> None:
        self._cancel_cap()
        self._gait_active = False
        self._link.send(self._opencat.REST, read_reply=False)

    def send_token(self, token: str) -> None:
        """Send one raw OpenCat token (used for buzzer cues). Skipped while a looping gait is
        running: whether a non-skill token interrupts the gait has not been checked on the robot."""
        if self._gait_active:
            log.debug("skipping %r while a gait is running", token)
            return
        self._link.send(token, read_reply=False)

    def read_voltage(self) -> float | None:
        """Battery volts via the firmware's `P` command, or None while a gait is running (the reading sags under load, and the
        serial line is busy)."""
        if self._gait_active:
            return None
        from ..power.battery import read_voltage
        return read_voltage(self._link)

    def close(self) -> None:
        self._cancel_cap()
        if self._owns_link:
            self._link.close()   # a shared link's lifecycle belongs to whoever built it


def make_actuator(mode: str, *, port: str, baud: int, link=None,
                  max_continuous_s: float | None = None) -> Actuator:
    if mode == "serial":
        if max_continuous_s is None:           # not given: use the G2_MAX_GAIT_S setting (default off)
            from ..config import settings
            max_continuous_s = settings.max_gait_s
        return SerialActuator(port, baud, link=link, max_continuous_s=max_continuous_s)
    return MockActuator()
