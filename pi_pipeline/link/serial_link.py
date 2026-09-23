"""A resilient serial connection to the BiBoard.

`SerialLink` does not open the port in `__init__` -- call `connect()`. On a write
or read error it marks itself disconnected and, if `auto_reconnect`, retries the
open on the next `send()`. This keeps a dropped USB/serial cable from crashing
the voice loop. `pyserial` is imported lazily so the dev machine doesn't need it.
"""
from __future__ import annotations

import collections
import logging
import time

log = logging.getLogger("g2.link")

# Line prefixes of the firmware's continuous IMU stream (`gP` -> `imu.h`
# `print6Axis()`). Kept identical to gait/imu_parse.py's prefixes -- a test
# asserts they match.
IMU_PREFIXES = ("MCU:", "ICM:")


def is_imu_line(line: str) -> bool:
    return line.lstrip().startswith(IMU_PREFIXES)


class SerialLink:
    def __init__(
        self,
        port: str,
        baud: int = 115200,
        *,
        reset_wait: float = 2.0,   # BiBoard reboots when the port opens
        read_timeout: float = 1.0,
        auto_reconnect: bool = True,
    ):
        self._port = port
        self._baud = baud
        self._reset_wait = reset_wait
        self._read_timeout = read_timeout
        self._auto_reconnect = auto_reconnect
        self._ser = None
        self._down_since: float | None = None   # when the link last dropped
        self._was_connected = False
        # IMU stream demux: with `gP` on, the board interleaves IMU frames with
        # command replies. Every read path routes IMU lines here instead of
        # handing them back as a reply; `poll_imu()` collects them.
        self._rx = b""
        self._imu = collections.deque(maxlen=64)

    @staticmethod
    def _diag(level: str, name: str, **kv) -> None:
        """Emit a named diagnostics event; never raises if diag isn't set up."""
        try:
            from ..diag import diag
            diag.event("link", level, name, **kv)
        except Exception:  # noqa: BLE001
            pass

    def _mark_down(self, why: str) -> None:
        if self._down_since is None:
            self._down_since = time.monotonic()
            self._diag("WARN", "link.lost", why=why, port=self._port)

    def _mark_up(self) -> None:
        if self._down_since is not None:
            self._diag("INFO", "link.reconnect", port=self._port,
                       gap_s=round(time.monotonic() - self._down_since, 2))
        self._down_since = None

    # --- connection ---------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._ser is not None and getattr(self._ser, "is_open", False)

    def connect(self) -> bool:
        if self.is_connected:
            return True
        try:
            import serial  # pyserial
        except ImportError:
            log.error("pyserial not installed -- `pip install pyserial`")
            return False
        try:
            # short port timeout: blocking reads loop against their own deadlines
            # (read_timeout) instead of stalling a whole second per read
            self._ser = serial.Serial(self._port, self._baud, timeout=0.02)
        except Exception as e:  # noqa: BLE001 -- serial.SerialException + OSError
            log.warning("serial open %s failed: %s", self._port, e)
            self._ser = None
            self._mark_down(f"open failed: {e}")
            return False
        time.sleep(self._reset_wait)
        try:
            self._ser.reset_input_buffer()
        except Exception:  # noqa: BLE001
            pass
        self._rx = b""
        log.info("serial connected: %s @ %d", self._port, self._baud)
        if self._was_connected:
            self._mark_up()
        self._was_connected = True
        return True

    def close(self) -> None:
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass
            self._ser = None

    # --- messaging --------------------------------------------------------

    def send(self, command: str, *, read_reply: bool = True, settle: float = 0.05) -> str:
        """Write `command` (a newline is added). Optionally read one reply line.
        Returns the reply (or '' ). Raises nothing -- logs and returns '' on error."""
        if not self.is_connected and not (self._auto_reconnect and self.connect()):
            log.debug("send(%r) dropped -- not connected", command)
            return ""
        try:
            self._ser.write((command + "\n").encode("ascii", "ignore"))
            self._ser.flush()
            if settle:
                time.sleep(settle)
            if read_reply:
                return self._read_reply(time.monotonic() + self._read_timeout)
            return ""
        except Exception as e:  # noqa: BLE001
            log.warning("serial send failed (%s); marking disconnected", e)
            self.close()
            self._mark_down(f"send failed: {e}")
            return ""

    def read_line(self) -> str:
        """Read one non-IMU line the board sent (a reply, a banner). Waits up to
        the port's read_timeout; returns '' if nothing arrives. IMU stream
        frames are routed to `poll_imu()`, never returned here. Does not write
        anything."""
        if not self.is_connected:
            return ""
        try:
            return self._read_reply(time.monotonic() + self._read_timeout)
        except Exception as e:  # noqa: BLE001
            log.warning("serial read failed (%s); marking disconnected", e)
            self.close()
            self._mark_down(f"read failed: {e}")
            return ""

    def poll_imu(self) -> list[str]:
        """Non-blocking: every IMU stream line received since the last call,
        oldest first. Reads only what is already buffered, so it is safe to
        call every control tick. Non-IMU lines found on the way (e.g. the
        token echo after each move command) are dropped -- nothing is waiting
        on them."""
        if self.is_connected:
            try:
                while True:
                    line = self._next_line(block_until=None)
                    if line is None:
                        break
                    if line:
                        log.debug("poll_imu dropped non-IMU line %r", line)
            except Exception as e:  # noqa: BLE001
                log.warning("serial read failed (%s); marking disconnected", e)
                self.close()
                self._mark_down(f"read failed: {e}")
        out = list(self._imu)
        self._imu.clear()
        return out

    def drain(self, seconds: float = 0.3) -> str:
        """Read whatever non-IMU lines the board has queued for up to `seconds`."""
        if not self.is_connected:
            return ""
        out, end = [], time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                line = self._read_reply(end)
                if line:
                    out.append(line)
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(out)

    # --- line assembly --------------------------------------------------------

    def _read_reply(self, deadline: float) -> str:
        """First non-IMU line before `deadline`, or ''."""
        while True:
            line = self._next_line(block_until=deadline)
            if line is None:
                return ""
            if line:
                return line

    def _next_line(self, block_until: float | None) -> str | None:
        """Next complete line with IMU frames routed to the IMU buffer (returned
        as ''), or None if no complete line is available -- immediately when
        `block_until` is None, else once that monotonic deadline passes."""
        while b"\n" not in self._rx:
            waiting = self._ser.in_waiting
            if waiting:
                self._rx += self._ser.read(waiting)
                continue
            if block_until is None or time.monotonic() >= block_until:
                return None
            chunk = self._ser.read(1)          # blocks up to the 20 ms port timeout
            if chunk:
                self._rx += chunk
        raw, self._rx = self._rx.split(b"\n", 1)
        line = raw.decode("utf-8", "replace").strip()
        if is_imu_line(line):
            self._imu.append(line)
            return ""
        return line

    @staticmethod
    def list_ports() -> list[tuple[str, str]]:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        return [(p.device, p.description) for p in list_ports.comports()]
