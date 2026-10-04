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
    def perform(self, skill_name: str) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class MockActuator:
    """Logs the command instead of sending it. Default on a dev machine."""

    def perform(self, skill_name: str) -> None:
        if not skills.is_valid(skill_name):
            log.warning("unknown skill %r -- ignoring", skill_name)
            return
        cmd = skills.serial_command(skill_name)
        loop = " (continuous)" if skills.SKILLS[skill_name].continuous else ""
        log.info("[mock] G2 would perform %s -> serial %r%s", skill_name, cmd, loop)

    def stop(self) -> None:
        log.info("[mock] G2 would stop (serial 'd')")

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
    another skill or `stop()` arrives first.
    """

    def __init__(self, port: str, baud: int, *, link=None, max_continuous_s: float = 0.0):
        from ..link import opencat

        self._max_continuous_s = max_continuous_s
        self._cap_timer: threading.Timer | None = None

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

    def perform(self, skill_name: str) -> None:
        if not skills.is_valid(skill_name):
            log.warning("unknown skill %r -- ignoring", skill_name)
            return
        cmd = skills.serial_command(skill_name)
        log.info("G2 perform %s -> %r", skill_name, cmd)
        self._cancel_cap()
        self._link.send(cmd, read_reply=False)
        if self._max_continuous_s > 0 and skills.SKILLS[skill_name].continuous:
            self._cap_timer = threading.Timer(self._max_continuous_s, self._cap_expired, args=(skill_name,))
            self._cap_timer.daemon = True
            self._cap_timer.start()

    def _cancel_cap(self) -> None:
        if self._cap_timer is not None:
            self._cap_timer.cancel()
            self._cap_timer = None

    def _cap_expired(self, skill_name: str) -> None:
        log.warning("G2 %s hit the %.1fs gait cap -- stopping", skill_name, self._max_continuous_s)
        self._cap_timer = None
        self._link.send(self._opencat.REST, read_reply=False)

    def stop(self) -> None:
        self._cancel_cap()
        self._link.send(self._opencat.REST, read_reply=False)

    def close(self) -> None:
        self._cancel_cap()
        if self._owns_link:
            self._link.close()   # a shared link's lifecycle belongs to whoever built it


def make_actuator(mode: str, *, port: str, baud: int, link=None, max_continuous_s: float = 0.0) -> Actuator:
    if mode == "serial":
        return SerialActuator(port, baud, link=link, max_continuous_s=max_continuous_s)
    return MockActuator()
