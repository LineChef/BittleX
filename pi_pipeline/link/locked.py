"""One serial link shared by several threads (the voice loop, the behaviour runtime, background watchers)."""
from __future__ import annotations

import threading


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

    def drain(self, seconds: float = 0.3) -> str:
        with self._lock:
            return self._link.drain(seconds)

    def poll_imu(self) -> list:
        """Non-blocking, so holding the lock here never delays a send."""
        with self._lock:
            return self._link.poll_imu()

    def pop_other(self) -> list:
        with self._lock:
            return getattr(self._link, "pop_other", lambda: [])()

    @property
    def is_connected(self) -> bool:
        return getattr(self._link, "is_connected", False)

    def close(self) -> None:
        with self._lock:
            self._link.close()
