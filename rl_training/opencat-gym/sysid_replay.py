"""Sim-to-real gap: replay a real robot log's joint commands OPEN-LOOP in a
minimal pybullet sim and diff the body-tilt / angular-rate trajectories against
the real IMU. No policy, no joint feedback needed -- just the commands (logged)
and the IMU (logged).

    # from a calibration run
    python sysid_replay.py --log sysid_20260918.csv
    # from an H1 walk
    python sysid_replay.py --log run_rl_C1_1.csv
    # find the sim actuator params that best match reality
    python sysid_replay.py --log sysid_20260918.csv --fit

    # H10 -- carpet resistance calibration, two passes:
    #  1. fit the actuator model on a HARD-FLOOR log first (as above), note the
    #     best mf/kp/kd/lat
    #  2. lock those, fit ONLY the carpet surface against a CARPET log:
    python sysid_replay.py --log sysid_carpet_20260918.csv --fit-surface \\
        --max-force 0.20 --kp 0.1 --kd 1.0 --latency 0   # <- locked from step 1

Log format (from run_gait.py --log or pi_pipeline/gait/sysid_collect.py):
    t,roll,pitch,yaw,gx,gy,gz,j0,j1,j2,j3,j4,j5,j6,j7[,phase]
    angles/rates in RADIANS, joints in DEGREES, URDF order.

The sim here mirrors opencat_gym_env's physics: models/bittle_esp32.urdf,
g=-9.81, 240 Hz, POSITION_CONTROL, a welded 75 g rear payload. What --fit
sweeps: motor maxForce, position gain, velocity gain, and a command-latency in
control steps. Output: the corrected values + how to put them in the env.

--fit-surface sweeps the flat-carpet ground model instead (mirrors
opencat_gym_env.py's `_carpet_floor` block exactly): CARPET_SOFT and the carpet
lateralFriction. Fit this SECOND, holding the actuator params fixed -- doing
both at once lets carpet resistance leak into the wrong parameters (e.g.
inflating max_force to compensate for foot drag instead of attributing it to
the surface). When the log has a `phase` column, both --fit and --fit-surface
print a per-phase-family gap breakdown: a residual concentrated in the
`static` (plant/hold) family points at the contact stiffness/damping term; one
spread evenly across the `wkf` (dynamic swing+stance) family instead points at
a mechanism the contact model can't represent at all -- fiber drag on a foot
moving through pile above the floor plane -- which would need a new term, not
just a CARPET_SOFT refit. See docs/rl-runs/hardware-gated-training-backlog.md H10.
"""
import argparse
import itertools
import os
import sys

import numpy as np
import pybullet as p
import pybullet_data

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
PAYLOAD_MASS = 0.075
PAYLOAD_POS = (-0.020, 0.0, 0.025)
SUBSTEP_HZ = 240.0

# Mirrors opencat_gym_env.py's `_carpet_floor` block. Training randomizes each
# of these per-episode (np.random.uniform); replay needs one fixed value per
# trial for a coordinate-descent fit to converge, so we use the range midpoint
# as the un-fit baseline and let --fit-surface search carpet_soft/friction
# directly. Keep these three ranges in sync with opencat_gym_env.py by hand --
# there's no shared import between the two files.
_CARPET_STIFFNESS_RANGE = (4e4, 1.2e5)
_CARPET_DAMPING_RANGE = (300.0, 1500.0)
_CARPET_FRICTION_MID = 1.1                      # opencat_gym_env.py draws U(0.9, 1.3)


def _phase_family(tag):
    """Bucket the fine-grained phase tags sysid_collect.py writes (static0..4,
    wkf_c0_f0..wkf_c2_f99, stand0/1) into the 3 families the H10 diagnostic
    cares about."""
    if not tag:
        return "other"
    if tag.startswith("static"):
        return "static (plant/hold)"
    if tag.startswith("wkf"):
        return "wkf (dynamic swing+stance)"
    if tag.startswith("stand"):
        return "stand (neutral)"
    return "other"


