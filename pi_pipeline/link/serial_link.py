"""A resilient serial connection to the BiBoard.

`SerialLink` does not open the port in `__init__` -- call `connect()`. On a write
or read error it marks itself disconnected and, if `auto_reconnect`, retries the
open on the next `send()`. This keeps a dropped USB/serial cable from crashing
the voice loop. `pyserial` is imported lazily so the dev machine doesn't need it.
"""
from __future__ import annotations

import collections
import logging
import threading
import time

from . import noise_log  # noqa: E402
from . import opencat, transitions  # noqa: E402

log = logging.getLogger("g2.link")

# Line prefixes of the firmware's continuous IMU stream (`gP` -> `imu.h`
# `print6Axis()`). Kept identical to gait/imu_parse.py's prefixes -- a test
# asserts they match.
IMU_PREFIXES = ("MCU:", "ICM:")
_IMU_PREFIXES_B = tuple(p.encode() for p in IMU_PREFIXES)


def is_imu_line(line: str) -> bool:
    return line.lstrip().startswith(IMU_PREFIXES)


def feedback_row(line: str):
    """The 8 leg angles of one `f` servo-feedback row (servos 8..15, tab separated, measured 2026-10-02), or None if the line is not one."""
    parts = line.replace("\t", " ").split()
    if len(parts) != 8:
        return None
    try:
        return [float(p) for p in parts]
    except ValueError:
        return None


