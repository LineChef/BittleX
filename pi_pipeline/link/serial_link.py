"""A resilient serial connection to the BiBoard.

`SerialLink` does not open the port in `__init__` -- call `connect()`. On a write
or read error it marks itself disconnected and, if `auto_reconnect`, retries the
open on the next `send()`. This keeps a dropped USB/serial cable from crashing
the voice loop. `pyserial` is imported lazily so the dev machine doesn't need it.
"""
from __future__ import annotations

import collections
import logging
import os
import threading
import time

from . import noise_log  # noqa: E402
from . import command_log  # noqa: E402
from . import opencat, transitions, motion_events  # noqa: E402

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
POSE_READ_TRIES = 3             # reads of the board's pose before a stand-up (the first one after the service stops is often garbled)
REST_FIRST_S = 3.0              # after the rest command that comes first when the pose is unknown: the time the board takes to lie down
LYING_OR_SITTING = ("", "d", "krest", "kzz", "ksit", "kcalib")      # kcalib: the attention pose (legs straight); a move out of it stands him up back legs first (user, 2026-11-02)
# Skills that leave him lying or sitting, or that are not a stand-up: they never get the ramp.
STAY_DOWN_SKILLS = frozenset({"krest", "kzz", "ksit", "kzero", "kc", "kcd", "kcalib"})


GYRO_GAIT_GAP_S = float(os.environ.get("G2_GYRO_GAIT_GAP_S", "0.3") or 0.3)


def gyro_gaits_on() -> bool:
    """`G2_GYRO_GAITS=1`: the firmware gyro balance is switched on just before a scripted gait and stays off otherwise (default off; an experiment, 2026-11-08)."""
    return os.environ.get("G2_GYRO_GAITS", "").strip().lower() in ("1", "on", "true", "yes")


class _NoWalkLog:
    def note(self, command):
        pass

    def close(self):
        pass


