"""Skill-showcase replay: run a trained checkpoint through every behaviour it
knows, back-to-back, with on-screen labels and a following camera. One GIF.

    python render_showcase.py --learned trained/run20m_ppo --out showcase.gif
    python render_showcase.py --learned trained/run20m_ppo --scripted-balance 0.5   # scripted wkF instead

Scenarios are (label, seconds, {env knobs}, (cmd_fwd, cmd_yaw)). Knobs are zeroed
between scenarios; the env is reset at each one. DR is forced full so knobs apply.
"""
import argparse, math, os, sys
import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE); os.chdir(BASE)
D = math.radians

import opencat_gym_env as E
E.GUI_MODE = False

_ZERO_KNOBS = ("RANDOM_FRICTION", "RANDOM_MASS", "RANDOM_GYRO", "RANDOM_PUSH", "RANDOM_TERRAIN",
               "IMPULSE_PUSH", "SLOPE_MAX_DEG", "START_POSE_JITTER", "STUCK_FOOT_PROB",
               "SUSTAINED_FORCE", "DEFORM_GROUND", "SLIP_PATCH", "ROUGH_TERRAIN",
               "TORQUE_CUTBACK", "LEDGE_HEIGHT", "LEDGE_PROB", "LEDGE_DIR")

SCENARIOS = [
    ("cruise  (cmd 0.10 m/s)",        4.0, {},                                              (0.10, 0.0)),
    ("creep  (cmd 0.04 m/s)",         4.0, {},                                              (0.04, 0.0)),
    ("fast  (cmd 0.13 m/s)",          4.0, {},                                              (0.13, 0.0)),
    ("backward  (cmd -0.06 m/s)",     4.0, {},                                              (-0.06, 0.0)),
    ("stand + hold",                  3.5, {},                                              (0.0, 0.0)),
    ("stand under shoves",            4.5, {"IMPULSE_PUSH": 0.55, "IMPULSE_PUSH_PROB": 0.02}, (0.0, 0.0)),
    ("heading hold (straight line)",  5.0, {},                                              (0.10, 0.0)),
    ("obstacles  (35 mm)",            4.5, {"RANDOM_TERRAIN": 0.035},                        (0.10, 0.0)),
    ("slope up  (12 deg)",            4.5, {"SLOPE_FIXED_RP": (0.0, D(12))},                 (0.10, 0.0)),
    ("slope down  (-12 deg)",         4.5, {"SLOPE_FIXED_RP": (0.0, D(-12))},               (0.10, 0.0)),
    ("cross-slope  (5 deg roll)",     4.5, {"SLOPE_FIXED_RP": (D(5), 0.0)},                  (0.10, 0.0)),
    ("the gauntlet  (everything)",    6.0, {"SLOPE_FIXED_RP": (D(4), D(9)), "RANDOM_TERRAIN": 0.040,
                                            "IMPULSE_PUSH": 0.60, "IMPULSE_PUSH_PROB": 0.012,
                                            "RANDOM_PUSH": 0.25},                            (0.10, 0.0)),
    ("threshold up  (15 mm)",         4.5, {"LEDGE_HEIGHT": 0.015, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}, (0.08, 0.0)),
    ("step up  (30 mm sill)",         5.0, {"LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}, (0.08, 0.0)),
    ("step down  (30 mm drop)",       5.0, {"LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}, (0.08, 0.0)),
]

FPS = 12                    # output GIF frame rate
W, H = 440, 300


def build_controller(args, env):
    if args.scripted_balance is not None:
        from benchmark_gaits import ScriptedGait
        return ScriptedGait(env, balance_k=args.scripted_balance), "scripted wkF"
    from stable_baselines3 import PPO
    return PPO.load(args.learned), os.path.basename(args.learned)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned", default="trained/run20m_ppo")
    ap.add_argument("--scripted-balance", type=float, default=None,
                    help="render the scripted wkF gait with this balance-assist gain instead of --learned")
    ap.add_argument("--out", default="showcase.gif")
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--payload", choices=("on", "off"), default="on")
    args = ap.parse_args()

    import pybullet as p
    E.DR_EVAL_FULL = True
    E.PAYLOAD_PROB = 1.0 if args.payload == "on" else 0.0
    E.PAYLOAD_MASS_RAND = 0.0
    from opencat_gym_env import OpenCatGymEnv

    env = OpenCatGymEnv()
    model, who = build_controller(args, env)
    print(f"showcase: {who}  payload={args.payload}  -> {args.out}", flush=True)

    frames, labels = [], []
    for label, secs, knobs, (cf, cy) in SCENARIOS:
        for k in _ZERO_KNOBS:
            if hasattr(E, k):
                setattr(E, k, 0.0)
        E.SLOPE_FIXED_RP = None
        for k, v in knobs.items():
            setattr(E, k, v)
        np.random.seed(args.seed)
        if hasattr(model, "reset"):
            model.reset()
        obs, _ = env.reset()
        if hasattr(env, "set_command"):
            env.set_command(fwd=cf, yaw=cy)
        n_steps = int(secs * 60)                       # sim runs ~60 Hz display cadence
        every = max(1, round(60 / FPS))
        print(f"  {label}", flush=True)
        for t in range(n_steps):
            a, _ = model.predict(obs, deterministic=True)
            obs, _, term, trunc, _ = env.step(a)
            if hasattr(env, "set_command") and (term or trunc):
                obs, _ = env.reset(); env.set_command(fwd=cf, yaw=cy)
            if t % every == 0:
                pos = p.getBasePositionAndOrientation(env.robot_id)[0]
                _, _, rgb, _, _ = p.getCameraImage(
                    W, H,
                    viewMatrix=p.computeViewMatrixFromYawPitchRoll(
                        [pos[0], pos[1], pos[2] + 0.02], 0.55, 50, -22, 0, 2),
                    projectionMatrix=p.computeProjectionMatrixFOV(60, W / H, 0.1, 5),
                    renderer=p.ER_TINY_RENDERER)
                frames.append(np.reshape(rgb, (H, W, 4))[:, :, :3].astype(np.uint8))
                labels.append(label)

    # annotate + save
    from PIL import Image, ImageDraw
    imgs = []
    for fr, lab in zip(frames, labels):
        im = Image.fromarray(fr)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, W, 18], fill=(0, 0, 0))
        d.text((6, 4), f"{who}   |   {lab}", fill=(255, 210, 120))
        imgs.append(im)
    imgs[0].save(args.out, save_all=True, append_images=imgs[1:],
                 duration=int(1000 / FPS), loop=0, optimize=True)
    mb = os.path.getsize(args.out) / 1e6
    print(f"wrote {args.out}  ({len(imgs)} frames, {mb:.2f} MB)", flush=True)


if __name__ == "__main__":
    main()
