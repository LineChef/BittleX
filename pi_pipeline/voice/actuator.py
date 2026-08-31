"""The Actuator interface and its implementations.

`Actuator.perform(skill_name)` is the only thing the conversation loop calls to
make G2 move. On a dev machine that's `MockActuator` (logs what it would send);
on the robot it's `SerialActuator` (writes OpenCat commands to the BiBoard over
serial).
"""
from __future__ import annotations

import logging
import time
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
    """Sends OpenCat serial commands to the BiBoard.

    Not exercised until hardware is connected. `pyserial` is imported lazily so
    the dev machine doesn't need it.
    """

    def __init__(self, port: str, baud: int, settle_s: float = 0.05):
        import serial  # pyserial; add to requirements when hardware arrives

        self._settle_s = settle_s
        self._ser = serial.Serial(port, baud, timeout=1)
        time.sleep(2.0)  # BiBoard resets on serial open
        log.info("serial actuator on %s @ %d", port, baud)

    def _send(self, command: str) -> None:
        self._ser.write((command + "\n").encode("ascii"))
        self._ser.flush()
        time.sleep(self._settle_s)

    def perform(self, skill_name: str) -> None:
        if not skills.is_valid(skill_name):
            log.warning("unknown skill %r -- ignoring", skill_name)
            return
        cmd = skills.serial_command(skill_name)
        log.info("G2 perform %s -> %r", skill_name, cmd)
        self._send(cmd)

    def stop(self) -> None:
        self._send("d")  # OpenCat: rest / lie down, ends any looping gait

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass


def make_actuator(mode: str, *, port: str, baud: int) -> Actuator:
    if mode == "serial":
        return SerialActuator(port, baud)
    return MockActuator()