def load_log(path):
    hdr = None
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            if hdr is None:
                hdr = ln.split(",")
                continue
            rows.append(ln.split(","))
    cols = {name: i for i, name in enumerate(hdr)}
    t = np.array([float(r[cols["t"]]) for r in rows])
    rp = np.array([[float(r[cols["roll"]]), float(r[cols["pitch"]])] for r in rows])
    gyro = np.array([[float(r[cols["gx"]]), float(r[cols["gy"]])] for r in rows])
    jd = np.array([[float(r[cols[f"j{k}"]]) for k in range(8)] for r in rows])
    phase = ([r[cols["phase"]] for r in rows] if "phase" in cols else [""] * len(rows))
    return t, rp, gyro, jd, phase


def apply_surface(plane_id, surface, carpet_soft, carpet_friction):
    """surface='hard' leaves PyBullet's rigid plane.urdf defaults alone.
    surface='carpet' applies the same flat+compliant model as
    opencat_gym_env.py's `_carpet_floor` block, but with fixed (not
    per-episode-randomized) stiffness/damping/friction so a fit can converge."""
    if surface != "carpet":
        return
    lo_k, hi_k = _CARPET_STIFFNESS_RANGE
    lo_d, hi_d = _CARPET_DAMPING_RANGE
    mid_k, mid_d = (lo_k + hi_k) / 2, (lo_d + hi_d) / 2
    p.changeDynamics(plane_id, -1,
        contactStiffness=float(mid_k * (1 - 0.4 * carpet_soft)),
        contactDamping=float(mid_d * (1 + 0.6 * carpet_soft)),
        restitution=0.0,
        lateralFriction=float(carpet_friction))


