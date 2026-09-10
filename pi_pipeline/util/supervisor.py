"""Supervisor -- keep a long-running worker thread alive.

Similar Pi-robot projects (pidog-embodiment) log audio / serial worker threads
dying silently with no restart. On hardware G2 will run a few of these (the mic
capture / wake-word loop, the STT stream, the serial reader). This wraps a
worker callable so that if it raises, returns, or stops heart-beating, it's
restarted -- with exponential backoff and a give-up ceiling so a hard-broken
worker doesn't spin forever.

Two pieces:

  WatchdogPolicy  -- pure logic (fake-clock testable): given start / heartbeat /
                     exit events, `poll(now)` returns RUN / RESTART(delay) /
                     GIVE_UP(reason).
  Supervisor      -- the thin thread mechanics around it. `start()` spawns a
                     supervisor thread that runs the worker, watches it, and
                     restarts per the policy. `stop()` shuts it down cleanly.

The worker is `target(ctx)` where `ctx` is a `WorkerContext`:
  * `ctx.beat()`     -- call periodically so the watchdog knows it's alive
  * `ctx.stopping`   -- a threading.Event; return promptly once it's set
  * `ctx.name`       -- this supervisor's name (for logging)

Events are emitted through an injected `emit(subsystem, level, name, **kv)`
callable (default: best-effort `pi_pipeline.diag.event`).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class WatchAction(Enum):
    RUN = "run"           # worker is healthy -- nothing to do
    RESTART = "restart"   # (re)start the worker after `delay_s`
    GIVE_UP = "give_up"    # too many failures -- stop trying


@dataclass
class Decision:
    action: WatchAction
    delay_s: float = 0.0
    reason: str = ""


@dataclass
class WatchdogConfig:
    heartbeat_timeout_s: float = 5.0   # no beat for this long (after grace) -> unhealthy
    startup_grace_s: float = 3.0       # allow this long after a (re)start before expecting beats
    restart_window_s: float = 60.0     # restarts are counted over this rolling window
    max_restarts_in_window: int = 5    # more than this in the window -> GIVE_UP
    backoff_base_s: float = 0.5        # 1st restart waits this; doubles each time
    backoff_max_s: float = 30.0


class WatchdogPolicy:
    """Pure logic. Feed it events; `poll(now)` says what the supervisor should do."""

    def __init__(self, cfg: WatchdogConfig | None = None):
        self.cfg = cfg or WatchdogConfig()
        self._started_at: float | None = None
        self._last_beat: float | None = None
        self._exited_at: float | None = None
        self._exit_exc: str | None = None
        self._restarts: deque[float] = deque()   # timestamps of recent (re)starts
        self._given_up = False

    # -- events ------------------------------------------------------------
    def on_start(self, now: float) -> None:
        self._started_at = now
        self._last_beat = None
        self._exited_at = None
        self._exit_exc = None
        self._restarts.append(now)
        self._prune(now)

    def on_heartbeat(self, now: float) -> None:
        self._last_beat = now

    def on_exit(self, now: float, exc: BaseException | None) -> None:
        self._exited_at = now
        self._exit_exc = repr(exc) if exc is not None else None

    # -- query ------------------------------------------------------------
    def poll(self, now: float) -> Decision:
        c = self.cfg
        if self._given_up:
            return Decision(WatchAction.GIVE_UP, reason="already gave up")

        if self._started_at is None:
            return Decision(WatchAction.RESTART, 0.0, "first start")

        unhealthy_reason = None
        if self._exited_at is not None:
            unhealthy_reason = (f"worker exited ({self._exit_exc})" if self._exit_exc
                                else "worker returned")
        else:
            ref = self._last_beat if self._last_beat is not None else self._started_at
            grace_over = now - self._started_at >= c.startup_grace_s
            if grace_over and now - ref >= c.heartbeat_timeout_s:
                unhealthy_reason = f"no heartbeat for {now - ref:.1f}s"

        if unhealthy_reason is None:
            return Decision(WatchAction.RUN)

        self._prune(now)
        if len(self._restarts) > c.max_restarts_in_window:
            self._given_up = True
            return Decision(WatchAction.GIVE_UP,
                            reason=f"{len(self._restarts)} restarts in "
                                   f"{c.restart_window_s:.0f}s -- {unhealthy_reason}")

        n = len(self._restarts)                       # restarts so far in the window
        delay = min(c.backoff_base_s * (2 ** max(0, n - 1)), c.backoff_max_s)
        return Decision(WatchAction.RESTART, delay, unhealthy_reason)

    @property
    def given_up(self) -> bool:
        return self._given_up

    def _prune(self, now: float) -> None:
        while self._restarts and now - self._restarts[0] > self.cfg.restart_window_s:
            self._restarts.popleft()


@dataclass
class WorkerContext:
    name: str
    stopping: threading.Event
    _beat: Callable[[], None]

    def beat(self) -> None:
        self._beat()


def _default_emit(subsystem: str, level: str, name: str, **kv) -> None:
    try:
        from ..diag import event
        event(subsystem, level, name, **kv)
    except Exception:
        pass


class Supervisor:
    def __init__(self, name: str, target, *, cfg: WatchdogConfig | None = None,
                 emit=_default_emit, clock=time.monotonic, poll_interval_s: float = 0.2,
                 join_timeout_s: float = 2.0):
        self.name = name
        self._target = target
        self._policy = WatchdogPolicy(cfg)
        self._emit = emit
        self._clock = clock
        self._poll = poll_interval_s
        self._join_timeout = join_timeout_s

        self._sup_thread: threading.Thread | None = None
        self._worker: threading.Thread | None = None
        self._stopping = threading.Event()
        self._worker_stop = threading.Event()
        self._last_beat_mono = 0.0
        self._worker_exc: list[BaseException | None] = [None]
        self._restarts = 0

    # -- lifecycle ------------------------------------------------------
    def start(self) -> None:
        if self._sup_thread and self._sup_thread.is_alive():
            return
        self._stopping.clear()
        self._sup_thread = threading.Thread(target=self._supervise, name=f"sup:{self.name}",
                                            daemon=True)
        self._sup_thread.start()

    def stop(self, timeout: float | None = None) -> None:
        self._stopping.set()
        self._worker_stop.set()
        if self._sup_thread:
            self._sup_thread.join(timeout if timeout is not None else self._join_timeout)

    @property
    def alive(self) -> bool:
        return bool(self._sup_thread and self._sup_thread.is_alive())

    @property
    def given_up(self) -> bool:
        return self._policy.given_up

    @property
    def restart_count(self) -> int:
        return self._restarts

    # -- internals ----------------------------------------------------
    def _spawn_worker(self) -> None:
        self._worker_stop = threading.Event()
        self._worker_exc[0] = None
        ctx = WorkerContext(self.name, self._worker_stop, self._note_beat)
        self._last_beat_mono = self._clock()

        def _run():
            try:
                self._target(ctx)
            except BaseException as e:        # noqa: BLE001 -- report anything, keep supervising
                self._worker_exc[0] = e

        self._worker = threading.Thread(target=_run, name=f"wrk:{self.name}", daemon=True)
        self._worker.start()
        self._policy.on_start(self._clock())
        self._emit("worker", "INFO", "worker.started", worker=self.name)

    def _note_beat(self) -> None:
        self._last_beat_mono = self._clock()
        self._policy.on_heartbeat(self._last_beat_mono)

    def _supervise(self) -> None:
        self._spawn_worker()
        while not self._stopping.is_set():
            time.sleep(self._poll)
            now = self._clock()

            if self._worker and not self._worker.is_alive():
                self._policy.on_exit(now, self._worker_exc[0])

            d = self._policy.poll(now)
            if d.action is WatchAction.RUN:
                continue
            if d.action is WatchAction.GIVE_UP:
                self._emit("worker", "ERROR", "worker.gave_up",
                           worker=self.name, reason=d.reason, restarts=self._restarts)
                break

            # RESTART
            self._emit("worker", "WARN", "worker.restart", worker=self.name,
                       reason=d.reason, delay_s=round(d.delay_s, 2), n=self._restarts + 1)
            self._worker_stop.set()
            if self._worker:
                self._worker.join(self._join_timeout)
            if self._stopping.wait(d.delay_s):
                break
            self._restarts += 1
            self._spawn_worker()

        # shutdown
        self._worker_stop.set()
        if self._worker:
            self._worker.join(self._join_timeout)
        self._emit("worker", "INFO", "worker.stopped", worker=self.name,
                   restarts=self._restarts, gave_up=self._policy.given_up)
