"""The Actuator interface and its implementations.

`Actuator.perform(skill_name)` is the only thing the conversation loop calls to
make G2 move. On a dev machine that's `MockActuator` (logs what it would send);
on the robot it's `SerialActuator` (writes OpenCat commands to the BiBoard over
serial).
"""
from __future__ import annotations

import logging
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
    """

    def __init__(self, port: str, baud: int):
        from ..link import opencat
        from ..link.serial_link import SerialLink

        self._opencat = opencat
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
        self._link.send(cmd, read_reply=False)

    def stop(self) -> None:
        self._link.send(self._opencat.REST, read_reply=False)

    def close(self) -> None:
        self._link.close()


def make_actuator(mode: str, *, port: str, baud: int) -> Actuator:
    if mode == "serial":
        return SerialActuator(port, baud)
    return MockActuator()
