"""On-Pi control loop: run the deployed gait policy (residual_policy.DEFAULT_POLICY) on the real robot.

    python -m pi_pipeline.gait.run_gait --probe-imu           # see what the BiBoard streams (idle bus)
    python -m pi_pipeline.gait.run_gait --probe-imu-load      # same, but under real 80 Hz command load
    python -m pi_pipeline.gait.run_gait --openloop            # play wkf_ref.npy, no policy (calibration)
    python -m pi_pipeline.gait.run_gait --cmd 0.10            # walk forward at 0.10 m/s
    python -m pi_pipeline.gait.run_gait --cmd 0.0 --seconds 5 # stand + hold

Pipeline per tick (~80 Hz):
    ImuFeed <- every IMU line received since last tick (non-blocking poll)
      -> latest (roll,pitch,yaw rad) held between the firmware's 5 Hz prints,
         roll/pitch rate = 0 (--imu-rate fd: finite difference; no better in sim)
    quat = policy_quat(rpy)        # yaw sign flipped to the sim's convention (POLICY_YAW_SIGN)
    joint_deg_urdf = ResidualGaitPolicy.step(quat, gyro)
    "i8 <d> 12 <d> ..."  = deploy_map.policy_deg_to_move_cmd(joint_deg_urdf)
    serial.send(cmd)

The BiBoard streams 6-axis IMU after the `gP` command (T_GYRO 'g' +
C_PRINT 'P' -- NOT the bare 'V' this code sent before 2026-09-20; that
token doesn't exist in current firmware source at all). Line format is
confirmed from source (see parse_imu_line's docstring). The stream is
throttled to 5 Hz in firmware and carries no gyro, so the loop must not wait
for IMU lines: until 2026-09-22 it did a blocking readline per tick, which
paced the whole loop -- policy, gait phase and joint commands -- to the 5 Hz
IMU print instead of 80 Hz. Run --probe-imu at bring-up to confirm the chip
prefix (MCU/ICM) and yaw sign on the real unit before trusting this loop.

SAFETY: on any of {no IMU frame for IMU_STALE_S, Ctrl-C, loop overrun}, the loop
sends `d` (rest, servos relaxed) and exits. deploy_map clamps every command to
+/-120 deg. Start with --openloop on a stand/cradle before trusting the policy.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                              # sibling modules, also under `python -m`
sys.path.insert(0, os.path.join(_HERE, ".."))          # for `link`
sys.path.insert(0, os.path.join(_HERE, "..", ".."))    # repo root, for `pi_pipeline.diag`

from residual_policy import ResidualGaitPolicy, CONTROL_HZ, heading_blind_for   # noqa: E402
import deploy_map                                             # noqa: E402
from thermal_guard import ThermalGuard                        # noqa: E402
import heading_hold as _hh                                    # noqa: E402  -- optional steering on the policy's joint targets (--heading-hold)
from imu_parse import ImuFeed, parse_imu_line                 # noqa: E402  -- shared with app/sensors.py

try:                                                          # carpet mode (optional)
    from pi_pipeline.gait.carpet import CarpetAction, CarpetDetector  # noqa: E402
    from pi_pipeline.gait.speed_estimate import ZuptSpeedEstimator    # noqa: E402
    from pi_pipeline.link import opencat as _opencat                  # noqa: E402
except Exception:                                             # noqa: BLE001
    CarpetDetector = None

try:                                                          # Phase E vision-skill layer (optional)
    from pi_pipeline.gait.skill_layer import SkillLayer       # noqa: E402
    from pi_pipeline.gait.skill_switch import SkillRefs       # noqa: E402
    from pi_pipeline.vision.cliff_guard import CliffAction, CliffGuard, action_commands  # noqa: E402
    from pi_pipeline.vision.gait_selector import detections_to_terrain_reading  # noqa: E402
except Exception:                                             # noqa: BLE001 -- runs blind without it
    SkillLayer = None

try:
    from pi_pipeline.diag import diag, RingBuffer, bridge_stdlib_logging  # noqa: E402
except Exception:                                             # diag is optional
    diag = None
    RingBuffer = None
    def bridge_stdlib_logging(*_a, **_kw):  # type: ignore
        pass

_THERMAL_EVENT = {   # guard state -> (event name, level)
    "warn":     ("servo.thermal_warn", "WARN"),
    "soft":     ("servo.soft_cutback", "WARN"),
    "cooldown": ("servo.thermal_cooldown", "ERROR"),
}


def _speak_best_effort(phrase):
    """Say it through the voice pipeline if that stack is importable, else print."""
    print(f"[thermal] G2: \"{phrase}\"", flush=True)
    try:
        from pi_pipeline.voice.tts import speak     # type: ignore
        speak(phrase)
    except Exception:
        pass


# --------------------------------------------------------------------- IMU
def euler_to_quat(roll, pitch, yaw):
    """(r,p,y) rad -> quaternion [x,y,z,w], inverse of residual_policy.quat_to_euler."""
    cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    return np.array([
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
        cr * cp * cy + sr * sp * sy,
    ])


# The firmware IMU stream (imu_parse) reports + yaw for a RIGHT turn (confirmed on G2 2026-10-02); the policy was
# trained in PyBullet, where + yaw is a LEFT turn (z up). Until 2026-10-06 the rebased yaw went into the policy with
# the wrong sign: harmless for V2.1 (it ignores heading, docs/rl/v3-retrain-plan.md §1.1), wrong for any policy that
# uses it. Logs keep the firmware convention (+ = right); only the policy's input is flipped.
POLICY_YAW_SIGN = float(os.environ.get("G2_POLICY_YAW_SIGN", "-1"))   # -1 is correct; +1 reproduces the pre-2026-10-06 behaviour, for A/B tests only


def policy_quat(roll, pitch, yaw_fw):
    """IMU (roll, pitch, rebased firmware yaw) rad -> the quaternion the policy expects (PyBullet yaw sign)."""
    return euler_to_quat(roll, pitch, POLICY_YAW_SIGN * yaw_fw)


# --------------------------------------------------------------------- loop
FALL_ABORT_S = 0.3                                # how long a >fall_abort_deg tilt must persist before the loop rests
STAND_URDF_DEG = [50, 0, 50, 0, 50, 0, 50, 0]     # matches env.reset() start pose
IMU_STALE_S = 0.6     # no IMU frame for this long (3 missed 5 Hz prints) -> stop


def _open_link(port, baud):
    """Opens the BiBoard serial link or exits with a clear error."""
    from link.serial_link import SerialLink
    lk = SerialLink(port, baud=baud)
    if not lk.connect():
        raise SystemExit(f"could not open {port} @ {baud}")
    return lk


def probe_imu(lk, seconds):
    """Bring-up check: start the IMU stream, print raw lines and the measured
    rate for `seconds`, then stop it."""
    # CONFIRMED from firmware source (src/OpenCat.h, src/reaction.h) 2026-09-20:
    # 'V' is not a real token at all (grepped the current source, doesn't exist
    # anywhere in the command parser -- would just be silently ignored). The
    # actual continuous-6-axis-print trigger is T_GYRO ('g') + C_PRINT ('P'),
    # i.e. the two-character command "gP" -- updateGyroQ is already true from
    # boot, so "gU" isn't needed just to get the stream moving. Turning it back
    # off is NOT symmetric: send "gp" (lowercase C_PRINT_OFF), not "gP" again --
    # 'P' vs 'p' selects continuous-vs-once, it isn't a toggle.
    print("sending 'gP' (start continuous 6-axis print); printing raw lines for", seconds, "s")
    _send(lk, "gP")
    t0 = time.time()
    n = 0
    while time.time() - t0 < seconds:
        for line in lk.poll_imu():
            print(repr(line))
            n += 1
        time.sleep(0.01)
    _send(lk, "gp")
    print(f"{n} IMU lines in {seconds:.0f} s = {n / seconds:.1f} Hz")
    print("stream stopped ('gp'). Match parse_imu_line() to the format above.")
    print("NOTE: this is a passive/idle measurement (nothing else was sent to the "
          "board). Real hardware measured ~249 Hz here 2026-09-28, contradicting "
          "the documented 5 Hz cap -- see docs/hardware/petoi-firmware-reference.md. "
          "Run --probe-imu-load too before trusting this number for the real "
          "control loop, which shares the same UART with 80 Hz command traffic.")


def probe_imu_under_load(lk, seconds, hz=CONTROL_HZ):
    """Same measurement as probe_imu, but with the control loop's other half of
    the traffic actually running: sends the neutral stand pose at `hz` (the real
    deployment rate) while counting IMU lines, instead of just listening
    quietly. probe_imu measures a best case (idle bus); this measures the
    shared-bus condition run_gait's real control loop operates under -- sending
    and receiving on the same UART at once. Added 2026-09-28 after probe_imu's
    249 Hz idle measurement contradicted the documented 5 Hz cap: that number
    alone wasn't enough to trust, since it never exercised simultaneous 80 Hz
    command traffic. Leaves the robot in a neutral stand + rest on exit."""
    cmd = deploy_map.policy_deg_to_move_cmd(STAND_URDF_DEG)
    print(f"sending 'gP' + neutral stand at {hz:g} Hz for {seconds:g}s "
         "(real control-loop load, not idle); counting IMU lines")
    _send(lk, "gP")
    dt = 1.0 / hz
    t0 = time.time()
    t_next = time.perf_counter()
    n = 0
    while time.time() - t0 < seconds:
        _send(lk, cmd)
        for _ in lk.poll_imu():
            n += 1
        t_next += dt
        slack = t_next - time.perf_counter()
        if slack > 0:
            time.sleep(slack)
        else:
            t_next = time.perf_counter()
    _send(lk, "gp")
    _send(lk, "d")
    print(f"{n} IMU lines in {seconds:.0f} s = {n / seconds:.1f} Hz under {hz:g} Hz "
         "command load -- compare against the passive --probe-imu number")
    return n


def openloop(lk, cycles, hz, lift_scale=1.0, log_path=None, fall_abort_deg=60.0,
             balance_off=False, lift_joints="all", shoulder_scale=1.0, ramp_cycles=0.0, volt_every_s=0.0, send_every=1, foot_trim=None, *,
             sleep=time.sleep, clock=time.monotonic):
    """Replays the scripted wkF walk with no policy/IMU -- a firmware/servo
    sanity check before running the real control loop.

    `lift_scale` multiplies every joint's swing around its cycle mean (1.3 -> ~14 mm peak
    foot lift instead of ~10; 1.6 -> ~21; 2.0 -> ~31, estimated with the sim's robot model),
    for finding how much lift a surface needs. `log_path` records the IMU (same columns as
    the policy loop's log); the fall guard rests after a sustained tilt past
    `fall_abort_deg`. `balance_off` sends `gb` first, so it is purely scripted.
    `lift_joints="knees"` applies `lift_scale` to the knees only (the stride barely changes,
    unlike scaling every joint, which lengthens it ~1.5-1.9x at x1.6-2.0); `shoulder_scale`
    scales the shoulder swing (<1 shortens the stride: knees x2.0 + shoulders x0.7 is ~26 mm
    lift at ~the original ~75 mm stride, est. with the sim's robot model). `ramp_cycles`
    blends the scaling in from x1 over that many cycles, so the first frames match plain
    wkF (a scaled gait jumps further from the stand pose and can topple G2 at the start).
    `volt_every_s` > 0 asks the BiBoard for the battery voltage (`P`) that often during the
    walk and records the latest reading in the log's `volt` column.

    Pacing (2026-10-07): frames are scheduled against a deadline, the way the policy loop does, so the playback holds `hz` however long a send takes. It used to sleep `dt` AFTER
    each frame's work (a serial send blocks about 5 ms at 115200 baud), which ran the walk at about 44 Hz instead of 80 (23 s for a 12.5 s walk). `send_every` sends only every Nth
    frame (the policy loop sends every 3rd tick, `i@27`, the cadence the BiBoard is known to take without chattering); the frames in between are skipped, not queued."""
    ref = np.load(os.path.join(_HERE, "wkf_ref.npy"))          # (100,8) rad, URDF order
    m = ref.mean(axis=0)
    scale = np.ones(8)
    scale[[1, 3, 5, 7] if lift_joints == "knees" else slice(None)] = lift_scale
    scale[[0, 2, 4, 6]] *= shoulder_scale if lift_joints == "knees" else 1.0
    base = ref
    ref = m + (ref - m) * scale
    ramp_n = int(ramp_cycles * len(ref))
    dt = 1.0 / hz
    print(f"open-loop wkF playback: {cycles} cycles, {hz} Hz, lift x{lift_scale:g}"
          f"{' (knees only' + (f', shoulders x{shoulder_scale:g}' if shoulder_scale != 1.0 else '') + ')' if lift_joints == 'knees' else ''}"
          f"{', balance off' if balance_off else ''}. Ctrl-C to stop.")
    log = open(log_path, "w") if log_path else None
    t_start, tilt_since, fell = clock(), None, False
    try:
        if balance_off:
            _send(lk, "gb")
            sleep(0.2)
        _send(lk, deploy_map.policy_deg_to_move_cmd(STAND_URDF_DEG))   # stand first: no jump from rest into mid-stride
        sleep(2.0)
        if log:
            log.write(f"# openloop wkF  cycles={cycles} hz={hz} lift_scale={lift_scale:g} balance_off={balance_off}\n")
            log.write("t,roll,pitch,yaw,gx,gy,gz,guard_state,volt\n")
            _send(lk, "gP")
            sleep(0.3)
            t_start = clock()
        step, volt, next_volt = 0, float("nan"), 0.0
        every = max(1, int(send_every))
        t_next = clock()
        for c in range(cycles):
            for fi, frame in enumerate(ref):
                if ramp_n and step < ramp_n:                    # blend plain wkF -> the scaled gait
                    frame = base[fi] + (frame - base[fi]) * (step / ramp_n)
                step += 1
                if (step - 1) % every == 0:
                    deg = np.rint(np.rad2deg(frame)).astype(int)
                    if foot_trim is not None:            # --foot-trim: one foot's swing scaled, fixed, no feedback
                        deg = np.array(_hh.apply_foot_trims(deg, foot_trim), dtype=int)
                    _send(lk, deploy_map.policy_deg_to_move_cmd(deg))
                if volt_every_s and clock() - t_start >= next_volt:
                    _send(lk, "P")
                    next_volt = clock() - t_start + volt_every_s
                if log or fall_abort_deg:
                    for line in lk.poll_imu():
                        r = parse_imu_line(line)
                        if r is None:
                            continue
                        if volt_every_s:
                            for o in getattr(lk, "pop_other", lambda: [])():
                                if o.startswith("Voltage"):
                                    try:
                                        volt = float(o.split(":")[1].split()[0])
                                    except (IndexError, ValueError):
                                        pass
                        if log:
                            log.write(f"{clock() - t_start:.4f},{r[0]:.5f},{r[1]:.5f},{r[2]:.5f},0,0,0,ok,{volt:.2f}\n")
                        if fall_abort_deg and max(abs(r[0]), abs(r[1])) > math.radians(fall_abort_deg):
                            tilt_since = tilt_since if tilt_since is not None else clock()
                            fell = fell or (clock() - tilt_since >= FALL_ABORT_S)
                        else:
                            tilt_since = None
                if fell:
                    print("!! fallen -- resting", flush=True)
                    return
                t_next += dt
                slack = t_next - clock()
                if slack > 0:
                    sleep(slack)
                else:
                    t_next = clock()                            # fell behind: do not try to catch up in a burst
    finally:
        if log:
            log.close()
            _send(lk, "gp")
        if balance_off:
            _send(lk, "gB")       # restore the firmware balance BEFORE the rest, as the policy loop does: `d` sent right after left G2 standing
            sleep(0.3)
        _send(lk, "d")
        sleep(0.5)                # a pause so the board has the rest command before the port closes (2026-10-07: without it G2 stayed standing after a scripted walk)
    print("done (sent rest).")


def dry_run(cmd_fwd, seconds, hz, skill_layer=None, vision=None):
    """Full 80 Hz loop with synthetic (near-level) IMU and NO serial -- checks the
    loop holds rate on this machine before any hardware exists. With --skills it
    also drives the vision-skill layer (mock feed) so the whole path is exercised
    without a robot."""
    pol = ResidualGaitPolicy()
    pol.set_command(fwd=cmd_fwd, yaw=0.0)
    rng = np.random.default_rng(0)

    def fake_imu():
        r, p_, y = rng.normal(0, 0.05, 3)
        return euler_to_quat(r, p_, y), rng.normal(0, 0.3, 3)

    q, g = fake_imu()
    pol.reset(np.deg2rad(np.array(STAND_URDF_DEG, dtype=float)), q, g)
    if skill_layer is not None:
        skill_layer.reset()
    _skill_prev = "cruise"
    modes_seen = {}
    dt = 1.0 / hz
    n = int((seconds or 5.0) * hz)
    step_ms, loop_ms = [], []
    t_next = time.perf_counter()
    t_loop = time.perf_counter()
    print(f"dry-run: {hz} Hz x {n} ticks, cmd_fwd={cmd_fwd}. No serial."
          + ("  [skills ON]" if skill_layer is not None else ""))
    for _ in range(n):
        q, g = fake_imu()
        t0 = time.perf_counter()
        jd = pol.step(q, g)
        if skill_layer is not None:
            frame = vision.latest() if vision is not None else []
            terr = detections_to_terrain_reading(frame)
            jd, sinfo = skill_layer.step(jd, gait_phase=pol.phase_frac(), terrain=terr)
            pol.set_command(fwd=cmd_fwd * sinfo.speed_scale)
            if vision is not None:
                vision.set_look_down(skill_layer.looking_down)
            modes_seen[sinfo.mode.value] = modes_seen.get(sinfo.mode.value, 0) + 1
            if sinfo.mode.value != _skill_prev:
                print(f"  [skills] {_skill_prev} -> {sinfo.mode.value} (src={sinfo.source.value})")
                _skill_prev = sinfo.mode.value
        _ = deploy_map.policy_deg_to_move_cmd(jd)          # build the string, don't send
        step_ms.append((time.perf_counter() - t0) * 1e3)
        t_next += dt
        slack = t_next - time.perf_counter()
        if slack > 0:
            time.sleep(slack)
        else:
            t_next = time.perf_counter()
        now = time.perf_counter()
        loop_ms.append((now - t_loop) * 1e3)
        t_loop = now
    s = np.array(step_ms); l = np.array(loop_ms[1:])
    print(f"  policy step : mean {s.mean():.2f} ms  p95 {np.percentile(s,95):.2f}  max {s.max():.2f}")
    print(f"  loop period : mean {l.mean():.2f} ms  (target {dt*1e3:.2f})  -> {1000/l.mean():.1f} Hz achieved")
    print(f"  overruns    : {(l > dt*1e3*1.5).sum()} / {len(l)} ticks > 1.5x target")
    if skill_layer is not None:
        print(f"  skill modes : {modes_seen}")


# --------------------------------------------------------------- vision skills
_REF_DIRS = (_HERE, os.path.join(_HERE, "..", "..", "rl_training", "opencat-gym",
                                 "reference_gait"))


def _load_ref(name):
    """(N,8) rad keyframe array from pi_pipeline/gait/ or the training reference_gait/."""
    for d in _REF_DIRS:
        p = os.path.join(d, name)
        if os.path.exists(p):
            return np.load(p).astype(np.float64)
    raise FileNotFoundError(f"{name} not found in {[os.path.normpath(d) for d in _REF_DIRS]}")


def build_skill_layer(*, with_cliff_guard=True):
    """Assemble the Phase E SkillLayer from the shipped keyframe references.
    step_over -> trot (tr_ref, won the item-1 A/B), inspect -> crouch, back_out ->
    walk-backward, brace -> derived from stance, stance -> wkF mean pose."""
    if SkillLayer is None:
        raise RuntimeError("skill layer deps missing (pi_pipeline.vision / .gait import failed)")
    refs = SkillRefs(
        step_over=_load_ref("tr_ref.npy"),
        inspect=_load_ref("inspect_sweep_ref.npy"),   # up-and-down camera scan (nose-up -> bow)
        back_out=_load_ref("bk_ref.npy"),
        brace=None,                                   # derived: stance + knee flex
        stance=_load_ref("wkf_ref.npy").mean(axis=0),
    )
    return SkillLayer(refs, cliff_guard=CliffGuard() if with_cliff_guard else None)


class _LatestFrame:
    """Pull `feed.frames()` in a daemon thread; expose the newest frame without
    blocking the 80 Hz loop. `latest()` returns [] once a frame is older than
    `stale_after` s (detector dropped out -> treat as 'nothing seen')."""

    def __init__(self, feed, stale_after=0.6):
        import threading
        self._feed = feed
        self._stale = float(stale_after)
        self._frame = []
        self._stamp = 0.0
        self._stop = threading.Event()
        self._look_down = False
        self._th = threading.Thread(target=self._pump, name="vision-feed", daemon=True)

    def start(self):
        self._th.start()
        return self

    def _pump(self):
        try:
            for fr in self._feed.frames():
                if self._stop.is_set():
                    break
                self._frame, self._stamp = fr, time.time()
        except Exception as e:  # noqa: BLE001 -- a dead feed must not kill the gait
            print(f"[skills] vision feed stopped: {e!r}", flush=True)

    def latest(self):
        if time.time() - self._stamp > self._stale:
            return []
        return self._frame

    def set_look_down(self, v):
        self._look_down = bool(v)

    def close(self):
        self._stop.set()
        try:
            self._feed.close()
        except Exception:  # noqa: BLE001
            pass


def _cliff_firmware_action(lk, cliff_action, turn_burst_s):
    """The gait layer can only HALT for an edge -- turning is a firmware job.
    When CliffGuard asks to turn away / back up, hand off to the OpenCat scripted
    turn gait for a short burst, then let the policy loop resume and CliffGuard
    re-evaluate the next edge read. Returns True if it drove the servos this tick
    (caller skips its normal move send). FREEZE is handled by the caller."""
    if SkillLayer is None or cliff_action is None:
        return False
    if cliff_action in (CliffAction.TURN_AWAY_LEFT, CliffAction.TURN_AWAY_RIGHT,
                        CliffAction.BACK_UP):
        for tok in action_commands(cliff_action):
            _send(lk, tok)
        time.sleep(max(0.0, turn_burst_s))
        return True
    return False


def _make_vision_feed(kind, port, baud):
    """kind: 'serial' (Grove Vision AI on its own USB port) or 'mock:approach'
    (a scripted box growing in the path, loops -- bench check without the camera)."""
    from pi_pipeline.vision.feed import MockDetectionFeed, SerialDetectionFeed
    if kind == "serial":
        labels = [s for s in os.environ.get("VISION_LABELS", "").split(",") if s]
        return SerialDetectionFeed(port, baud, labels=labels or None,
                                   min_score=int(os.environ.get("VISION_MIN_SCORE", "40")))
    if kind.startswith("mock"):
        script = MockDetectionFeed.approaching(steps=10, bearing=0.5)
        return MockDetectionFeed(script * 1000, interval=0.4)
    raise SystemExit(f"unknown --skills-feed {kind!r} (want 'serial' or 'mock')")


def _extra_cols(feed, now, volt, on):
    """The `--log-extra` columns: accel in m/s^2, how many IMU frames have arrived so far (equal numbers on consecutive rows mean the same held
    frame, so a fresh reading is the row where it changes), seconds since the latest frame, and the last pack voltage."""
    if not on:
        return ""
    a = feed.accel if feed.accel is not None else (float("nan"),) * 3
    age = feed.age(now)
    return ",%.2f,%.2f,%.2f,%d,%.3f,%.2f" % (a[0], a[1], a[2], feed.frames, age if age != float("inf") else float("nan"), volt)


# --------------------------------------------------------------------- loop
def run(lk, cmd_fwd, seconds, hz, imu_fmt, disable_firmware_balance, log_path=None,
        thermal_guard=True, skill_layer=None, vision=None, skill_labels=None,
        turn_burst_s=1.0, carpet=False, imu_rate="zero", policy_path=None, send_every=None, fall_abort_deg=60.0,
        stop_event=None, in_service=False, volt_every_s=5.0, on_battery=None, heading_hold=False, steer_const=None, hold_ff=0.0, hold_kp=None, hold_umax=None, hold_ki=None, log_extra=False, foot_trim=None, foot_hold=None, scripted=False):
    """`log_extra=True` adds accel (m/s^2, about 10 on az at rest), the IMU frame counter and age, and the pack voltage to the log (see tools/g2_log_extra notes in docs/rl/hardware-logging.md).
    `heading_hold=True` steers back toward the starting heading by lengthening the strides on one side (gait/heading_hold.py); off by default.
    `stop_event` (a threading.Event) ends the loop from another thread; with `stop_event.rest = False` the legs are left standing, not rested.
    `volt_every_s` > 0 reads the battery voltage (`P`) that often WHILE walking, logs each reading (diag `gait/battery.load`), calls
    `on_battery(level, volts)` on a low reading (default: speak it) and rests the legs on a critical one before the board browns out.
    `in_service=True` is for a caller that owns the diagnostics session and the IMU stream (the voice service): this loop then neither
    starts/closes a diag session nor turns the stream off or restores firmware balance when it ends."""
    pol = ResidualGaitPolicy(onnx_path=policy_path)
    if scripted:                       # --scripted: no learned correction at all, the scripted wkF walk through the same loop (IMU, logging, holds)
        pol.residual_scale_deg = 0.0
    send_every = max(1, send_every if send_every else pol.send_every)   # explicit flag wins; else what the policy was trained with
    yaw_k = 0.0 if heading_blind_for(pol.onnx_path) else 1.0           # a heading-blind policy (sidecar) is fed yaw 0, as in training; the hold still reads the real yaw
    print(f"policy: {os.path.basename(pol.onnx_path)}"
          f"  (joint command every {send_every} tick{'s' if send_every != 1 else ''})", flush=True)
    pol.set_command(fwd=cmd_fwd, yaw=0.0)
    guard = ThermalGuard(enabled=thermal_guard, on_announce=_speak_best_effort)

    carpet_det = speed_est = None
    _carpet_prev = "normal"
    if carpet and CarpetDetector is not None:
        carpet_det = CarpetDetector()
        speed_est = ZuptSpeedEstimator()
        print("[carpet] detector ON -- NOTE: forward-speed estimate needs the "
              "6-axis IMU accel plumbed (currently inert); thresholds untuned.", flush=True)

    ring = None
    wd = None
    if diag is not None and not in_service:
        diag.start_session("gait", policy_path=getattr(pol, "onnx_path", None),
                           extra={"cmd_fwd": cmd_fwd, "hz": hz})
        diag.install_excepthook()
        bridge_stdlib_logging()
        ring = diag.attach_ring(RingBuffer(seconds=15, hz=hz))
        try:
            from pi_pipeline.diag.watchdog import Watchdog, WatchdogConfig
            from pi_pipeline.diag.sysmon import Sysmon
            wd = Watchdog(WatchdogConfig(stall_after_s=max(0.25, 4.0 / hz)),
                          on_stall=lambda: _send(lk, "d"), sysmon=Sysmon())
            wd.start()
        except Exception:
            wd = None
    _guard_prev = "ok"
    _skill_prev = "cruise"
    if skill_layer is not None:
        skill_layer.reset()
        print("[skills] vision-skill layer ACTIVE"
              + ("" if vision is not None else " (no feed -- terrain always clear)"),
              flush=True)

    if foot_trim is None and not scripted and not foot_hold and not heading_hold and steer_const is None:     # the everyday policy walk: the measured constant trim (heading_hold.DEFAULT_TRIMS)
        foot_trim = _hh.default_foot_trim(getattr(pol, "onnx_path", None))
        if foot_trim:
            print(f"[steer] constant foot trim {foot_trim} (G2_FOOT_TRIM=off disables)", flush=True)
    autolog_run, end_reason = None, ["other"]
    if not log_path:                     # no explicit --log: every policy walk (voice, exploration, command line) is captured automatically
        try:
            from pi_pipeline.telemetry import autolog as _autolog
            autolog_run = _autolog.new_run("policy_walk", policy=os.path.basename(str(getattr(pol, "onnx_path", "") or "")) or None, cmd_fwd=cmd_fwd, hz=hz,
                                           extra={"in_service": bool(in_service), "heading_hold": bool(heading_hold), "steer_const": steer_const, "foot_trim": foot_trim, "foot_hold": foot_hold, "scripted": bool(scripted)})
        except Exception:  # noqa: BLE001 -- never let logging stop a walk
            autolog_run = None
        if autolog_run is not None:
            log_path, log_extra = autolog_run.csv_path, True
    logf = None
    if log_path:
        logf = open(log_path, "w", buffering=1)      # line-buffered: a run that is stopped keeps its data
        logf.write("# run_gait log  cmd_fwd=%.3f hz=%.1f fw_balance=%s policy_yaw_sign=%+g\n"
                   % (cmd_fwd, hz, "off" if disable_firmware_balance else "on", POLICY_YAW_SIGN))
        logf.write("t,roll,pitch,yaw,gx,gy,gz," + ",".join(f"j{k}" for k in range(8))
                   + ",guard_state,hottest_j,hottest_tier,hottest_frac,duty_s" + (",steer_u" if (heading_hold or steer_const is not None or foot_hold) else "")
                   + (",ax,ay,az,imu_n,imu_age_s,volt" if log_extra else "") + "\n")
    hold = (_hh.HeadingHold(ff=hold_ff, kp=_hh.KP if hold_kp is None else hold_kp, ki=_hh.KI if hold_ki is None else hold_ki, u_max=_hh.U_MAX if hold_umax is None else hold_umax) if (heading_hold or steer_const is not None) else None)
    if foot_hold:                        # --foot-hold FOOT: the proportional heading hold on one front foot (gait/heading_hold.FootHold)
        hold = _hh.FootHold(foot=foot_hold, ff=_hh.default_foot_hold_ff())
    if hold is not None and steer_const is not None:
        hold.fixed_u = float(steer_const)
    steer_u = 0.0

    if disable_firmware_balance:
        # firmware balance OFF -> policy has full control. "gb", not bare "g":
        # bare "g" TOGGLES gyroBalanceQ, so after any session that already sent
        # it (or a crash that skipped the restore) it would turn balance ON --
        # and with balance on the firmware also runs its own lifted / fall /
        # push reflex skills over the policy (reaction.h dealWithExceptions).
        _send(lk, "gb")
        time.sleep(0.2)

    # go to the sim's reset stance, let it settle
    _send(lk, deploy_map.policy_deg_to_move_cmd(STAND_URDF_DEG))
    time.sleep(1.0)

    _send(lk, "gP")                # start continuous 6-axis stream (see probe_imu's note)
    time.sleep(0.2)

    # prime: read one good IMU frame for the reset
    feed = ImuFeed(imu_fmt, rate_mode=imu_rate)
    t0 = time.time()
    while feed.frame is None and time.time() - t0 < 3.0:
        feed.update(lk.poll_imu(), time.monotonic())
        time.sleep(0.01)
    if feed.frame is None:
        _send(lk, "d")
        raise SystemExit("no parseable IMU frame in 3 s -- run --probe-imu and fix parse_imu_line()")

    r, p_, y, gx, gy, gz = feed.frame
    # Yaw rebase: the IMU has no magnetometer, so firmware yaw is relative to
    # the power-on heading plus drift -- anything in +/-180. Training always
    # starts at yaw 0. Sim shows run20m_ppo ignores a yaw offset (0-180 deg,
    # 2026-09-22), but rebasing keeps any policy on the distribution it saw.
    yaw0 = y
    y = 0.0
    q = policy_quat(r, p_, yaw_k * y)
    pol.reset(np.deg2rad(np.array(STAND_URDF_DEG, dtype=float)), q, [gx, gy, gz])

    dt = 1.0 / hz
    n = int(seconds * hz) if seconds else None
    t_next = time.perf_counter()
    t_start = time.perf_counter()
    lat = []
    print(f"loop: cmd_fwd={cmd_fwd} m/s, {hz} Hz, {'forever' if n is None else str(n)+' ticks'}"
          + (f", logging -> {log_path}" if log_path else "") + ". Ctrl-C to stop.")
    tilt_since = None                 # fall guard: when |roll| or |pitch| first exceeded fall_abort_deg
    volt_chk = None
    last_volt = [float("nan")]
    if log_extra and not volt_every_s:
        volt_every_s = 5.0                   # the pack voltage is part of the extra log
    if volt_every_s:
        try:
            from pi_pipeline.config import settings as _st
            _lo, _cr = _st.battery_load_low_v, _st.battery_load_critical_v
        except Exception:  # noqa: BLE001
            _lo, _cr = 7.2, 6.8
        from pi_pipeline.power.battery import BatteryLevel, BatteryMonitor, LoadVoltageCheck
        volt_chk = LoadVoltageCheck(lambda c: _send(lk, c), getattr(lk, "pop_other", lambda: []),
                                    BatteryMonitor(_lo, _cr, confirm=2, hysteresis_v=0.15, repeat_s=60.0), every_s=volt_every_s,
                                    on_reading=(lambda v: (last_volt.__setitem__(0, v), diag.event("gait", "INFO", "battery.load", volts=round(v, 2)) if diag is not None else None)))
    try:
        i = 0
        while n is None or i < n:
            if stop_event is not None and stop_event.is_set():
                end_reason[0] = "stopped"
                break
            # never wait on the IMU: take what has arrived, step on the held frame
            now = time.monotonic()
            if volt_chk is not None:
                hit = volt_chk.tick(now)
                if hit is not None:
                    lvl, v = hit
                    print(f"!! battery {lvl.name.lower()} under load: {v:.2f} V", flush=True)
                    try:
                        (on_battery or (lambda l, vv: _speak_best_effort(
                            "My battery is critically low. Please charge me." if l is BatteryLevel.CRITICAL else "My battery is low.")))(lvl, v)
                    except Exception:  # noqa: BLE001
                        pass
                    if lvl is BatteryLevel.CRITICAL:
                        print("!! stopping before the battery browns out", flush=True)
                        end_reason[0] = "battery_critical"
                        break
            feed.update(lk.poll_imu(), now)
            imu_age = feed.age(now)
            if imu_age > IMU_STALE_S:
                print(f"!! no IMU frame for {imu_age:.2f} s -- stopping")
                if diag is not None:
                    diag.event("gait", "ERROR", "imu.stale", age_s=round(imu_age, 3))
                end_reason[0] = "imu_stale"
                break
            else:
                r, p_, y, gx, gy, gz = feed.frame
                if fall_abort_deg and max(abs(r), abs(p_)) > math.radians(fall_abort_deg):
                    tilt_since = tilt_since if tilt_since is not None else now
                    if now - tilt_since >= FALL_ABORT_S:       # down and staying down: stop driving the legs
                        print(f"!! fallen (tilt {math.degrees(max(abs(r), abs(p_))):.0f} deg > "
                              f"{fall_abort_deg:g} for {FALL_ABORT_S:g} s) -- resting", flush=True)
                        if diag is not None:
                            diag.event("gait", "ERROR", "fall.abort",
                                       roll_deg=round(math.degrees(r), 1), pitch_deg=round(math.degrees(p_), 1))
                        end_reason[0] = "fall"
                        break
                else:
                    tilt_since = None
                y = math.remainder(y - yaw0, 2.0 * math.pi)     # firmware convention, + = right (logged as is)
                q = policy_quat(r, p_, yaw_k * y)
                t0 = time.perf_counter()
                joint_deg = pol.step(q, [gx, gy, gz])
                if foot_trim is not None:            # --foot-trim: ONE foot's steps scaled, a fixed amount, no feedback (the per-foot steering test)
                    joint_deg = np.array(_hh.apply_foot_trims(joint_deg, foot_trim), dtype=int)
                if hold is not None:                 # steer by making one side's strides longer; yaw here is right-positive (the firmware convention)
                    steer_u = hold.update(y, dt, active=abs(cmd_fwd) >= 0.025)
                    joint_deg = np.array(_hh.apply_foot_trim(joint_deg, hold.foot, steer_u) if foot_hold else _hh.apply_stride_difference(joint_deg, steer_u), dtype=int)
                lat.append(time.perf_counter() - t0)

                if skill_layer is not None:
                    frame = vision.latest() if vision is not None else []
                    terrain = detections_to_terrain_reading(
                        frame, obstacle_labels=skill_labels)
                    joint_deg, sinfo = skill_layer.step(
                        joint_deg, gait_phase=pol.phase_frac(), terrain=terrain)
                    pol.set_command(fwd=cmd_fwd * sinfo.speed_scale)
                    if vision is not None:
                        vision.set_look_down(skill_layer.looking_down)
                    if sinfo.mode.value != _skill_prev:
                        print(f"[skills] {_skill_prev} -> {sinfo.mode.value} "
                              f"(src={sinfo.source.value}, spd x{sinfo.speed_scale:.2f}"
                              + (f", cliff={sinfo.cliff_action.value}" if sinfo.cliff_action
                                 and sinfo.cliff_action is not CliffAction.NONE else "")
                              + ")", flush=True)
                        if diag is not None:
                            diag.event("gait", "INFO", "skill.mode",
                                       mode=sinfo.mode.value, source=sinfo.source.value)
                        _skill_prev = sinfo.mode.value

                    # edge -> stop is handled by the HALT mode above; edge -> turn
                    # away / back up needs the firmware scripted turn gait.
                    if sinfo.frozen:
                        print(f"!! CliffGuard FROZEN: {skill_layer._cliff.last_reason} "
                              "-- stopping, needs a human", flush=True)
                        if diag is not None:
                            diag.event("gait", "ERROR", "cliff.frozen",
                                       reason=skill_layer._cliff.last_reason)
                        _speak_best_effort("I'm at an edge I can't get around. Come help me.")
                        _send(lk, "kbalance")
                        break
                    if _cliff_firmware_action(lk, sinfo.cliff_action, turn_burst_s):
                        pol.set_command(fwd=cmd_fwd)     # restore after the scaled/held cmd
                        t_next = time.perf_counter()     # the burst blocked; resync the clock
                        i += 1
                        continue

                if carpet_det is not None:
                    eff_cmd = cmd_fwd * (sinfo.speed_scale if skill_layer is not None else 1.0)
                    # HARDWARE: body-X accel isn't in the ypr+gyro IMU stream yet
                    # (--imu-format 6axis carries ax/ay/az). None -> estimator inert.
                    accel_fwd = None
                    v_meas = speed_est.update(accel_fwd, pol.phase_frac(), dt)
                    cact = carpet_det.update(eff_cmd, v_meas)
                    if cact != _carpet_prev:
                        if diag is not None:
                            diag.event("gait", "WARN", "carpet.mode",
                                       action=cact.value, reason=carpet_det.last_reason)
                        print(f"[carpet] {_carpet_prev} -> {cact.value}: {carpet_det.last_reason}",
                              flush=True)
                        if _carpet_prev == CarpetAction.CARPET_GAIT.value \
                                and cact is CarpetAction.NORMAL:
                            _send(lk, _opencat.STAND)              # re-anchor after the firmware gait
                            pol.reset(np.deg2rad(np.array(STAND_URDF_DEG, dtype=float)),
                                      q, [gx, gy, gz])
                        _carpet_prev = cact.value
                    if cact is CarpetAction.CARPET_GAIT:
                        _send(lk, _opencat.CARPET_WALK)            # firmware kcarpetF drives; skip the policy send
                        if wd is not None:
                            wd.beat()
                        i += 1
                        t_next += dt
                        continue
                    if cact is CarpetAction.BOOST_CMD:
                        pol.set_command(fwd=carpet_det.cmd_with_boost(eff_cmd))

                snap = guard.update(joint_deg, dt)
                joint_deg = guard.apply_soft(joint_deg, snap)   # Petoi-style per-joint ease-off (no-op unless a joint is stalling)
                if i % send_every == 0:      # V2/V2.1 were trained sending every 3rd tick (i@27)
                    _send(lk, deploy_map.policy_deg_to_move_cmd(joint_deg))
                if wd is not None:
                    wd.beat()

                if ring is not None:
                    ring.push(t=round(time.perf_counter() - t_start, 3),
                              roll=round(r, 4), pitch=round(p_, 4), yaw=round(y, 4),
                              gx=round(gx, 4), gy=round(gy, 4), gz=round(gz, 4),
                              step_ms=round(lat[-1] * 1e3, 2),
                              guard=snap.state, hot_j=snap.hottest_j, hot_tier=int(snap.hottest_tier),
                              hot_frac=round(snap.hottest_frac, 3), duty_s=round(snap.duty_s, 1),
                              **{f"j{k}": int(v) for k, v in enumerate(joint_deg)})
                if diag is not None and snap.state != _guard_prev:
                    if snap.state in _THERMAL_EVENT:
                        nm, lv = _THERMAL_EVENT[snap.state]
                        diag.event("gait", lv, nm, reason=snap.tripped_reason,
                                   hottest_j=snap.hottest_j, hottest_frac=round(snap.hottest_frac, 3),
                                   duty_s=round(snap.duty_s, 1))
                    elif snap.state == "ok" and _guard_prev in ("cooldown", "warn", "soft"):
                        diag.event("gait", "INFO", "servo.thermal_recover",
                                   hottest_frac=round(snap.hottest_frac, 3))
                    _guard_prev = snap.state

                if snap.state == "cooldown":
                    # danger zone: lie down, all servos off load, until cooled
                    print(f"!! thermal COOLDOWN: {snap.tripped_reason} -- lying down to cool", flush=True)
                    _send(lk, "d")
                    rested = 0.0
                    while rested < 120.0:
                        time.sleep(guard.cooldown_seconds)
                        guard.note_rest(guard.cooldown_seconds)
                        rested += guard.cooldown_seconds
                        if guard.is_cool():
                            break
                    print(f"   cooled after {rested:.0f}s -- resuming", flush=True)
                    _send(lk, deploy_map.policy_deg_to_move_cmd(STAND_URDF_DEG))
                    time.sleep(1.0)
                    pol.reset(np.deg2rad(np.array(STAND_URDF_DEG, dtype=float)), q, [gx, gy, gz])
                    t_next = time.perf_counter()

                if logf:
                    logf.write("%.4f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%s,%s,%d,%d,%.3f,%.0f%s\n" % (
                        time.perf_counter() - t_start, r, p_, y, gx, gy, gz,
                        ",".join(str(int(v)) for v in joint_deg),
                        snap.state, snap.hottest_j, int(snap.hottest_tier),
                        snap.hottest_frac, snap.duty_s, ((",%.4f" % steer_u) if hold is not None else "") + _extra_cols(feed, now, last_volt[0], log_extra)))
            t_next += dt
            slack = t_next - time.perf_counter()
            if slack > 0:
                time.sleep(slack)
            else:
                t_next = time.perf_counter()     # fell behind; resync
            i += 1
        else:
            end_reason[0] = "complete"       # the loop ran its full length without a break
    except KeyboardInterrupt:
        end_reason[0] = "interrupted"
        print("\n^C")
    except BaseException as e:                       # noqa: BLE001 -- never leave servos loaded
        end_reason[0] = "error"
        if diag is not None:
            diag.event("gait", "FATAL", "loop.exception", err=repr(e))
        raise
    finally:
        if wd is not None:
            wd.stop()
        if not in_service:
            _send(lk, "gp")    # stream off (lowercase C_PRINT_OFF, not a toggle)
        if disable_firmware_balance and not in_service:
            _send(lk, "gB")    # restore the firmware default (balance + reflexes on) BEFORE the rest: sent right after `d` it left G2 standing
            time.sleep(0.3)
        if getattr(stop_event, "rest", True):
            _send(lk, "d")     # rest, last, then a pause so the board has it before the port closes
            time.sleep(0.5)
        elif getattr(stop_event, "end_pose", None) == "balance":
            _send(lk, "kbalance")     # an exploration leg ended with another about to start (2026-10-09, user): hold a balanced stand, not the last stride; the session rests at its end
            time.sleep(0.8)
        if vision is not None:
            vision.close()
        if logf:
            logf.close()
            print(f"log written: {log_path}")
        if autolog_run is not None:
            autolog_run.finish(end_reason[0], last_volt_v=None if last_volt[0] != last_volt[0] else round(last_volt[0], 2))
        if diag is not None and not in_service:
            diag.close()
    if lat:
        a = np.array(lat) * 1e3
        print(f"policy step: {a.mean():.2f} ms mean, {a.max():.2f} ms max ({len(lat)} ticks)")
    print("sent rest.")
    return end_reason[0]            # complete / stopped / fall / imu_stale / battery_critical / interrupted / error / other


def _latest_imu_line(lk):
    """Newest IMU line received since the last call (non-blocking), or None."""
    lines = lk.poll_imu()
    return lines[-1] if lines else None


def _send(lk, cmd):
    """Fire-and-forget serial send -- no reply wait."""
    lk.send(cmd, read_reply=False, settle=0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--hz", type=float, default=CONTROL_HZ)
    ap.add_argument("--cmd", type=float, default=0.10, help="forward speed command, m/s")
    ap.add_argument("--policy", default=None, metavar="ONNX",
                    help="policy .onnx to run instead of residual_policy.DEFAULT_POLICY "
                         "(its .onnx.json sidecar must sit next to it). Does not change the default.")
    ap.add_argument("--hold-ff", type=float, default=0.0, metavar="U", help="--heading-hold: feed-forward stride difference added to the feedback (u > 0 = longer LEFT strides = a right turn)")
    ap.add_argument("--hold-kp", type=float, default=None, metavar="K", help="--heading-hold: proportional gain, u per degree of heading error (default heading_hold.KP)")
    ap.add_argument("--hold-ki", type=float, default=None, metavar="K", help="--heading-hold: integral gain, u per degree-second (default heading_hold.KI)")
    ap.add_argument("--hold-umax", type=float, default=None, metavar="U", help="--heading-hold / --steer-const: largest stride difference (default heading_hold.U_MAX = 0.20)")
    ap.add_argument("--foot-hold", default=None, metavar="FOOT", choices=tuple(_hh.FOOT_JOINT) + ("off",),
                    help="closed-loop heading hold on ONE foot (proportional to heading error, with deadband and ease-off; gait/heading_hold.FootHold). Default: ON, the front-left foot (G2_FOOT_HOLD); 'off' turns it off")
    ap.add_argument("--scripted", action="store_true", help="zero the learned residual: the scripted wkF walk through the full loop (IMU, logging, holds)")
    ap.add_argument("--foot-trim", default=None, metavar="FOOT=G",
                    help="scale ONE foot's step by (1 + G) with no feedback, e.g. bl=+0.25 (feet: fl fr br bl): the per-foot steering test. Also logs which foot in the sidecar.")
    ap.add_argument("--steer-const", type=float, default=None, metavar="U",
                    help="hold the stride difference u fixed (no feedback, limited to +-0.20): + = longer right strides. Measures the lever's real sign / authority")
    ap.add_argument("--heading-hold", action="store_true",
                    help="steer back toward the starting heading by lengthening one side's strides (gait/heading_hold.py); off by default")
    ap.add_argument("--fall-abort-deg", type=float, default=60.0, metavar="DEG",
                    help="rest and stop if |roll| or |pitch| stays above DEG for 0.3 s (a fall); 0 disables")
    ap.add_argument("--send-every", type=int, default=None, metavar="N",
                    help="send a joint command every Nth control tick. Default: what the policy "
                         "was trained with (its .onnx.json `cmd_send_every_n`; V2/V2.1 = 3, i@27)")
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = run until Ctrl-C")
    ap.add_argument("--imu-format", default="auto", choices=("auto", "ypr", "rpy", "6axis"))
    ap.add_argument("--imu-rate", default="zero", choices=("fd", "zero"),
                    help="roll/pitch rate fed to the policy: fd = finite difference of "
                         "consecutive 5 Hz IMU frames, zero = none (stream has no gyro)")
    ap.add_argument("--probe-imu", action="store_true")
    ap.add_argument("--probe-imu-load", action="store_true",
                    help="like --probe-imu, but sends the neutral stand at --hz while "
                         "counting IMU lines, matching the real control loop's shared-bus "
                         "traffic instead of a quiet/idle bus")
    ap.add_argument("--openloop", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="full loop with synthetic IMU and no serial -- rate check")
    ap.add_argument("--cycles", type=int, default=6, help="--openloop: wkF cycles")
    ap.add_argument("--lift-scale", type=float, default=1.0, metavar="K",
                    help="--openloop: scale the wkF swing about its mean (1.3/1.6/2.0 -> ~14/21/31 mm foot lift, est.)")
    ap.add_argument("--lift-joints", default="all", choices=("all", "knees"),
                    help="--openloop: which joints --lift-scale applies to (knees keeps the stride ~unchanged)")
    ap.add_argument("--shoulder-scale", type=float, default=1.0, metavar="S",
                    help="--openloop with --lift-joints knees: scale the shoulder swing (0.7 holds the stride near wkF's)")
    ap.add_argument("--volt-every", type=float, default=0.0, metavar="S",
                    help="--openloop: log the battery voltage every S seconds during the walk (0 = off)")
    ap.add_argument("--log-extra", action="store_true",
                    help="policy walks: also log accel (m/s^2), the IMU frame counter and age, and the pack voltage (asked every 5 s)")
    ap.add_argument("--ramp-cycles", type=float, default=0.0, metavar="N",
                    help="--openloop: blend the lift/shoulder scaling in from x1 over N cycles (avoids a jump from the stand pose)")
    ap.add_argument("--openloop-balance-off", action="store_true",
                    help="--openloop: send gb first so the walk is purely scripted (no firmware gyro assist)")
    ap.add_argument("--keep-firmware-balance", action="store_true",
                    help="do NOT send 'gb' -- leave the firmware gyro-assist layer on under the policy")
    ap.add_argument("--log", default=None,
                    help="write a per-tick CSV (t, rpy, gyro, 8 joint deg) for real_vs_sim / sysid_replay")
    ap.add_argument("--carpet", action="store_true",
                    help="run CarpetDetector -- boost the speed cmd / hand off to "
                         "firmware kcarpetF on sustained slip. Inert until the "
                         "6-axis IMU accel is plumbed + thresholds tuned on carpet.")
    ap.add_argument("--no-thermal-guard", action="store_true",
                    help="disable the conservative servo thermal guard (WARN speech + rare auto-cooldown)")
    ap.add_argument("--ignore-features", action="store_true",
                    help="don't consult G2_FEATURES (run even if gait is flagged off)")
    ap.add_argument("--skills", action="store_true",
                    help="run the Phase E vision-skill layer over the walk "
                         "(GaitSelector + SkillSwitch + CliffGuard). Requires "
                         "features.vision (G2_FEATURES=\"+vision\") -- gated OFF by "
                         "default because no obstacle/edge detector is deployed yet. "
                         "--dry-run bypasses the gate with a mock feed.")
    ap.add_argument("--skills-feed", default="serial", choices=("serial", "mock"),
                    help="--skills detection source: 'serial' (Grove Vision AI on its own "
                         "USB port) or 'mock' (a scripted approaching box, bench check)")
    ap.add_argument("--skills-vision-port", default="/dev/ttyACM0",
                    help="--skills-feed serial: the vision module's serial port")
    ap.add_argument("--skills-vision-baud", type=int, default=921600)
    ap.add_argument("--no-cliff-guard", action="store_true",
                    help="--skills: drop the CliffGuard edge reflex (no downward sensor wired)")
    ap.add_argument("--skills-turn-burst", type=float, default=1.0,
                    help="--skills: seconds to run the firmware turn gait when CliffGuard "
                         "asks to turn away from an edge (then the policy loop resumes)")
    args = ap.parse_args()

    thermal_on = not args.no_thermal_guard
    vision_flag = None
    if not args.ignore_features:
        try:
            from pi_pipeline.features import features, log_summary
            log_summary()
            if features.gait == "off":
                print("features: gait is flagged off (G2_FEATURES). "
                      "Use --ignore-features to run anyway.")
                return
            thermal_on = thermal_on and features.thermal_guard
            vision_flag = bool(features.vision)
        except Exception as e:  # noqa: BLE001
            print(f"features: not consulted ({e!r})")

    if args.skills and vision_flag is False and not args.dry_run:
        print("--skills needs features.vision, but no obstacle/edge detector is "
              "deployed (the camera runs a single-class face model). "
              "Set G2_FEATURES=\"+vision\" once one exists, or use --dry-run "
              "(mock feed) / --ignore-features to force.")
        return

    skill_layer = vision = None
    if args.skills:
        if SkillLayer is None:
            raise SystemExit("--skills: pi_pipeline.vision / .gait imports failed "
                             "(missing deps?) -- can't build the skill layer")
        skill_layer = build_skill_layer(with_cliff_guard=not args.no_cliff_guard)
        # dry-run always uses the mock feed (no camera on a dev box)
        feed_kind = "mock" if args.dry_run else args.skills_feed
        feed = _make_vision_feed(feed_kind, args.skills_vision_port,
                                 args.skills_vision_baud)
        vision = _LatestFrame(feed).start()

    if args.dry_run:
        try:
            dry_run(args.cmd, args.seconds, args.hz, skill_layer=skill_layer, vision=vision)
        finally:
            if vision is not None:
                vision.close()
        return

    lk = _open_link(args.port, args.baud)
    try:
        if args.probe_imu:
            probe_imu(lk, 5.0)
        elif args.probe_imu_load:
            probe_imu_under_load(lk, 5.0, args.hz)
        elif args.openloop:
            openloop(lk, args.cycles, args.hz, lift_scale=args.lift_scale, log_path=args.log,
                     fall_abort_deg=args.fall_abort_deg, balance_off=args.openloop_balance_off,
                     lift_joints=args.lift_joints, shoulder_scale=args.shoulder_scale,
                     ramp_cycles=args.ramp_cycles, volt_every_s=args.volt_every,
                     send_every=args.send_every if args.send_every else 3,
                     foot_trim=_hh.parse_foot_trims(args.foot_trim))   # default: the policy loop's cadence (i@27)
        else:
            run(lk, args.cmd, args.seconds, args.hz, args.imu_format,
                disable_firmware_balance=not args.keep_firmware_balance, log_path=args.log,
                thermal_guard=thermal_on, skill_layer=skill_layer, vision=vision,
                turn_burst_s=args.skills_turn_burst, carpet=args.carpet, imu_rate=args.imu_rate,
                policy_path=args.policy, send_every=args.send_every,
                fall_abort_deg=args.fall_abort_deg, heading_hold=args.heading_hold, steer_const=args.steer_const, foot_trim=_hh.parse_foot_trims(args.foot_trim), foot_hold=(None if args.foot_hold == "off" else (args.foot_hold or _hh.default_foot_hold())), scripted=args.scripted,
                hold_ff=args.hold_ff, hold_kp=args.hold_kp, hold_umax=args.hold_umax, hold_ki=args.hold_ki,
                log_extra=args.log_extra, **({"volt_every_s": args.volt_every} if args.volt_every > 0 else {}))
    finally:
        try:
            lk.close()
        except Exception:
            pass
        if vision is not None:
            vision.close()


if __name__ == "__main__":
    main()
