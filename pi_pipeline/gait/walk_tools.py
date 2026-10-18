"""The bench walks of run_gait.py: IMU rate probes, the open-loop scripted walk (`--openloop`) and the no-hardware dry run (`--dry-run`).
Split out of run_gait.py 2026-10-18 (no behaviour change); run_gait re-exports every name."""
from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (_HERE, os.path.join(_HERE, ".."), os.path.join(_HERE, "..", "..")):     # run by path like run_gait.py: siblings, `link`, the repo root
    if _p not in sys.path:
        sys.path.insert(0, _p)

import time

import numpy as np

import deploy_map                                             # noqa: E402
import heading_hold as _hh                                    # noqa: E402
import standup as _standup                                    # noqa: E402
from imu_parse import parse_imu_line                          # noqa: E402
from residual_policy import ResidualGaitPolicy, CONTROL_HZ    # noqa: E402
from walk_common import FALL_ABORT_S, STAND_URDF_DEG, _send, euler_to_quat   # noqa: E402

try:                                                          # the vision terrain reading for --dry-run --skills (optional)
    from pi_pipeline.vision.gait_selector import detections_to_terrain_reading  # noqa: E402
except Exception:                                             # noqa: BLE001
    detections_to_terrain_reading = None


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
             ref_name="wkf", stop_event=None, sleep=time.sleep, clock=time.monotonic):
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
    ref = np.load(os.path.join(_HERE, f"{ref_name}_ref.npy"))   # (100,8) rad, URDF order; `ref_name` picks another scripted base gait (hsF = the stable high-step, 2026-10-09)
    m = ref.mean(axis=0)
    scale = np.ones(8)
    scale[[1, 3, 5, 7] if lift_joints == "knees" else slice(None)] = lift_scale
    scale[[0, 2, 4, 6]] *= shoulder_scale if lift_joints == "knees" else 1.0
    base = np.load(os.path.join(_HERE, "wkf_ref.npy")) if ref_name != "wkf" else ref        # the ramp blends the plain wkF into the chosen gait
    ref = m + (ref - m) * scale
    ramp_n = int(ramp_cycles * len(ref))
    dt = 1.0 / hz
    print(f"open-loop wkF playback: {cycles} cycles, {hz} Hz, lift x{lift_scale:g}"
          f"{' (knees only' + (f', shoulders x{shoulder_scale:g}' if shoulder_scale != 1.0 else '') + ')' if lift_joints == 'knees' else ''}"
          f"{', balance off' if balance_off else ''}. Ctrl-C to stop.")
    log = open(log_path, "w") if log_path else None
    t_start, tilt_since, fell = clock(), None, False
    reason = "complete"
    try:
        if balance_off:
            _send(lk, "gb")
            sleep(0.2)
        _standup.ramp_to_stand(lambda c: _send(lk, c), deploy_map.policy_deg_to_move_cmd, STAND_URDF_DEG, sleep, getattr(lk, "last_motion_command", None))
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
                    reason = "fall"
                    return reason
                if stop_event is not None and stop_event.is_set():
                    reason = "stopped"
                    return reason
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
        if stop_event is not None and not getattr(stop_event, "rest", True):
            if getattr(stop_event, "end_pose", None) == "balance":
                _send(lk, "kbalance")        # an exploration leg ending with another about to start: the standing pose, not lying down
            sleep(0.8)
        else:
            _send(lk, "d")
            sleep(0.5)                # a pause so the board has the rest command before the port closes (2026-10-07: without it G2 stayed standing after a scripted walk)
    print("done (sent rest)." if stop_event is None or getattr(stop_event, "rest", True) else "done (standing).")
    return "complete"


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
