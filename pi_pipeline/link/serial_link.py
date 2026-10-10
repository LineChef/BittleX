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

from . import noise_log  # noqa: E402

log = logging.getLogger("g2.link")

# Line prefixes of the firmware's continuous IMU stream (`gP` -> `imu.h`
# `print6Axis()`). Kept identical to gait/imu_parse.py's prefixes -- a test
# asserts they match.
IMU_PREFIXES = ("MCU:", "ICM:")
_IMU_PREFIXES_B = tuple(p.encode() for p in IMU_PREFIXES)


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
        self._other = collections.deque(maxlen=64)      # non-IMU lines seen by poll_imu(), see pop_other()

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

    last_motion_command: str = ""
    on_failure = None            # callable(why): the "wrong answer" signal when a MOTION command (k / d / i / m) could not be sent (user, 2026-10-10); set by the services, never raises

    def _failed(self, command: str, why: str) -> None:
        if self.on_failure is not None and command[:1] in ("k", "d", "i", "m"):          # background reads and balance toggles must not honk
            try:
                self.on_failure(f"{command.strip()[:20]}: {why}")
            except Exception:  # noqa: BLE001
                pass

    def send(self, command: str, *, read_reply: bool = True, settle: float = 0.05) -> str:
        """Write `command` (a newline is added). Optionally read one reply line.
        Returns the reply (or '' ). Raises nothing -- logs and returns '' on error."""
        if not self.is_connected and not (self._auto_reconnect and self.connect()):
            log.debug("send(%r) dropped -- not connected", command)
            self._failed(command, "not connected")
            return ""
        try:
            self._ease_stand_up(command)
            self._ser.write((command + "\n").encode("ascii", "ignore"))
            self._ser.flush()
            noise_log.record(command)             # every command that makes the BiBoard make a noise is logged (link/noise_log.py)
            if command[:1] in ("k", "d", "i", "m"):
                self.last_motion_command = command.strip()      # what the legs were last told to do (a quiet P / gb / gP does not change it)
            if settle:
                time.sleep(settle)
            if read_reply:
                return self._read_reply(time.monotonic() + self._read_timeout)
            return ""
        except Exception as e:  # noqa: BLE001
            log.warning("serial send failed (%s); marking disconnected", e)
            self.close()
            self._mark_down(f"send failed: {e}")
            self._failed(command, f"send failed: {e}")
            return ""

    _ramping = False

    def _ease_stand_up(self, command: str) -> None:
        """Standing rule (user, 2026-10-10): every stand-up is eased. `kup` / `kbalance` sent while G2 lies at rest (last motion `d`, or nothing yet) are preceded by a ~0.8 s ramp of `i` steps
        from the rest pose to that skill's pose (gait/standup.py). From any other state the command goes out as it is (a stop / freeze `kbalance` out of a stride must stay immediate)."""
        c = command.strip()
        walks = c.startswith(("kwk", "kcr", "ktr", "kbk", "kvt", "kgp"))     # a firmware gait or turn started from lying or sitting stands him up by itself, un-eased (user, 2026-10-10: glitchy start of an exploration)
        if not (c in ("kup", "kbalance") or walks) or self._ramping or self.last_motion_command not in ("", "d", "ksit"):
            return
        try:
            try:
                from pi_pipeline.gait import standup
            except ImportError:                       # scripts run by path (fw_skill_log.py, run_gait.py) have pi_pipeline/ itself on sys.path, not the repo root
                import importlib.util as _ilu
                import os as _os
                _p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "gait", "standup.py")
                _spec = _ilu.spec_from_file_location("g2_standup", _p)
                standup = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(standup)
            secs = standup.ramp_seconds()
            if secs <= 0:
                return
            self._ramping = True
            start = standup.start_pose(self.last_motion_command) or standup.REST_URDF_DEG
            for pose in standup.ramp_poses(start, standup.BALANCE_URDF_DEG, secs):
                self._ser.write((standup.move_cmd(pose) + "\n").encode("ascii"))
                self._ser.flush()
                time.sleep(1.0 / standup.STEPS_PER_S)
        except Exception as e:  # noqa: BLE001  -- the ramp must never stop the command that follows
            log.warning("stand-up ramp skipped (%s)", e)
        finally:
            self._ramping = False

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
                        log.debug("poll_imu kept non-IMU line %r", line)
                        self._other.append(line)
            except Exception as e:  # noqa: BLE001
                log.warning("serial read failed (%s); marking disconnected", e)
                self.close()
                self._mark_down(f"read failed: {e}")
        out = list(self._imu)
        self._imu.clear()
        return out

    def pop_other(self) -> list[str]:
        """Non-IMU lines (e.g. a `Voltage:` reply) that `poll_imu()` saw since the last call."""
        out = list(self._other)
        self._other.clear()
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

    def _pop_record(self) -> bytes | None:
        """One complete record off the receive buffer, or None if incomplete.

        Records end at a newline -- except IMU frames: over UART2 (the Pi's
        link) the BiBoard terminates each `MCU:`/`ICM:` frame with a TAB, not a
        newline (measured 2026-09-30), so a newline-only split glues every frame
        since the last reply into one giant "line". Over USB they end in a
        newline and this changes nothing. Non-IMU replies can legitimately
        contain tabs (e.g. the `X?` module table), so only IMU frames split on
        them."""
        nl = self._rx.find(b"\n")
        if self._rx.lstrip().startswith(_IMU_PREFIXES_B):
            tab = self._rx.find(b"\t")
            if tab != -1 and (nl == -1 or tab < nl):
                raw, self._rx = self._rx[:tab], self._rx[tab + 1:]
                return raw
        if nl == -1:
            return None
        raw, self._rx = self._rx[:nl], self._rx[nl + 1:]
        return raw

    def _next_line(self, block_until: float | None) -> str | None:
        """Next complete line with IMU frames routed to the IMU buffer (returned
        as ''), or None if no complete line is available -- immediately when
        `block_until` is None, else once that monotonic deadline passes."""
        while True:
            raw = self._pop_record()
            if raw is not None:
                break
            waiting = self._ser.in_waiting
            if waiting:
                self._rx += self._ser.read(waiting)
                continue
            if block_until is None or time.monotonic() >= block_until:
                return None
            chunk = self._ser.read(1)          # blocks up to the 20 ms port timeout
            if chunk:
                self._rx += chunk
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