def build_sim(gui=False, surface="hard", carpet_soft=0.3, carpet_friction=_CARPET_FRICTION_MID):
    cid = p.connect(p.GUI if gui else p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.setGravity(0, 0, -9.81)
    p.setTimeStep(1.0 / SUBSTEP_HZ)
    plane_id = p.loadURDF("plane.urdf")
    apply_surface(plane_id, surface, carpet_soft, carpet_friction)
    rid = p.loadURDF("models/bittle_esp32.urdf", [0, 0, 0.08], [0, 0, 0, 1],
                     flags=p.URDF_USE_SELF_COLLISION)
    jids = [j for j in range(p.getNumJoints(rid))
            if p.getJointInfo(rid, j)[2] in (p.JOINT_REVOLUTE, p.JOINT_PRISMATIC)]
    pl = p.createMultiBody(baseMass=PAYLOAD_MASS, baseCollisionShapeIndex=-1,
                           basePosition=[PAYLOAD_POS[0], PAYLOAD_POS[1], 0.08 + PAYLOAD_POS[2]])
    c = p.createConstraint(rid, -1, pl, -1, p.JOINT_FIXED, [0, 0, 0], list(PAYLOAD_POS), [0, 0, 0])
    p.changeConstraint(c, maxForce=5e3)
    return cid, rid, jids, plane_id


def replay(t, jd_deg, jids, rid, max_force, kp, kd, latency):
    """Feed the recorded joint targets open-loop; return sim (roll,pitch) and
    (gx,gy) sampled at each log row."""
    jr = np.deg2rad(jd_deg)
    # reset the body + joints to a clean start (fit calls this many times)
    p.resetBasePositionAndOrientation(rid, [0, 0, 0.08], [0, 0, 0, 1])
    p.resetBaseVelocity(rid, [0, 0, 0], [0, 0, 0])
    for k, j in enumerate(jids):
        p.resetJointState(rid, j, float(jr[0][k]))
    # settle at the first commanded pose
    for _ in range(120):
        p.setJointMotorControlArray(rid, jids, p.POSITION_CONTROL, jr[0],
                                    forces=[max_force] * 8,
                                    positionGains=[kp] * 8, velocityGains=[kd] * 8)
        p.stepSimulation()
    buf = [jr[0]] * max(1, latency + 1)
    sim_rp = np.empty((len(t), 2))
    sim_g = np.empty((len(t), 2))
    prev = t[0]
    for i in range(len(t)):
        buf.append(jr[i])
        tgt = buf.pop(0)
        nsub = 1 if i == 0 else max(1, int(round((t[i] - prev) * SUBSTEP_HZ)))
        prev = t[i]
        for _ in range(min(nsub, 24)):
            p.setJointMotorControlArray(rid, jids, p.POSITION_CONTROL, tgt,
                                        forces=[max_force] * 8,
                                        positionGains=[kp] * 8, velocityGains=[kd] * 8)
            p.stepSimulation()
        _, quat = p.getBasePositionAndOrientation(rid)
        e = p.getEulerFromQuaternion(quat)
        w = p.getBaseVelocity(rid)[1]
        sim_rp[i] = (e[0], e[1])
        sim_g[i] = (w[0], w[1])
    return sim_rp, sim_g


def gap(real_rp, real_g, sim_rp, sim_g, align=True):
    """RMS tilt + rate gap. If align, subtract per-axis means first (removes a
    static IMU-vs-sim frame offset) and report what was removed."""
    off = np.zeros(2)
    if align:
        off = np.mean(real_rp - sim_rp, axis=0)
        real_rp = real_rp - off
    tilt_rms = float(np.sqrt(np.mean((real_rp - sim_rp) ** 2)))
    rate_rms = float(np.sqrt(np.mean((real_g - sim_g) ** 2)))
    return tilt_rms, rate_rms, off


def print_phase_gap(real_rp, real_g, sim_rp, sim_g, phase, align=True):
    """H10 diagnostic: RMS gap broken out per phase family. A residual
    concentrated in `static` points at the contact stiffness/damping term
    (the plant/lift mechanism); one spread evenly across `wkf` instead points
    at a mechanism the contact model can't represent -- fiber drag on a foot
    moving through pile above the floor plane."""
    if not any(phase):
        return
    off = np.zeros(2)
    if align:
        off = np.mean(real_rp - sim_rp, axis=0)
        real_rp = real_rp - off
    fams = np.array([_phase_family(p) for p in phase])
    rows = []
    for fam in sorted(set(fams)):
        m = fams == fam
        if m.sum() < 3:
            continue
        tilt_rms = float(np.sqrt(np.mean((real_rp[m] - sim_rp[m]) ** 2)))
        rate_rms = float(np.sqrt(np.mean((real_g[m] - sim_g[m]) ** 2)))
        rows.append((fam, tilt_rms, rate_rms, int(m.sum())))
    if len(rows) < 2:
        return
    print("  by phase family:")
    for fam, tr, rr, n in rows:
        print(f"    {fam:<26} tilt {np.degrees(tr):5.2f} deg RMS   rate {rr:5.3f} rad/s RMS   (n={n})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--fit-surface", action="store_true",
                     help="H10: fit CARPET_SOFT + carpet friction instead of the actuator model. "
                          "Pass --max-force/--kp/--kd/--latency as the values LOCKED from a prior "
                          "--fit run against a hard-floor log. Requires --surface carpet.")
    ap.add_argument("--surface", choices=["hard", "carpet"], default="hard")
    ap.add_argument("--carpet-soft", type=float, default=0.3,
                     help="starting/placeholder CARPET_SOFT for --surface carpet (matches the env's current estimate)")
    ap.add_argument("--carpet-friction", type=float, default=_CARPET_FRICTION_MID)
    ap.add_argument("--max-force", type=float, default=0.20)   # env default
    ap.add_argument("--kp", type=float, default=0.1)
    ap.add_argument("--kd", type=float, default=1.0)
    ap.add_argument("--latency", type=int, default=0)
    ap.add_argument("--no-align", action="store_true")
    args = ap.parse_args()

    if args.fit_surface and args.surface != "carpet":
        raise SystemExit("--fit-surface fits the carpet ground model -- pass --surface carpet")
    if args.fit_surface and args.fit:
        raise SystemExit("--fit (actuator) and --fit-surface (carpet ground) fit different things -- "
                          "run them as two separate passes: actuator against a hard-floor log first, "
                          "then surface against a carpet log with those values locked in")

    t, real_rp, real_g, jd, phase = load_log(args.log)
    print(f"log: {len(t)} rows, {t[-1]-t[0]:.1f} s"
          + (f", phases: {sorted(set(phase))}" if any(phase) else ""))

    _cid, rid, jids, plane_id = build_sim(surface=args.surface, carpet_soft=args.carpet_soft,
                                          carpet_friction=args.carpet_friction)

    def eval_params(mf, kp, kd, lat):
        srp, sg = replay(t, jd, jids, rid, mf, kp, kd, lat)
        return gap(real_rp, real_g, srp, sg, align=not args.no_align), (srp, sg)

    base = eval_params(args.max_force, args.kp, args.kd, args.latency)
    (t0, r0, off0), (srp0, sg0) = base
    print(f"\nbaseline (surface={args.surface}"
          + (f", carpet_soft={args.carpet_soft}, carpet_friction={args.carpet_friction}"
             if args.surface == "carpet" else "")
          + f" | actuator: max_force={args.max_force}, kp={args.kp}, kd={args.kd}, "
            f"latency={args.latency}):")
    print(f"  tilt gap  {np.degrees(t0):.2f} deg RMS")
    print(f"  rate gap  {r0:.3f} rad/s RMS")
    print(f"  frame offset removed (roll,pitch): {np.degrees(off0).round(2).tolist()} deg  "
          f"{'<- large: IMU axis/sign mismatch, check parse_imu_line' if np.abs(off0).max() > 0.15 else ''}")
    print_phase_gap(real_rp, real_g, srp0, sg0, phase, align=not args.no_align)

    if args.fit_surface:
        print("\nfitting carpet surface (coordinate descent, actuator params LOCKED)...")
        grids = {
            "carpet_soft":     [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0],
            "carpet_friction": [0.6, 0.8, 1.0, 1.1, 1.3, 1.5, 1.8],
        }
        best = dict(carpet_soft=args.carpet_soft, carpet_friction=args.carpet_friction)
        best_cost = np.degrees(t0) + 30 * r0
        best_srp, best_sg = srp0, sg0
        for _round in range(2):
            for key, vals in grids.items():
                for v in vals:
                    trial = dict(best); trial[key] = v
                    apply_surface(plane_id, "carpet", trial["carpet_soft"], trial["carpet_friction"])
                    (tr, rr, _), (srp, sg) = eval_params(args.max_force, args.kp, args.kd, args.latency)
                    cost = np.degrees(tr) + 30 * rr
                    if cost < best_cost - 1e-6:
                        best_cost, best = cost, trial
                        best_srp, best_sg = srp, sg
        apply_surface(plane_id, "carpet", best["carpet_soft"], best["carpet_friction"])
        (tf, rf, offf), (srpf, sgf) = eval_params(args.max_force, args.kp, args.kd, args.latency)
        improved = (np.degrees(t0) - np.degrees(tf) > 0.15) or (r0 - rf > 0.005)
        if not improved:
            print(f"\nno meaningful improvement -- CARPET_SOFT={args.carpet_soft} already fits this "
                  f"log (tilt gap stays {np.degrees(t0):.2f} deg RMS). "
                  + ("Sim matches reality here." if np.degrees(t0) < 1.0 else
                     "The residual isn't explained by ground compliance/friction -- check the phase "
                     "breakdown above: concentrated in `wkf` points at unmodeled swing-phase fiber "
                     "drag, not a bad CARPET_SOFT value (H10)."))
            return
        print(f"\nbest: CARPET_SOFT={best['carpet_soft']:.2f}, carpet friction={best['carpet_friction']:.2f}")
        print(f"  tilt gap  {np.degrees(t0):.2f} -> {np.degrees(tf):.2f} deg RMS")
        print(f"  rate gap  {r0:.3f} -> {rf:.3f} rad/s RMS")
        print_phase_gap(real_rp, real_g, srpf, sgf, phase, align=not args.no_align)
        print("\napply to opencat_gym_env.py:")
        print(f"  - CARPET_SOFT = {best['carpet_soft']:.2f}   (placeholder tested against: {args.carpet_soft})")
        if abs(best["carpet_friction"] - _CARPET_FRICTION_MID) > 0.05:
            lo, hi = max(0.1, best["carpet_friction"] - 0.2), best["carpet_friction"] + 0.2
            print(f"  - carpet lateralFriction: np.random.uniform({lo:.2f}, {hi:.2f})   (was 0.9, 1.3)")
        print("\nIf the residual after this fit still concentrates in the `wkf` phase family (see "
              "breakdown above), that's evidence for the missing swing-phase fiber-drag term, not a "
              "CARPET_SOFT problem -- see H10 in docs/rl-runs/hardware-gated-training-backlog.md.")
        return

    if not args.fit:
        return

    print("\nfitting (coordinate descent)...")
    grids = {
        "mf":  [0.10, 0.15, 0.20, 0.28, 0.40, 0.60],
        "kp":  [0.03, 0.06, 0.1, 0.2, 0.4],
        "kd":  [0.2, 0.5, 1.0, 2.0],
        "lat": [0, 1, 2, 3, 4],
    }
    best = dict(mf=args.max_force, kp=args.kp, kd=args.kd, lat=args.latency)
    best_cost = np.degrees(t0) + 30 * r0
    for _round in range(2):
        for key, vals in grids.items():
            for v in vals:
                trial = dict(best); trial[key] = v
                (tr, rr, _), _ = eval_params(trial["mf"], trial["kp"], trial["kd"], trial["lat"])
                cost = np.degrees(tr) + 30 * rr
                if cost < best_cost - 1e-6:
                    best_cost, best = cost, trial
    (tf, rf, offf), _ = eval_params(best["mf"], best["kp"], best["kd"], best["lat"])
    improved = (np.degrees(t0) - np.degrees(tf) > 0.15) or (r0 - rf > 0.005)
    if not improved:
        print(f"\nno meaningful improvement -- the env's current params already fit this log "
              f"(tilt gap stays {np.degrees(t0):.2f} deg RMS). "
              f"{'The gap is small; sim matches reality here.' if np.degrees(t0) < 1.0 else 'The residual gap is not explained by these 4 params -- look at friction, CoM, IMU frame.'}")
        return
    print(f"\nbest: max_force={best['mf']}, kp={best['kp']}, kd={best['kd']}, latency={best['lat']}")
    print(f"  tilt gap  {np.degrees(t0):.2f} -> {np.degrees(tf):.2f} deg RMS")
    print(f"  rate gap  {r0:.3f} -> {rf:.3f} rad/s RMS")
    print("\napply to opencat_gym_env.py:")
    print(f"  - motor forces:  forces=np.ones(8)*{best['mf']:.3f}*self._torque_scale   (was 0.2)")
    if abs(best["kp"] - 0.1) > 1e-6 or abs(best["kd"] - 1.0) > 1e-6:
        print(f"  - add gains to setJointMotorControlArray: positionGains=[{best['kp']}]*8, "
              f"velocityGains=[{best['kd']}]*8")
    if best["lat"] > 0:
        print(f"  - CMD_LATENCY_STEPS = {best['lat']}   (already a knob; default 0)")
    print("\nThen re-run the H1 walk and validate_deploy; retrain if H1 was a 'middle' result.")


if __name__ == "__main__":
    main()