_NO_WALK_LOG = _NoWalkLog()


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
        from ..telemetry.scripted_walks import ScriptedWalkLog
        self._scripted_walks = ScriptedWalkLog()

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
        self._gyro_off_if_needed()                # a restarted board has the gyro assist on (its default), and with it on the firmware keeps trying its own get-up after a fall
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
        try:
            (getattr(self, "_scripted_walks", None) or _NO_WALK_LOG).close()
        except Exception:  # noqa: BLE001
            pass

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
            if command.strip() == "kcalib" and self._attention_entry_eased():     # the move into the attention pose is eased (owner, 2026-11-08: it sat hard into it): the firmware kcalib is not sent
                return ""
            self._ease_transition(command)
            if self._stand_refused:                          # the eased stand-up could not run: nothing else is sent in its place (a horn tells the owner), he stays as he is
                self._stand_refused = False
                self._skip_firmware_stand = False
                self._failed(command, "no eased stand-up")
                return ""
            if self._skip_firmware_stand and command.strip() in ("kbalance", "kup"):
                self._skip_firmware_stand = False       # the arm's own stand-up just ran (_stand_up): this stand-up command would make the firmware stand up a second time from the posture it believes he is in
                self.last_motion_command = command.strip()
                self._last_motion_t = time.monotonic()
                return ""
            self._skip_firmware_stand = False
            if transitions.pose_balance(command) and self._gyro_allowed():
                self._write_pose("gB")            # a pose plays with the firmware gyro balance on (user, 2026-10-19); after the ease, which runs with it off
                self.pose_balance_epoch += 1      # the stand guard turns it off again once he has been still
            if command[:1] == "b" and len(command) > 1 and command[1] in "-0123456789":      # a BiBoard buzzer beep
                from ..voice import audio_gate
                if not _deferred and audio_gate.is_busy():          # speech or another beep is sounding: send this beep a moment later from its own thread. NEVER wait here: the link is shared and a wait starved the walk loop of IMU frames (2026-10-10)
                    threading.Thread(target=lambda: (audio_gate.wait_idle(2.0), self.send(command, read_reply=False, settle=settle, _deferred=True)), name="beep-wait", daemon=True).start()
                    return ""
                audio_gate.note_beep(audio_gate.beep_seconds(command))
            if gyro_gaits_on() and command[:1] == "k" and command.strip() not in transitions.STOP_SKILLS and transitions.kind(command.strip()) == "gait":
                self._ser.write(b"gB\n")                 # the gyro balance on for a gait only (G2_GYRO_GAITS=1; user, 2026-11-08). The stop `kbalance` is followed by `gb` as before, so it is never on in the attention / sit poses,
                self._ser.flush()                         # where the board took a pose for a fall and started its own rc / up (the flip of 2026-11-08)
                time.sleep(GYRO_GAIT_GAP_S)               # a toggle right next to a gait token stopped the walk once (2026-10-25): leave a gap
            self._ser.write((command + "\n").encode("ascii", "ignore"))
            if read_reply or settle:
                self._ser.flush()                  # wait until it is on the wire (a reply or a settle follows)
            # fire-and-forget (the walk loop's joint commands): no flush. On the Pi's UART flush() is tcdrain, which blocked every send tick ~5 ms and made
            # 30% of walk ticks late (2026-10-18, almost all on the send tick); the kernel sends the bytes in order anyway.
            noise_log.record(command)             # every command that makes the BiBoard make a noise is logged (link/noise_log.py)
            self._last_sent_t = time.monotonic()
            command_log.sent(command)             # and every command (not the joint streams), with who sent it (link/command_log.py)
            if command.strip() in ("gP", "gp"):
                self.imu_print_on = command.strip() == "gP"
            (getattr(self, "_scripted_walks", None) or _NO_WALK_LOG).note(command)    # a scripted gait is one `scripted_walk` auto-log run, ended by the next motion command (telemetry/scripted_walks.py)
            if command.strip() == "gB" or command[:1] == "k":
                self.balance_epoch += 1                     # a command that can switch the firmware gyro balance on (`gB`, or a skill: kbalance can); the stand guard reads it
            if command[:1] == "k" and transitions.kind(command.strip()) != "gait":      # (never around a gait, before or behind it: any `gb` next to `kwkF` stopped the walk, 2026-10-25 hardware; the gyro is already off from the stand-up or the last posture)
                self._gyro_off_if_needed()                  # the arm (user, 2026-10-25): a skill turns the gyro assist back on, and with it on the firmware keeps trying its own self-right (`rc`) after a fall,
                                                            # which is what shakes the Pi plug loose; fall recovery is off for it, so the assist goes straight back off
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

    def _gyro_off_if_needed(self) -> None:
        """Send `gb` when the fitted attachment has the gyro balance off or fall recovery off (the arm). Never raises."""
        try:
            from . import opencat
            if self._ser is not None and not self._gyro_allowed():          # (user, 2026-11-08: the arm runs with the gyro balance ON; fall recovery off no longer forces it off after a skill)
                self._ser.write(b"gb\n")
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _gyro_allowed() -> bool:
        try:
            from pi_pipeline.attachments import flag_safe
        except ImportError:
            return True
        return flag_safe("gyro_balance")

    _ramping = False
    _stand_refused = False                        # set when the eased stand-up could not run: send() then drops the command that asked for it
    _skip_firmware_stand = False                  # set by _stand_up when the arm's own stand-up ran: the kbalance / kup that asked for it is not sent
    _last_motion_t: float | None = None          # when last_motion_command went out (monotonic)
    last_pose_read: dict | None = None           # the outcome of the last read_leg_pose() (ok, rows, ms, spread, pose)

    last_ease: dict | None = None                 # what the last skill's transition did: {"cmd", "ran", "why", "start", "secs", "delta"} (the drill prints it; "why" says what kept a ramp from running)
    _ease_done: str | None = None                 # a skill ease_into() already eased: send() does not ramp it a second time

    def ease_into(self, command: str, start=None) -> dict:
        """Ease the legs to `command`'s first frame NOW, from `start` (default: the pose the link knows, else the balance pose: the caller has just stopped him and let him settle), even where
        send() would not (the pose after a gait or a stream is unknown to the link). The following send() of the same command then skips its own ramp. Returns the record (also `last_ease`)."""
        c = command.strip()
        rec = {"cmd": c, "ran": False, "why": "", "start": None, "secs": 0.0, "delta": 0.0}
        self.last_ease = rec
        try:
            end = transitions.target(c) if c.startswith("k") and not transitions.is_plain(c) and c not in transitions.STOP_SKILLS else None
            if end is None:
                rec["why"] = "not an eased skill"
                return rec
            if start is None:
                start = transitions.pose_after(self.last_motion_command)
                rec["start"] = "known pose"
            if start is None:
                start = transitions.balance_pose()
                rec["start"] = "assumed balance pose"
            skew = transitions.skew_for(c)
            secs = transitions.ramp_seconds(start, end, skew=skew)
            rec["delta"] = round(max(abs(a - b) for a, b in zip(start, end)), 1)
            if secs <= 0:
                rec["why"] = "under the minimum move or ramps off"
                return rec
            self._ramping = True
            try:
                if transitions.kind(c) != "gait":
                    self._write_pose("gb")
                transitions.play(transitions.ramp_poses(start, end, secs, transitions.STEPS_PER_S, skew), lambda pose: self._write_pose(transitions.leg_cmd(pose)), sleep=time.sleep)
            finally:
                self._ramping = False
            rec.update(ran=True, secs=round(secs, 2))
            self._ease_done = c
            self.last_motion_command, self._last_motion_t = transitions.leg_cmd(end), time.monotonic()
        except Exception as e:  # noqa: BLE001
            rec["why"] = f"failed: {e}"
            log.warning("ease_into skipped (%s)", e)
        return rec

    def _ease_transition(self, command: str) -> None:
        """Every move into a firmware skill is eased (user, 2026-10-18; link/transitions.py has the rules). Two steps, each a short ramp of `i` commands:
        1. the stand-up (standing rule, user, 2026-10-10): a skill that raises him, sent while he lies or sits, is preceded by the ~0.8 s ramp to the balance pose (gait/standup.py);
        2. the transition: from the pose the link knows to the skill's first frame. `kbalance` / `kup` only ever get step 1, so a stop / freeze out of a stride stays immediate."""
        c = command.strip()
        if self._ease_done == c:
            self._ease_done = None                             # ease_into() has just done this one
            return
        self._ease_done = None
        if not c.startswith("k") or self._ramping or transitions.is_plain(c):
            return                                             # the picture poses play as the firmware does (user, 2026-10-18: eased they were too slow)
        self._ramping = True
        rec = self.last_ease = {"cmd": c, "ran": False, "why": "", "start": None, "secs": 0.0, "delta": 0.0}
        try:
            start = None
            # Any firmware skill that is not itself a lying or sitting one stands him up by itself, un-eased, when it starts from lying or sitting (user, 2026-10-10: a gait or turn;
            # 2026-10-18: every skill, `khi` / `kck` / `kwh` from rest looked rough). So the link stands him up first, eased, and the skill then starts from the balance pose.
            if c not in STAY_DOWN_SKILLS and self.last_motion_command in LYING_OR_SITTING:
                start = self._stand_up()
            if c in transitions.STOP_SKILLS:
                rec["why"] = "stop skill: immediate"
                return
            end = transitions.target(c)
            if end is None:
                rec["why"] = "no first frame / never eased"
                return
            if start is None:
                if transitions.is_stream(self.last_motion_command, self._last_motion_t):
                    rec["why"] = "a stream is running"
                    return                                     # a walk or another streamed motion is running: the caller owns it
                start = transitions.pose_after(self.last_motion_command)
                rec["start"] = "known pose" if start is not None else None
            if start is None and transitions.read_pose_enabled() and transitions.may_read_before(self.last_motion_command, c):
                start = self.read_leg_pose()                   # stage 2: after a firmware gait or a trick, ask the servos where the legs are
            if start is None:
                rec["why"] = "pose unknown to the link: the firmware's own jump"
                return                                         # unknown pose: the firmware's own start
            skew = transitions.skew_for(c)
            secs = transitions.ramp_seconds(start, end, skew=skew)
            rec["delta"] = round(max(abs(a - b) for a, b in zip(start, end)), 1)
            if secs <= 0:
                rec["why"] = "under the minimum move or ramps off"
                return
            if transitions.kind(c) != "gait" and c not in transitions.STOP_SKILLS:
                self._write_pose("gb")        # firmware gyro balance off while the Pi eases (2026-10-18: with it on, the 5 Hz balance loop fought every ramp, the legs slipped and G2 "caught his balance"; the voice actuator sends gb after each posture, other callers do not)
            transitions.play(transitions.ramp_poses(start, end, secs, transitions.STEPS_PER_S, skew), lambda pose: self._write_pose(transitions.leg_cmd(pose)), sleep=time.sleep)
            rec.update(ran=True, secs=round(secs, 2))
        except Exception as e:  # noqa: BLE001  -- the ramp must never stop the command that follows
            log.warning("transition ramp skipped (%s)", e)
        finally:
            self._ramping = False

    imu_print_on = False                          # whether the board's IMU print is on, from the last `gP` / `gp` sent (link/imu_print.py puts it back after a read that needs it off)

    def _write_pose(self, command: str) -> None:
        self._ser.write((command + "\n").encode("ascii"))
        self._ser.flush()
        if command.strip() in ("gP", "gp"):
            self.imu_print_on = command.strip() == "gP"

    def _stand_up(self):
        """The eased stand-up from lying or sitting to the balance pose. Returns the balance pose (Petoi leg order) if it ran, else None.
        With the gyro balance allowed (the arm since 2026-11-08) it is turned off for the ramp, which the firmware's 5 Hz balance loop fights (2026-10-18: the legs slipped), and on again once he is up."""
        try:
            from pi_pipeline.attachments import flag_explicit_on
            gyro = flag_explicit_on("gyro_balance")      # only where the gyro balance is switched on by name (the arm); the stock robot's stand-up is unchanged
        except ImportError:
            gyro = False
        if gyro:
            try:
                self._write_pose("gb")
            except Exception:  # noqa: BLE001
                gyro = False
        done = self._stand_up_ramp()
        if gyro:
            try:
                self._write_pose("gB")
            except Exception:  # noqa: BLE001
                pass
        return done

    def _stand_up_ramp(self):
        try:
            from pi_pipeline.gait import standup
        except ImportError:                       # scripts run by path (fw_skill_log.py, run_gait.py) have pi_pipeline/ itself on sys.path, not the repo root
            import importlib.util as _ilu
            import os as _os
            _p = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "gait", "standup.py")
            _spec = _ilu.spec_from_file_location("g2_standup", _p)
            standup = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(standup)
        if standup._poses() and standup.use_kskill(standup._poses()):      # the arm build (G2): the eased K-skill stand-up is the ONLY stand-up (owner, 2026-11-08, a hard rule)
            self._skip_firmware_stand = True                          # whatever happens, the firmware's own stand-up (the kbalance / kup that asked for this) is never sent
            if not self._stand_up_kskill(standup):
                log.error("the eased stand-up could not run (start pose unknown and unreadable, or an error): G2 does NOT stand up, and the command that asked for it is dropped")
                self._stand_refused = True
            return transitions.balance_pose()
        if standup.stand_from_attention(self._write_pose, time.sleep, self.last_motion_command):  # from the attention pose (kcalib): the back legs first, then the front legs (user, 2026-11-02)
            self._skip_firmware_stand = True
            return transitions.balance_pose()
        if standup.stand_from_sit(self._write_pose, time.sleep, self.last_motion_command):        # the arm build from a sit (the claw look): the back legs rise slowly, then the front legs
            self._skip_firmware_stand = True
            return transitions.balance_pose()
        if standup.stand_sequenced(self._write_pose, time.sleep, self.last_motion_command):       # the arm build: rear legs, then front legs, the lift easing to 0
            self._skip_firmware_stand = True
            return transitions.balance_pose()
        secs = standup.ramp_seconds()
        if secs <= 0:
            return None
        start = standup.start_pose(self.last_motion_command) or standup.rest_pose()
        if self.last_motion_command == "ksit":
            # Rising straight from a sit puts G2's weight on the back legs while the front is loaded: on 2026-10-18 the back legs skipped and jittered and he fell
            # forward, at 0.8 s and again at 1.4 s. The stand-up from rest has been clean every time, so ease down to rest first, then stand up from there.
            transitions.play(standup.ramp_poses(start, standup.rest_pose(), standup.SIT_TO_REST_S, transitions.STEPS_PER_S), lambda pose: self._write_pose(standup.move_cmd(pose)), sleep=time.sleep)
            start = standup.rest_pose()
        transitions.play(standup.ramp_poses(start, standup.balance_pose(), secs, transitions.STEPS_PER_S), lambda pose: self._write_pose(standup.move_cmd(pose)), sleep=time.sleep)
        return transitions.balance_pose()

    def _tilt_after_stand(self, seconds: float = 0.7):
        """The body's roll and pitch (median of the IMU frames over `seconds`) just after a stand-up, for the motion-event log; None if there were no frames. Never raises."""
        try:
            import math
            from ..gait.imu_parse import parse_imu_line
            if not hasattr(self._ser, "in_waiting"):         # not a real port (a test's fake): a failed read would flag the link as disconnected
                return None
            was_on = self.imu_print_on
            self._write_pose("gP")
            time.sleep(seconds)
            rows = [parse_imu_line(x) for x in (self.poll_imu() or [])]
            if not was_on:                                   # the print goes back to how it was: a guard that reads it must not lose it after every stand-up (2026-11-12: every roam turn ran with it off)
                self._write_pose("gp")
            rows = [r for r in rows if r is not None]
            if len(rows) < 2:
                return None
            med = lambda v: sorted(v)[len(v) // 2]       # noqa: E731
            return {"roll": round(med([math.degrees(r[0]) for r in rows]), 1), "pitch": round(med([math.degrees(r[1]) for r in rows]), 1), "n": len(rows)}
        except Exception:  # noqa: BLE001
            return None

    def _attention_entry_eased(self) -> bool:
        """Move into the attention pose (legs straight) as an eased `K` skill instead of the firmware `kcalib` (which drives every joint at once at full speed). UNTESTED on G2 until the next session
        (motion_feel.ATT_ENTRY_EASED turns it off). True if it handled the command (including "already there"); False means the caller sends `kcalib` as before."""
        try:
            from pi_pipeline.gait import standup
            from .. import motion_feel
            p = standup._poses()
            if not p or motion_feel.get("ATT_ENTRY_EASED") < 1:
                return False
            last = (self.last_motion_command or "").strip()
            if last == "kcalib":
                return True                                                # already in the attention pose: nothing to do
            if last in ("kbalance", "kup"):
                start = list(standup.balance_pose())
            elif last in ("d", "krest", "kzz"):
                start = list(standup.rest_pose())
            elif last == "ksit":
                start = list(standup.SIT_URDF_DEG)
            else:
                return False                                               # unknown pose: the firmware kcalib as before
            from . import kskill
            goal = list(standup.ATTENTION_URDF_DEG)
            data = kskill.message(kskill.entry_payload(start, goal, steps=int(motion_feel.get("ATT_ENTRY_STEPS")), speed_raw=int(motion_feel.get("ATT_ENTRY_SPEED"))))
            kskill.write_chunked(self._ser.write, data, time.sleep)
            self._ser.flush()
            waited, reached = 0.0, False
            while waited < motion_feel.get("ATT_ENTRY_WAIT_S"):
                time.sleep(kskill.POLL_S)
                waited += kskill.POLL_S + 0.25
                if waited >= kskill.MIN_WAIT_S and kskill.legs_reached(kskill.read_joints(self), goal):
                    reached = True
                    break
            if not reached:                                                # not snapped into it: a jump to the pose with his weight on the legs put the feet in odd places (owner, 2026-11-12); the skill is left to finish and the look's keep-alive holds the angles
                log.warning("eased move into the attention pose: the board did not report it after %.1f s: left to finish (no forced jump)", waited)
                time.sleep(1.0)
            else:
                log.info("the attention pose was reached after about %.1f s", waited)
            self.last_motion_command, self._last_motion_t = "kcalib", time.monotonic()
            log.info("moved into the attention pose as an eased K skill (%d bytes)", len(data))
            return True
        except Exception as e:  # noqa: BLE001  -- fall back to the firmware kcalib
            log.warning("eased move into the attention pose failed (%s): the firmware kcalib follows", e)
            return False

    def _stand_up_kskill(self, standup) -> bool:
        """The eased K stand-up, and one line in the motion events log (link/motion_events.py) for it, whatever happens."""
        ev: dict = {"outcome": "refused"}
        t0 = time.monotonic()
        try:
            ok = self._stand_up_kskill_run(standup, ev)
        except Exception as e:  # noqa: BLE001
            ev["error"] = str(e)[:120]
            ok = False
        ev["seconds"] = round(time.monotonic() - t0, 1)
        if not ok:
            ev["outcome"] = "refused"
        motion_events.write("stand_up", **ev)
        return ok

    def _stand_up_kskill_run(self, standup, ev: dict) -> bool:
        """THE stand-up (link/kskill.py): the whole rise as one `K` skill the board plays itself, from rest, a sit, the attention pose, or (when the pose is not known) the leg angles the board reports.
        Waits until the board reports the stand pose, forces it if it does not get there, gyro on during the rise and off right after. True if it ran; False means NOTHING was done (never a firmware stand-up)."""
        try:
            p = standup._poses()
            if not p or not standup.use_kskill(p):
                return False
            from .. import motion_feel
            from . import kskill
            last = (self.last_motion_command or "").strip()
            ev["last_command"] = last
            # The pose is read before EVERY stand-up (owner, 2026-11-09): a pose the board reports as rest, a sit or the attention pose is the start (it wins over what the Pi last sent); a pose it
            # does not know, or no readable pose at all (the first read after the service stops often comes back garbled), and he is laid in rest first, then stood up from rest.
            j0 = None
            for _ in range(POSE_READ_TRIES):
                j0 = kskill.read_joints(self)
                if j0 and len(j0) >= 16:
                    break
                j0 = None
                time.sleep(0.25)
            pose = kskill.classify_start(j0, standup)
            ev["pose_read"] = pose
            if j0:
                ev["legs"] = [int(j0[kskill.URDF_TO_SERVO[k]]) for k in range(8)]
            ev["rested_first"] = False
            if pose == "unknown" and j0 is not None:
                # a readable pose that is not one of the four (the survey bow, the check lean): eased from the angles the board reports, never a `krest` first (owner, 2026-11-10: "ease the bow to rest";
                # the rest-first rule of 2026-11-09 stays for an UNREADABLE pose)
                log.info("stand-up: the pose is not a known one: easing up from the angles the board reports")
                ev["eased_from_reported"] = True
                last = "unknown"                                  # the start is the reported angles, whatever was sent last
            elif pose == "unknown":
                log.warning("stand-up: the pose is %s: laying him in rest first", "unreadable" if j0 is None else "not a known one")
                self._write_pose("krest")
                time.sleep(REST_FIRST_S)
                self._write_pose("gb")
                self.last_motion_command, self._last_motion_t = "krest", time.monotonic()
                last, ev["rested_first"] = "krest", True
                j1 = kskill.read_joints(self)
                after = kskill.classify_start(j1, standup)
                ev["pose_after_rest"] = after
                pose = after if after in ("rest", "sit", "attention") else "rest"          # still unreadable or odd after the rest command: he was just told to lie down
            if pose in ("rest", "sit", "attention"):
                last = {"rest": "krest", "sit": "ksit", "attention": "kcalib"}[pose]
            ev["start"] = last
            motion_events.write("stand_up_start", pose_read=pose, start=last, joints=[int(x) for x in j0[:16]] if j0 else None)      # written BEFORE the rise: a fall in the middle of it still leaves what the board reported (the line above is only written when the stand-up ends)
            lift0, lift1 = None, None
            if last in ("d", "krest", "kzz"):
                start, lift0, lift1 = standup.rest_pose(), p.get("arm_rest"), p.get("arm_walk")            # the claw is on the floor at rest: its lift eases up with the legs
            elif last == "kcalib":
                start = list(standup.ATTENTION_URDF_DEG)                                                   # the claw is already down: only the legs rise
            elif last == "ksit":
                start = list(standup.SIT_URDF_DEG)
            else:                                                                                          # unknown (a fresh process, after a trick): the angles the board reports
                j = kskill.read_joints(self)
                if not j or len(j) < 16:
                    return False
                start = [float(j[kskill.URDF_TO_SERVO[k]]) for k in range(8)]
                lift0, lift1 = float(j[1]), p.get("arm_walk")
            t = kskill.tuning(from_attention=(last == "kcalib"))
            data = kskill.message(kskill.stand_payload(start, standup.balance_pose(), lift0, lift1, steps=t["steps"], speed_raw=t["speed"], delay_raw=t["delay"], speeds=t["speeds"], front_start=t["front_start"], rear_end=t["rear_end"], rear_hold=t["rear_hold"]))
            from pi_pipeline.attachments import flag_explicit_on
            keep_on = flag_explicit_on("gyro_balance")             # the gyro balance is on for the whole run (G2_GYRO_BALANCE=1): leave it
            gyro = keep_on or motion_feel.get("STAND_GYRO") >= 1     # on while the board plays the rise (the gyro-on stand-up was 10 of 10)
            if gyro:
                self._write_pose("gB")
                time.sleep(0.2)
            kskill.write_chunked(self._ser.write, data, time.sleep)          # in short pieces: a long burst can overflow the board's input while it is busy
            self._ser.flush()
            goal = standup.balance_pose()
            waited, reached = 0.0, False
            while waited < max(t["wait_s"] * 2.0, 6.0):                      # until the board reports the stand pose (not a fixed time: the Pi once moved on while the board was still rising, 2026-11-08)
                time.sleep(kskill.POLL_S)
                waited += kskill.POLL_S + 0.25
                if waited < kskill.MIN_WAIT_S:
                    continue
                if kskill.legs_reached(kskill.read_joints(self), goal):
                    reached = True
                    break
            ev["outcome"], ev["waited_s"] = ("reached" if reached else "forced"), round(waited, 1)
            ev["speeds"], ev["wait_s"], ev["gyro"] = t["speeds"], t["wait_s"], bool(gyro)
            if not reached:                                                  # did not get there: force the legs to the stand angles before anything else moves
                log.warning("K-skill stand-up: the board did not report the stand pose after %.1f s: forcing it", waited)
                for _ in range(2):
                    self._write_pose(standup.move_cmd(goal))
                    time.sleep(0.3)
            if gyro and not keep_on:
                self._write_pose("gb")                             # off again right after the rise: never left on in the attention / sit poses (the board's own rc / up flipped him there)
            ev["tilt_after"] = self._tilt_after_stand()                # how he stands once the rise is over (2026-11-10: he ends up on his hind legs after the exploration's attention stand-ups)
            self.last_motion_command, self._last_motion_t = "kbalance", time.monotonic()
            log.info("stand-up played as a K skill (%d bytes), tilt after: %s", len(data), ev["tilt_after"])
            return True
        except Exception as e:  # noqa: BLE001
            log.error("K-skill stand-up failed (%s)", e)
            return False

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
                        last = getattr(self, "_last_sent_t", None)
                        command_log.heard(line, None if last is None else time.monotonic() - last)      # a line nobody asked for: a voice command to the board shows up here
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
