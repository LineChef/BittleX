"""A resilient serial connection to the BiBoard.

`SerialLink` does not open the port in `__init__` -- call `connect()`. On a write
or read error it marks itself disconnected and, if `auto_reconnect`, retries the
open on the next `send()`. This keeps a dropped USB/serial cable from crashing
the voice loop. `pyserial` is imported lazily so the dev machine doesn't need it.
"""
from __future__ import annotations

import logging
import time

log = logging.getLogger("g2.link")


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
            self._ser = serial.Serial(self._port, self._baud, timeout=self._read_timeout)
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
                return self._ser.readline().decode("utf-8", "replace").strip()
            return ""
        except Exception as e:  # noqa: BLE001
            log.warning("serial send failed (%s); marking disconnected", e)
            self.close()
            self._mark_down(f"send failed: {e}")
            return ""

    def read_line(self) -> str:
        """Read one line the board sent unsolicited (e.g. a frame of the `V` IMU
        stream). Non-blocking-ish: returns '' if nothing is ready within the
        port's read_timeout. Does not write anything."""
        if not self.is_connected:
            return ""
        try:
            return self._ser.readline().decode("utf-8", "replace").strip()
        except Exception as e:  # noqa: BLE001
            log.warning("serial read failed (%s); marking disconnected", e)
            self.close()
            self._mark_down(f"read failed: {e}")
            return ""

    def drain(self, seconds: float = 0.3) -> str:
        """Read whatever the board has queued for up to `seconds`."""
        if not self.is_connected:
            return ""
        out, end = [], time.monotonic() + seconds
        try:
            while time.monotonic() < end:
                line = self._ser.readline().decode("utf-8", "replace").strip()
                if line:
                    out.append(line)
        except Exception:  # noqa: BLE001
            pass
        return "\n".join(out)

    @staticmethod
    def list_ports() -> list[tuple[str, str]]:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        return [(p.device, p.description) for p in list_ports.comports()]
