"""Walk forward with the deployed learned policy (`DEFAULT_POLICY`), as a background thread other code can start and stop.

This is the same 80 Hz loop `run_gait.py` runs from the command line, wrapped so the voice service and the exploration runtime can use it as
G2's default forward gait instead of the firmware's `wkF` (which lifts the feet very little). Turning, walking backward and the other gaits stay
firmware tokens.

    w = PolicyWalker(link)          # `link`: a link with send() and poll_imu() -- give it its own `ImuFanout.consumer()`
    w.walk(seconds=5)               # returns at once; `w.busy` is True until the loop ends
    w.stop()                        # ends the loop (rests the legs unless `rest=False`) and waits for it
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("g2.policy_walker")

DEFAULT_CMD_FWD = 0.10        # m/s, the speed the policy has been walked at on the robot
MAX_SECONDS = 120.0           # a walk with no stated length still ends


class _Stop(threading.Event):
    rest = True


class PolicyWalker:
    def __init__(self, link, *, cmd_fwd: float = DEFAULT_CMD_FWD, run_fn=None, on_done=None, on_battery=None, on_fall=None):
        self._link, self._cmd, self._run_fn, self._on_done = link, cmd_fwd, run_fn, on_done
        self._on_battery = on_battery            # called with (level, volts) on a low reading while walking
        self._on_fall = on_fall                  # called when a walk ended because G2 fell (the exploration halts instead of walking on, 2026-10-07)
        self._thread: threading.Thread | None = None
        self._stop = _Stop()
        self._lock = threading.Lock()

    @property
    def busy(self) -> bool:
        t = self._thread
        return t is not None and t.is_alive()

    def _run(self, seconds: float) -> None:
        try:
            run = self._run_fn
            if run is None:
                from .run_gait import run as run
                from .residual_policy import CONTROL_HZ
            else:
                CONTROL_HZ = 80
            reason = run(self._link, self._cmd, seconds, CONTROL_HZ, "auto", True, stop_event=self._stop, in_service=True,
                         on_battery=self._on_battery)
            if reason == "fall" and self._on_fall is not None:
                try:
                    self._on_fall()
                except Exception:  # noqa: BLE001
                    log.exception("the fall handler failed")
        except SystemExit as e:                       # run() reports "no IMU frame" and similar this way
            log.error("policy walk could not start: %s", e)
        except Exception:  # noqa: BLE001
            log.exception("policy walk failed")
        finally:
            if self._on_done:
                try:
                    self._on_done()
                except Exception:  # noqa: BLE001
                    log.debug("on_done failed", exc_info=True)

    def walk(self, seconds: float | None = None) -> bool:
        """Start walking (no-op, returns True, if already walking)."""
        with self._lock:
            if self.busy:
                return True
            self._stop = _Stop()
            secs = min(float(seconds), MAX_SECONDS) if seconds else MAX_SECONDS
            self._thread = threading.Thread(target=self._run, args=(secs,), name="policy-walk", daemon=True)
            self._thread.start()
            log.info("policy walk started (%.0f s max)", secs)
            return True

    def stop(self, *, rest: bool = True, timeout: float = 5.0) -> None:
        with self._lock:
            t = self._thread
            if t is None or not t.is_alive():
                return
            self._stop.rest = rest
            self._stop.set()
        t.join(timeout)
        if t.is_alive():
            log.warning("the policy walk did not stop within %.0f s", timeout)