# What the legs were last told to do, as far as the stand-up ramp is concerned. "" is a fresh process (assumed lying).
LYING_OR_SITTING = ("", "d", "krest", "kzz", "ksit")
# Skills that leave him lying or sitting, or that are not a stand-up: they never get the ramp.
STAY_DOWN_SKILLS = frozenset({"krest", "kzz", "ksit", "kzero", "kc", "kcd"})


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
        self._fb = collections.deque(maxlen=16)         # `f` servo-feedback rows: a stream (~5 rows/s) that runs until the next command, never a reply

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
    balance_epoch: int = 0       # counts the commands sent that can switch the firmware balance on (see send)
    pose_balance_epoch: int = 0  # counts the poses sent with balance on (transitions.pose_balance)
    on_failure = None            # callable(why): the "wrong answer" signal when a MOTION command (k / d / i / m) could not be sent (user, 2026-10-10); set by the services, never raises

    def _failed(self, command: str, why: str) -> None:
        if self.on_failure is not None and command[:1] in ("k", "d", "i", "m"):          # background reads and balance toggles must not honk
            try:
                self.on_failure(f"{command.strip()[:20]}: {why}")
            except Exception:  # noqa: BLE001
                pass

    def send(self, command: str, *, read_reply: bool = True, settle: float = 0.05, _deferred: bool = False) -> str:
        """Write `command` (a newline is added). Optionally read one reply line.
        Returns the reply (or '' ). Raises nothing -- logs and returns '' on error."""
        if opencat.is_disabled(command):
            log.warning("refusing %r: a move that tips G2 over on this payload, or fall recovery switched off for this attachment (link/opencat.py DISABLED_SKILLS, RECOVERY_SKILLS)", command.strip())
            try:
                from ..voice import fail_sound
                fail_sound.command_failed(f"disabled move {command.strip()}")        # the wrong-answer horn: he was asked for a move he will not do
            except Exception:  # noqa: BLE001
                pass
            return ""
        if not self.is_connected and not (self._auto_reconnect and self.connect()):
            log.debug("send(%r) dropped -- not connected", command)
            self._failed(command, "not connected")
            return ""
        if command.strip() == "gB" and not self._gyro_allowed():
            command = "gb"                        # the fitted attachment runs with the firmware gyro balance off (attachments.flag "gyro_balance")
        try:
            self._ease_transition(command)
            if transitions.pose_balance(command) and self._gyro_allowed():
                self._write_pose("gB")            # a pose plays with the firmware gyro balance on (user, 2026-10-19); after the ease, which runs with it off
                self.pose_balance_epoch += 1      # the stand guard turns it off again once he has been still
            if command[:1] == "b" and len(command) > 1 and command[1] in "-0123456789":      # a BiBoard buzzer beep
                from ..voice import audio_gate
                if not _deferred and audio_gate.is_busy():          # speech or another beep is sounding: send this beep a moment later from its own thread. NEVER wait here: the link is shared and a wait starved the walk loop of IMU frames (2026-10-10)
                    threading.Thread(target=lambda: (audio_gate.wait_idle(2.0), self.send(command, read_reply=False, settle=settle, _deferred=True)), name="beep-wait", daemon=True).start()
                    return ""
                audio_gate.note_beep(audio_gate.beep_seconds(command))
            self._ser.write((command + "\n").encode("ascii", "ignore"))
            if read_reply or settle:
                self._ser.flush()                  # wait until it is on the wire (a reply or a settle follows)
            # fire-and-forget (the walk loop's joint commands): no flush. On the Pi's UART flush() is tcdrain, which blocked every send tick ~5 ms and made
            # 30% of walk ticks late (2026-10-18, almost all on the send tick); the kernel sends the bytes in order anyway.
            noise_log.record(command)             # every command that makes the BiBoard make a noise is logged (link/noise_log.py)
            if command.strip() == "gB" or command[:1] == "k":
                self.balance_epoch += 1                     # a command that can switch the firmware gyro balance on (`gB`, or a skill: kbalance can); the stand guard reads it
            if command[:1] in ("k", "d") or (command[:1] in ("i", "m") and transitions.leg_pairs(command)):
                self.last_motion_command = command.strip()      # what the legs were last told to do (a quiet P / gb / gP, or a head-only `i0 30` look, does not change it)
                self._last_motion_t = time.monotonic()
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

    @staticmethod
    def _gyro_allowed() -> bool:
        try:
            from pi_pipeline.attachments import flag_safe
        except ImportError:
            return True
        return flag_safe("gyro_balance")

    _ramping = False
    _last_motion_t: float | None = None          # when last_motion_command went out (monotonic)
    last_pose_read: dict | None = None           # the outcome of the last read_leg_pose() (ok, rows, ms, spread, pose)

    def _ease_transition(self, command: str) -> None:
        """Every move into a firmware skill is eased (user, 2026-10-18; link/transitions.py has the rules). Two steps, each a short ramp of `i` commands:
        1. the stand-up (standing rule, user, 2026-10-10): a skill that raises him, sent while he lies or sits, is preceded by the ~0.8 s ramp to the balance pose (gait/standup.py);
        2. the transition: from the pose the link knows to the skill's first frame. `kbalance` / `kup` only ever get step 1, so a stop / freeze out of a stride stays immediate."""
        c = command.strip()
        if not c.startswith("k") or self._ramping or transitions.is_plain(c):
            return                                             # the picture poses play as the firmware does (user, 2026-10-18: eased they were too slow)
        self._ramping = True
        try:
            start = None
            # Any firmware skill that is not itself a lying or sitting one stands him up by itself, un-eased, when it starts from lying or sitting (user, 2026-10-10: a gait or turn;
            # 2026-10-18: every skill, `khi` / `kck` / `kwh` from rest looked rough). So the link stands him up first, eased, and the skill then starts from the balance pose.
            if c not in STAY_DOWN_SKILLS and self.last_motion_command in LYING_OR_SITTING:
                start = self._stand_up()
            if c in transitions.STOP_SKILLS:
                return
            end = transitions.target(c)
            if end is None:
                return
            if start is None:
                if transitions.is_stream(self.last_motion_command, self._last_motion_t):
                    return                                     # a walk or another streamed motion is running: the caller owns it
                start = transitions.pose_after(self.last_motion_command)
            if start is None and transitions.read_pose_enabled() and transitions.may_read_before(self.last_motion_command, c):
                start = self.read_leg_pose()                   # stage 2: after a firmware gait or a trick, ask the servos where the legs are
            if start is None:
                return                                         # unknown pose: the firmware's own start
            skew = transitions.skew_for(c)
            secs = transitions.ramp_seconds(start, end, skew=skew)
            if secs <= 0:
                return
            if transitions.kind(c) != "gait" and c not in transitions.STOP_SKILLS:
                self._write_pose("gb")        # firmware gyro balance off while the Pi eases (2026-10-18: with it on, the 5 Hz balance loop fought every ramp, the legs slipped and G2 "caught his balance"; the voice actuator sends gb after each posture, other callers do not)
            transitions.play(transitions.ramp_poses(start, end, secs, transitions.STEPS_PER_S, skew), lambda pose: self._write_pose(transitions.leg_cmd(pose)), sleep=time.sleep)
        except Exception as e:  # noqa: BLE001  -- the ramp must never stop the command that follows
            log.warning("transition ramp skipped (%s)", e)
        finally:
            self._ramping = False

    def _write_pose(self, command: str) -> None:
        self._ser.write((command + "\n").encode("ascii"))
        self._ser.flush()

    def _stand_up(self):
        """The eased stand-up from lying or sitting to the balance pose. Returns the balance pose (Petoi leg order) if it ran, else None."""
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
            return None
        start = standup.start_pose(self.last_motion_command) or standup.REST_URDF_DEG
        if self.last_motion_command == "ksit":
            # Rising straight from a sit puts G2's weight on the back legs while the front is loaded: on 2026-10-18 the back legs skipped and jittered and he fell
            # forward, at 0.8 s and again at 1.4 s. The stand-up from rest has been clean every time, so ease down to rest first, then stand up from there.
            transitions.play(standup.ramp_poses(start, standup.REST_URDF_DEG, standup.SIT_TO_REST_S, transitions.STEPS_PER_S), lambda pose: self._write_pose(standup.move_cmd(pose)), sleep=time.sleep)
            start = list(standup.REST_URDF_DEG)
        transitions.play(standup.ramp_poses(start, standup.BALANCE_URDF_DEG, secs, transitions.STEPS_PER_S), lambda pose: self._write_pose(standup.move_cmd(pose)), sleep=time.sleep)
        return list(transitions.BALANCE)

    def read_leg_pose(self, *, rows: int = 2, timeout_s: float = 0.6, agree_deg: float = 5.0):
        """Measured leg angles (servos 8..15, Petoi order) from the firmware's `f` feedback stream, or None.

        `f` starts a ~5 rows/s stream that the next command stops (measured over USB 2026-10-02; over the Pi's UART it returned only an echo on the
        firmware of that day, so `check_serial posecheck` re-tests it). The first `rows` rows must agree within `agree_deg` on every joint: a single
        glitched reading (the FR shoulder read -15 at 65 once) would otherwise start a ramp from a wrong angle, which is a jerk, the thing this avoids."""
        if not self.is_connected:
            return None
        try:
            self._fb.clear()
            self._ser.write(b"f\n")
            self._ser.flush()
            got, deadline = [], time.monotonic() + timeout_s
            while time.monotonic() < deadline and len(got) < rows:
                self._next_line(block_until=deadline)
                while self._fb:
                    got.append(self._fb.popleft()[1])
            ms = round((time.monotonic() - deadline + timeout_s) * 1000)
            if len(got) < rows:
                self.last_pose_read = {"ok": False, "rows": len(got), "ms": ms}
                self._diag("INFO", "link.pose_read", **self.last_pose_read)
                return None
            got = got[:rows]
            spread = max(max(r[j] for r in got) - min(r[j] for r in got) for j in range(8))
            pose = [sum(r[j] for r in got) / len(got) for j in range(8)]
            ok = spread <= agree_deg and all(abs(v) <= 130 for r in got for v in r)
            self.last_pose_read = {"ok": ok, "rows": len(got), "ms": ms, "spread": round(spread, 1), "pose": [round(v, 1) for v in pose]}
            self._diag("INFO", "link.pose_read", **self.last_pose_read)
            return pose if ok else None
        except Exception as e:  # noqa: BLE001  -- a failed read only means no easing
            log.warning("pose read failed (%s)", e)
            return None

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
        row = feedback_row(line)
        if row is not None:
            self._fb.append((time.monotonic(), row))
            return ""
        return line

    @staticmethod
    def list_ports() -> list[tuple[str, str]]:
        try:
            from serial.tools import list_ports
        except ImportError:
            return []
        return [(p.device, p.description) for p in list_ports.comports()]
