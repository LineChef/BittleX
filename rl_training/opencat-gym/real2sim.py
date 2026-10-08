"""Real-to-sim replay (user-approved 2026-10-08; docs/plan-detail/handoff-2026-10-08.md section 12): play the joint commands G2 actually sent (a `run_gait.py --log` CSV)
OPEN-LOOP through the TRAINING environment itself -- the scoring profile, the firmware command path, the servo speed limit, the world-2 payload -- and compare the sim's
body motion with G2's real IMU. Unlike sysid_replay.py (Sept 2026, its own simplified sim), the fit here tunes exactly the sim that trains.

    ../../.venv/bin/python real2sim.py LOG.csv [LOG2.csv ...]            # per-log comparison at the current settings
    ../../.venv/bin/python real2sim.py --fit LOG.csv [...]                # grid over servo speed limit x motor force x ground friction (run with the Mac idle)

Compared (G2's IMU is a 5 Hz held stream, so the sim's body angles are sampled the same way): roll and pitch spread (deg) and the dominant roll frequency (Hz, the
gait's sway). Heading is NOT part of the fit (standing rule: real data is never a drift source). Nominal sim: no randomization (mass, friction, shoves, IMU noise,
calibration offsets, payload jitter all off) so the comparison measures the model, not the dice. The fit only REPORTS the best values: applying one goes through the
real-data pipeline's gates (tools/g2_calibrate.py), never directly into training.
"""
import argparse
import glob
import itertools
import json
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def load_log(path):
    rows = [l.strip().split(",") for l in open(path) if l.strip() and not l.startswith("#")]
    head, data = rows[0], rows[1:]
    ix = {k: i for i, k in enumerate(head)}
    def col(k):
        return np.array([float(r[ix[k]]) for r in data])
    return {"t": col("t"), "roll": col("roll"), "pitch": col("pitch"), "j": np.stack([col(f"j{i}") for i in range(8)], axis=1)}


def stats(roll, pitch, hz):
    """Spread (deg) and the dominant roll frequency (Hz) of a body-angle trace sampled at `hz`."""
    r = np.degrees(roll - np.mean(roll))
    f = np.fft.rfftfreq(len(r), 1.0 / hz)
    spec = np.abs(np.fft.rfft(r))
    band = (f > 0.3) & (f < 6.0)
    return {"roll_std": float(np.std(r)), "pitch_std": float(np.degrees(np.std(pitch))),
            "roll_hz": float(f[band][np.argmax(spec[band])]) if band.any() else 0.0}


def real_stats(log):
    held = np.r_[True, (np.diff(log["roll"]) != 0) | (np.diff(log["pitch"]) != 0)]     # the IMU's fresh frames (5 Hz)
    t = log["t"][held]
    hz = 1.0 / np.median(np.diff(t)) if len(t) > 2 else 5.0
    return stats(log["roll"][held], log["pitch"][held], hz)


def sim_replay(log, overrides=None):
    """Replay one log's commands in the training env (nominal, no randomization). overrides: module constants to set first (the fit's grid point)."""
    sys.path.insert(0, HERE)
    import g2_profile
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    g2_profile.set_environ(g2_profile.scoring_env())
    import pybullet as p
    import opencat_gym_env as E
    E.GUI_MODE = False
    for k, v in (overrides or {}).items():
        setattr(E, k, v)
    for k in ("RANDOM_MASS", "RANDOM_FRICTION", "RANDOM_PUSH", "IMPULSE_PUSH", "JOINT_OFFSET_DEG", "RANDOM_GYRO", "IMU_BIAS_DEG", "TORQUE_CUTBACK",
              "PAYLOAD_MASS_RAND", "HEAD_MASS_RAND", "REAR_MASS_RAND", "PAYLOAD_JITTER_XY", "CMD_PATH_EXTRA_MS_MAX", "RANDOM_JOINT_ANGS"):
        setattr(E, k, 0.0)
    E.CATEGORY_OVERRIDE = {"terrain": 0.0}
    env = E.OpenCatGymEnv()
    env.set_ramp_steps(1e12)
    env.set_command(fwd=0.10, yaw=0.0)
    np.random.seed(0)
    env.reset()
    roll, pitch = [], []
    for k, j in enumerate(log["j"]):
        env._abs_joint_override = j
        _o, _r, te, _tr, _i = env.step(np.zeros(8))
        if k % E.IMU_HOLD_STEPS == 0:                     # sampled like G2's 5 Hz IMU stream
            r_, p_, _ = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(env.robot_id)[1])
            roll.append(r_)
            pitch.append(p_)
        if te:
            break
    env.close()
    return stats(np.array(roll), np.array(pitch), 80.0 / E.IMU_HOLD_STEPS)


def gap(real, sim):
    """Relative squared error over roll spread, pitch spread and sway frequency (heading excluded)."""
    return float(np.mean([((sim[k] - real[k]) / max(abs(real[k]), 1e-3)) ** 2 for k in ("roll_std", "pitch_std", "roll_hz")]))


GRID = {"SERVO_RATE_LIMIT_DEG_S": [120.0, 160.0, 200.0, 250.0, 320.0], "MOTOR_FORCE": [0.12, 0.15, 0.18, 0.22], "GROUND_FRICTION": [0.7, 1.0, 1.3]}


def _point(args):
    logs, ov = args
    out = [sim_replay(load_log(l), ov) for l in logs]
    return ov, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("logs", nargs="*")
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--jobs", type=int, default=6)
    a = ap.parse_args()
    logs = a.logs or sorted(glob.glob(os.path.join(HERE, "..", "..", "docs", "rl", "real-walk-data", "2026-10-06", "*.csv")))
    real = [real_stats(load_log(l)) for l in logs]
    if not a.fit:
        for l, r in zip(logs, real):
            s = sim_replay(load_log(l))
            print(f"{os.path.basename(l)}: real roll {r['roll_std']:.2f} deg, pitch {r['pitch_std']:.2f} deg, sway {r['roll_hz']:.2f} Hz | "
                  f"sim roll {s['roll_std']:.2f}, pitch {s['pitch_std']:.2f}, sway {s['roll_hz']:.2f} | gap {gap(r, s):.3f}", flush=True)
        return
    import multiprocessing as mp
    pts = [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]
    with mp.get_context("spawn").Pool(a.jobs) as pool:
        res = pool.map(_point, [(logs, ov) for ov in pts])
    scored = sorted(((float(np.mean([gap(r, s) for r, s in zip(real, out)])), ov) for ov, out in res), key=lambda t: t[0])
    print(f"{len(logs)} logs, {len(pts)} grid points; best (lower gap is closer to G2):")
    for g, ov in scored[:5]:
        print(f"  gap {g:.3f}  {ov}")
    json.dump({"logs": logs, "real": real, "ranked": [[g, ov] for g, ov in scored]}, open(os.path.join(HERE, "trained", "real2sim_fit.json"), "w"), indent=1)
    print("saved trained/real2sim_fit.json (report only: apply a value through tools/g2_calibrate.py's gates, never directly)")


if __name__ == "__main__":
    main()
