"""Headless evaluation of a trained policy (used by the automated testing loop).

Runs a checkpoint deterministically for several episodes in DIRECT mode, computes
gait-quality metrics, prints them as JSON, and renders a strip of frames from the
first episode to PNGs for visual inspection.

Usage:
  python evaluate_policy.py trained/full_run_v6_ppo
  python evaluate_policy.py trained/full_run_v6_ppo --episodes 5 --frames-dir eval_frames/v6

Metric conventions:
  - x = forward, y = left(+)/right(-), yaw > 0 = turning left, yaw < 0 = turning right.
  - distances in metres, angles in degrees, "per step" = one env.step().
"""
import argparse
import json
import os

import numpy as np
import pybullet as p

import opencat_gym_env
opencat_gym_env.GUI_MODE = False
from opencat_gym_env import OpenCatGymEnv

PAW_LINKS = [3, 6, 9, 12]          # foot link indices (from the env)
EPISODE_CAP = 250


def run_episode(env, model, render_frames=0, frames_dir=None):
    obs, _ = env.reset()
    rid = env.robot_id

    p0, _ = p.getBasePositionAndOrientation(rid)
    rec = {
        "x": [], "y": [], "z": [], "roll": [], "pitch": [], "yaw": [],
        "yaw_rate": [], "foot_z": [[], [], [], []], "foot_contact": [[], [], [], []],
        "foot_x": [[], [], [], []], "joint": [],
    }
    per_term = {}

    steps = 0
    fell = False
    while True:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, terminated, truncated, info = env.step(action)
        steps += 1

        pos, orn = p.getBasePositionAndOrientation(rid)
        roll, pitch, yaw = p.getEulerFromQuaternion(orn)
        ang_vel = p.getBaseVelocity(rid)[1]
        rec["x"].append(pos[0]); rec["y"].append(pos[1]); rec["z"].append(pos[2])
        rec["roll"].append(roll); rec["pitch"].append(pitch); rec["yaw"].append(yaw)
        rec["yaw_rate"].append(ang_vel[2])
        for i, link in enumerate(PAW_LINKS):
            ls = p.getLinkState(rid, link)
            rec["foot_z"][i].append(ls[0][2])
            rec["foot_x"][i].append(ls[0][0])
            rec["foot_contact"][i].append(bool(p.getContactPoints(bodyA=rid, linkIndexA=link)))
        js = np.asarray(p.getJointStates(rid, env.joint_id), dtype=object)[:, 0]
        rec["joint"].append(np.array(js, dtype=float))
        for k, v in info.items():
            per_term.setdefault(k, []).append(float(v))

        if render_frames and frames_dir and steps <= EPISODE_CAP:
            every = max(EPISODE_CAP // render_frames, 1)
            if steps % every == 0:
                w, h, rgb, _, _ = p.getCameraImage(
                    480, 360,
                    viewMatrix=p.computeViewMatrixFromYawPitchRoll(
                        cameraTargetPosition=pos, distance=0.5,
                        yaw=50, pitch=-35, roll=0, upAxisIndex=2),
                    projectionMatrix=p.computeProjectionMatrixFOV(60, 480 / 360, 0.1, 5),
                    renderer=p.ER_TINY_RENDERER)
                _save_png(np.reshape(rgb, (h, w, 4))[:, :, :3].astype(np.uint8),
                          os.path.join(frames_dir, f"step_{steps:03d}.png"))

        if terminated or truncated:
            fell = terminated and steps < EPISODE_CAP
            break

    return rec, per_term, steps, fell


def _save_png(arr, path):
    try:
        from PIL import Image
        Image.fromarray(arr).save(path)
    except Exception as e:      # noqa: BLE001 - rendering is best-effort
        print(f"  (frame save failed: {e})")


def _strides(foot_x, contact):
    """x-distance between successive touchdowns (False->True) of one foot."""
    tds = [i for i in range(1, len(contact)) if contact[i] and not contact[i - 1]]
    if len(tds) < 2:
        return None
    return float(np.mean(np.diff([foot_x[i] for i in tds])))


def summarize(episodes):
    fwd, lat, latmax, yaw_end, yaw_abs, speed = [], [], [], [], [], []
    clr = [[], [], [], []]
    strides, slip, rollv, pitchv, lens, falls = [], [], [], [], [], []
    yaw_quarters = [[], [], [], []]
    diag_corr = []
    startup_ratio, startup_jerk_ratio = [], []   # start-of-episode "stutter"

    for rec, per_term, steps, fell in episodes:
        x, y = np.array(rec["x"]), np.array(rec["y"])
        yaw = np.unwrap(np.array(rec["yaw"]))
        fwd.append(x[-1] - 0.0)
        lat.append(abs(y[-1]))
        latmax.append(float(np.max(np.abs(y))))
        yaw_end.append(np.degrees(yaw[-1]))
        yaw_abs.append(np.degrees(np.max(np.abs(yaw))))
        speed.append((x[-1]) / (steps * 1 / 50))          # ~50 Hz control
        for q in range(4):
            idx = min(int(len(yaw) * (q + 1) / 4) - 1, len(yaw) - 1)
            yaw_quarters[q].append(np.degrees(yaw[idx]))
        for i in range(4):
            fz = np.array(rec["foot_z"][i])
            clr[i].append(float(np.percentile(fz, 95) - np.min(fz)))
            s = _strides(rec["foot_x"][i], rec["foot_contact"][i])
            if s is not None:
                strides.append(s)
        rollv.append(float(np.var(rec["roll"])))
        pitchv.append(float(np.var(rec["pitch"])))
        lens.append(steps)
        falls.append(1 if fell else 0)
        if "r_paw_slip" in per_term:
            slip.append(float(np.mean(np.abs(per_term["r_paw_slip"]))))
        j = np.array(rec["joint"])                      # (T, 8)
        dj = np.diff(j, axis=0)
        diag_a = dj[:, 2] + dj[:, 6]                    # FR + BL
        diag_b = dj[:, 0] + dj[:, 4]                    # FL + BR
        if np.std(diag_a) > 1e-6 and np.std(diag_b) > 1e-6:
            diag_corr.append(float(np.corrcoef(diag_a, diag_b)[0, 1]))

        # Start-of-episode "stutter": compare the first 0.5 s (25 steps) to the
        # following 1 s (steps 25-75). A stutter shows as low early speed and/or
        # high early joint-jerk relative to the settled gait. Ratio ~1 = no stutter.
        if len(x) > 75:
            early_sp = (x[25] - x[0]) / 25
            mid_sp = (x[75] - x[25]) / 50
            if abs(mid_sp) > 1e-5:
                startup_ratio.append(float(early_sp / mid_sp))
            ddj = np.abs(np.diff(dj, axis=0)).sum(axis=1)   # per-step total joint jerk
            if ddj[25:75].mean() > 1e-9:
                startup_jerk_ratio.append(float(ddj[:25].mean() / ddj[25:75].mean()))

    m = lambda a: float(np.mean(a)) if len(a) else None
    return {
        "episodes": len(episodes),
        "episode_len_mean": m(lens),
        "fell_fraction": m(falls),
        "forward_distance_m_mean": m(fwd),
        "forward_speed_mps_mean": m(speed),
        "lateral_drift_final_m_mean": m(lat),
        "lateral_drift_max_m_mean": m(latmax),
        "yaw_final_deg_mean": m(yaw_end),                # <0 = ends pointing right
        "yaw_abs_max_deg_mean": m(yaw_abs),
        "yaw_by_quarter_deg": [m(q) for q in yaw_quarters],
        "foot_peak_clearance_m_mean": [m(c) for c in clr],
        "stride_length_m_mean": m(strides),
        "diagonal_trot_corr_mean": m(diag_corr),        # want strongly negative (anti-phase diagonals)
        "startup_speed_ratio_mean": m(startup_ratio),    # first-25-steps speed / next-50-steps speed; ~1 = no stutter
        "startup_jerk_ratio_mean": m(startup_jerk_ratio),# first-25-steps joint jerk / next-50; >1 = jerky start
        "roll_var_mean": m(rollv),
        "pitch_var_mean": m(pitchv),
        "paw_slip_term_mean_abs": m(slip),
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("checkpoint")
    ap.add_argument("--episodes", type=int, default=5)
    ap.add_argument("--frames-dir", default=None)
    ap.add_argument("--json-out", default=None)
    # Domain-randomization test overrides. Any of these forces dr = 1 (full
    # difficulty) so a policy can be graded on a held-out scenario it never
    # trained on: --dr-terrain 0.012 (obstacles), --dr-push 0.35 (shoves), etc.
    ap.add_argument("--dr-friction", type=float, default=None)
    ap.add_argument("--dr-mass", type=float, default=None)
    ap.add_argument("--dr-gyro", type=float, default=None)
    ap.add_argument("--dr-push", type=float, default=None)
    ap.add_argument("--dr-terrain", type=float, default=None)
    args = ap.parse_args()

    from stable_baselines3 import PPO
    _dr = {"RANDOM_FRICTION": args.dr_friction, "RANDOM_MASS": args.dr_mass,
           "RANDOM_GYRO": args.dr_gyro, "RANDOM_PUSH": args.dr_push,
           "RANDOM_TERRAIN": args.dr_terrain}
    if any(v is not None for v in _dr.values()):
        for k, v in _dr.items():
            if v is not None:
                setattr(opencat_gym_env, k, v)
        opencat_gym_env.DR_EVAL_FULL = True
    # Print the env's start-state config so a policy/env mismatch is visible
    # (evaluating a policy under different randomization than it trained on
    # skews startup_speed_ratio and fell_fraction badly).
    _rsi = getattr(opencat_gym_env, "RSI_JOINT_NOISE_DEG", 0)
    _phase = getattr(opencat_gym_env, "RSI_RANDOMIZE_PHASE", False)
    print(f"env start-state: RSI_JOINT_NOISE_DEG={_rsi}  RSI_RANDOMIZE_PHASE={_phase}"
          f"  |  DR: friction={opencat_gym_env.RANDOM_FRICTION} mass={opencat_gym_env.RANDOM_MASS}"
          f" gyro={opencat_gym_env.RANDOM_GYRO} push={opencat_gym_env.RANDOM_PUSH}"
          f" terrain={opencat_gym_env.RANDOM_TERRAIN} eval_full={opencat_gym_env.DR_EVAL_FULL}"
          "  (must match how the checkpoint was trained, except DR test overrides)")
    env = OpenCatGymEnv()
    model = PPO.load(args.checkpoint)

    if args.frames_dir:
        os.makedirs(args.frames_dir, exist_ok=True)

    eps = []
    for e in range(args.episodes):
        eps.append(run_episode(
            env, model,
            render_frames=30 if (args.frames_dir and e == 0) else 0,
            frames_dir=args.frames_dir))
        print(f"  episode {e + 1}/{args.episodes}: {eps[-1][2]} steps"
              f"{' (fell)' if eps[-1][3] else ''}")
    env.close()

    summary = {"checkpoint": args.checkpoint, **summarize(eps)}
    text = json.dumps(summary, indent=2)
    print(text)
    if args.json_out:
        with open(args.json_out, "w") as f:
            f.write(text)
