"""On-Pi control loop: run run20m_ppo on the real robot.

    python -m pi_pipeline.gait.run_gait --probe-imu           # see what the BiBoard streams
    python -m pi_pipeline.gait.run_gait --openloop            # play wkf_ref.npy, no policy (calibration)
    python -m pi_pipeline.gait.run_gait --cmd 0.10            # walk forward at 0.10 m/s
    python -m pi_pipeline.gait.run_gait --cmd 0.0 --seconds 5 # stand + hold

Pipeline per tick (~80 Hz):
    parse IMU line -> (roll,pitch,yaw rad, gyro xyz rad/s)
    quat = euler_to_quat(rpy)
    joint_deg_urdf = ResidualGaitPolicy.step(quat, gyro)
    "m8 <d> 12 <d> ..."  = deploy_map.policy_deg_to_move_cmd(joint_deg_urdf)
    serial.send(cmd)

The BiBoard streams 6-axis IMU after the `V` token. The exact line format
differs by firmware build -- run --probe-imu first and, if it doesn't match
`parse_imu_line` below, adjust that one function (or pass --imu-format).

SAFETY: on any of {IMU parse failures piling up, Ctrl-C, loop overrun}, the loop
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
sys.path.insert(0, os.path.join(_HERE, ".."))          # for `link`
sys.path.insert(0, os.path.join(_HERE, "..", ".."))    # repo root, for `pi_pipeline.diag`

from residual_policy import ResidualGaitPolicy, CONTROL_HZ   # noqa: E402
import deploy_map                                             # noqa: E402
from thermal_guard import ThermalGuard                        # noqa: E402

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


def parse_imu_line(line, fmt="auto", deg_in=True):
    """Return (roll, pitch, yaw [rad], gx, gy, gz [rad/s]) or None if this line
    isn't an IMU frame.

    Handles the common OpenCat `print6Axis` shapes:
      - "ypr <yaw> <pitch> <roll>"                (DMP, degrees)
      - "<ax> <ay> <az> <gx> <gy> <gz>"           (raw 6-axis)
      - "<yaw> <pitch> <roll> <gx> <gy> <gz>"     (ypr + gyro, if enabled)
    Adjust here once --probe-imu shows the real format.
    """
    s = line.strip().replace(",", " ")
    if not s:
        return None
    toks = s.split()
    try:
        if toks and toks[0].lower() in ("ypr", "ang"):
            nums = [float(x) for x in toks[1:4]]
            yaw, pitch, roll = nums
            g = [0.0, 0.0, 0.0]
        else:
            nums = [float(x) for x in toks]
            if len(nums) == 3:                      # roll pitch yaw (or ypr)
                if fmt == "ypr":
                    yaw, pitch, roll = nums
                else:
                    roll, pitch, yaw = nums
                g = [0.0, 0.0, 0.0]
            elif len(nums) >= 6:
                if fmt == "6axis":                  # ax ay az gx gy gz -> no orientation
                    return None
                yaw, pitch, roll = nums[0:3]
                g = nums[3:6]
            else:
                return None
    except ValueError:
        return None
    k = math.pi / 180.0 if deg_in else 1.0
    return (roll * k, pitch * k, yaw * k, g[0] * k, g[1] * k, g[2] * k)


# --------------------------------------------------------------------- loop
STAND_URDF_DEG = [50, 0, 50, 0, 50, 0, 50, 0]     # matches env.reset() start pose


def _open_link(port, baud):
    from link.serial_link import SerialLink
    lk = SerialLink(port, baud=baud)
    if not lk.connect():
        raise SystemExit(f"could not open {port} @ {baud}")
    return lk


def probe_imu(lk, seconds):
    print("sending 'V' (toggle IMU stream); printing raw lines for", seconds, "s")
    _send(lk, "V")
    t0 = time.time()
    while time.time() - t0 < seconds:
        line = lk.read_line()
        if line:
            print(repr(line))
    _send(lk, "V")
    print("stream toggled off. Match parse_imu_line() to the format above.")


def openloop(lk, cycles, hz):
    ref = np.load(os.path.join(_HERE, "wkf_ref.npy"))          # (100,8) rad, URDF order
    dt = 1.0 / hz
    print(f"open-loop wkF playback: {cycles} cycles, {hz} Hz. Ctrl-C to stop.")
    try:
        for c in range(cycles):
            for frame in ref:
                deg = np.rint(np.rad2deg(frame)).astype(int)
                _send(lk, deploy_map.policy_deg_to_move_cmd(deg))
                time.sleep(dt)
    finally:
        _send(lk, "d")
    print("done (sent rest).")


def dry_run(cmd_fwd, seconds, hz):
    """Full 80 Hz loop with synthetic (near-level) IMU and NO serial -- checks the
    loop holds rate on this machine before any hardware exists."""
    pol = ResidualGaitPolicy()
    pol.set_command(fwd=cmd_fwd, yaw=0.0)
    rng = np.random.default_rng(0)

    def fake_imu():
        r, p_, y = rng.normal(0, 0.05, 3)
        return euler_to_quat(r, p_, y), rng.normal(0, 0.3, 3)

    q, g = fake_imu()
    pol.reset(np.deg2rad(np.array(STAND_URDF_DEG, dtype=float)), q, g)
    dt = 1.0 / hz
    n = int((seconds or 5.0) * hz)
    step_ms, loop_ms = [], []
    t_next = time.perf_counter()
    t_loop = time.perf_counter()
    print(f"dry-run: {hz} Hz x {n} ticks, cmd_fwd={cmd_fwd}. No serial.")
    for _ in range(n):
        q, g = fake_imu()
        t0 = time.perf_counter()
        jd = pol.step(q, g)
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


def run(lk, cmd_fwd, seconds, hz, imu_fmt, disable_firmware_balance, log_path=None,
        thermal_guard=True):
    pol = ResidualGaitPolicy()
    pol.set_command(fwd=cmd_fwd, yaw=0.0)
    guard = ThermalGuard(enabled=thermal_guard, on_announce=_speak_best_effort)

    ring = None
    if diag is not None:
        diag.start_session("gait", policy_path=getattr(pol, "onnx_path", None),
                           extra={"cmd_fwd": cmd_fwd, "hz": hz})
        bridge_stdlib_logging()
        ring = diag.attach_ring(RingBuffer(seconds=15, hz=hz))
    _guard_prev = "ok"

    logf = None
    if log_path:
        logf = open(log_path, "w")
        logf.write("# run_gait log  cmd_fwd=%.3f hz=%.1f fw_balance=%s\n"
                   % (cmd_fwd, hz, "off" if disable_firmware_balance else "on"))
        logf.write("t,roll,pitch,yaw,gx,gy,gz," + ",".join(f"j{k}" for k in range(8))
                   + ",guard_state,hottest_j,hottest_frac,duty_s\n")

    if disable_firmware_balance:
        _send(lk, "g")            # toggle firmware gyro assist OFF -> policy has full control
        time.sleep(0.2)

    # go to the sim's reset stance, let it settle
    _send(lk, deploy_map.policy_deg_to_move_cmd(STAND_URDF_DEG))
    time.sleep(1.0)

    _send(lk, "V")                # start IMU stream
    time.sleep(0.2)

    # prime: read one good IMU frame for the reset
    rpy_g = None
    t0 = time.time()
    while rpy_g is None and time.time() - t0 < 3.0:
        line = _readline(lk)
        if line:
            rpy_g = parse_imu_line(line, imu_fmt)
    if rpy_g is None:
        _send(lk, "d")
        raise SystemExit("no parseable IMU frame in 3 s -- run --probe-imu and fix parse_imu_line()")

    r, p_, y, gx, gy, gz = rpy_g
    q = euler_to_quat(r, p_, y)
    pol.reset(np.deg2rad(np.array(STAND_URDF_DEG, dtype=float)), q, [gx, gy, gz])

    dt = 1.0 / hz
    n = int(seconds * hz) if seconds else None
    miss = 0
    t_next = time.perf_counter()
    t_start = time.perf_counter()
    lat = []
    print(f"loop: cmd_fwd={cmd_fwd} m/s, {hz} Hz, {'forever' if n is None else str(n)+' ticks'}"
          + (f", logging -> {log_path}" if log_path else "") + ". Ctrl-C to stop.")
    try:
        i = 0
        while n is None or i < n:
            line = _readline(lk)
            parsed = parse_imu_line(line, imu_fmt) if line else None
            if parsed is None:
                miss += 1
                if miss > 20:
                    print("!! 20 consecutive IMU misses -- stopping")
                    if diag is not None:
                        diag.event("gait", "ERROR", "imu.stale", consecutive_misses=miss)
                    break
            else:
                miss = 0
                r, p_, y, gx, gy, gz = parsed
                q = euler_to_quat(r, p_, y)
                t0 = time.perf_counter()
                joint_deg = pol.step(q, [gx, gy, gz])
                lat.append(time.perf_counter() - t0)

                snap = guard.update(joint_deg, dt)
                joint_deg = guard.apply_soft(joint_deg, snap)   # Petoi-style per-joint ease-off (no-op unless a joint is stalling)
                _send(lk, deploy_map.policy_deg_to_move_cmd(joint_deg))

                if ring is not None:
                    ring.push(t=round(time.perf_counter() - t_start, 3),
                              roll=round(r, 4), pitch=round(p_, 4), yaw=round(y, 4),
                              gx=round(gx, 4), gy=round(gy, 4), gz=round(gz, 4),
                              step_ms=round(lat[-1] * 1e3, 2),
                              guard=snap.state, hot_j=snap.hottest_j,
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
                    logf.write("%.4f,%.5f,%.5f,%.5f,%.5f,%.5f,%.5f,%s,%s,%d,%.3f,%.0f\n" % (
                        time.perf_counter() - t_start, r, p_, y, gx, gy, gz,
                        ",".join(str(int(v)) for v in joint_deg),
                        snap.state, snap.hottest_j, snap.hottest_frac, snap.duty_s))
            t_next += dt
            slack = t_next - time.perf_counter()
            if slack > 0:
                time.sleep(slack)
            else:
                t_next = time.perf_counter()     # fell behind; resync
            i += 1
    except KeyboardInterrupt:
        print("\n^C")
    except BaseException as e:                       # noqa: BLE001 -- never leave servos loaded
        if diag is not None:
            diag.event("gait", "FATAL", "loop.exception", err=repr(e))
        raise
    finally:
        _send(lk, "V")     # stream off
        _send(lk, "d")     # rest
        if logf:
            logf.close()
            print(f"log written: {log_path}")
        if diag is not None:
            diag.close()
    if lat:
        a = np.array(lat) * 1e3
        print(f"policy step: {a.mean():.2f} ms mean, {a.max():.2f} ms max ({len(lat)} ticks)")
    print("sent rest.")


def _readline(lk):
    return lk.read_line() or None


def _send(lk, cmd):
    lk.send(cmd, read_reply=False, settle=0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/serial0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--hz", type=float, default=CONTROL_HZ)
    ap.add_argument("--cmd", type=float, default=0.10, help="forward speed command, m/s")
    ap.add_argument("--seconds", type=float, default=0.0, help="0 = run until Ctrl-C")
    ap.add_argument("--imu-format", default="auto", choices=("auto", "ypr", "rpy", "6axis"))
    ap.add_argument("--probe-imu", action="store_true")
    ap.add_argument("--openloop", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="full loop with synthetic IMU and no serial -- rate check")
    ap.add_argument("--cycles", type=int, default=6, help="--openloop: wkF cycles")
    ap.add_argument("--keep-firmware-balance", action="store_true",
                    help="do NOT send 'g' -- leave the firmware gyro-assist layer on under the policy")
    ap.add_argument("--log", default=None,
                    help="write a per-tick CSV (t, rpy, gyro, 8 joint deg) for real_vs_sim / sysid_replay")
    ap.add_argument("--no-thermal-guard", action="store_true",
                    help="disable the conservative servo thermal guard (WARN speech + rare auto-cooldown)")
    args = ap.parse_args()

    if args.dry_run:
        dry_run(args.cmd, args.seconds, args.hz)
        return

    lk = _open_link(args.port, args.baud)
    try:
        if args.probe_imu:
            probe_imu(lk, 5.0)
        elif args.openloop:
            openloop(lk, args.cycles, args.hz)
        else:
            run(lk, args.cmd, args.seconds, args.hz, args.imu_format,
                disable_firmware_balance=not args.keep_firmware_balance, log_path=args.log,
                thermal_guard=not args.no_thermal_guard)
    finally:
        try:
            lk.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
