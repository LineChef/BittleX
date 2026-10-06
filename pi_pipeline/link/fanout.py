"""Give each reader of a shared link its own copy of the IMU stream.

`SerialLink.poll_imu()` hands over everything received since the last call and clears it, so two readers on one link (the stand guard, the
behavior runtime's sensor hub, the policy gait loop) steal each other's frames. `ImuFanout(link)` reads once and keeps a separate queue per
`consumer()`; a consumer forwards everything else (`send`, `drain`, ...) to the link.
"""
from __future__ import annotations

import threading
from collections import deque


class ImuFanout:
    def __init__(self, link, *, maxlen: int = 400):
        self._link = link
        self._lock = threading.Lock()
        self._queues: list[deque] = []
        self._maxlen = maxlen

    def _pump(self) -> None:
        lines = self._link.poll_imu()
        if lines:
            for q in self._queues:
                q.extend(lines)

    def consumer(self) -> "_Consumer":
        q: deque = deque(maxlen=self._maxlen)
        with self._lock:
            self._queues.append(q)
        return _Consumer(self, q)


class _Consumer:
    def __init__(self, fan: ImuFanout, q: deque):
        self._fan, self._q = fan, q

    def poll_imu(self) -> list:
        with self._fan._lock:
            self._fan._pump()
            out = list(self._q)
            self._q.clear()
        return out

    def __getattr__(self, name):
        return getattr(self._fan._link, name)
