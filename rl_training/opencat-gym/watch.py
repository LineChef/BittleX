"""Watch a trained policy run a chosen challenge live, in a pybullet window.
Fresh randomised episode after every fall / timeout, until you close the window.
Not a loop of one recording -- every run is a new episode.

    python watch.py --list                       # every challenge name
    python watch.py                              # flat ground, cruise
    python watch.py --challenge slope-up         # just a 12 deg climb
    python watch.py --challenge gauntlet         # the T5.1 combined test
    python watch.py --challenge step-down --cmd 0.08 --speed 0.5   # slo-mo
    python watch.py --model trained/checkpoints/p4c_3000000_steps  # a snapshot

MUST be run from your own terminal -- pybullet's GUI window does not appear when
launched from a background/detached process.

Config matches benchmark_decathlon (payload on by default = the deployment
config; --dr clean|full to change). Each challenge is the same knob dict the
decathlon / showcase uses.
"""
import argparse
import math
import time

D = math.radians

# name -> env-knob overrides (everything else is zeroed by benchmark_decathlon._apply)
CHALLENGES = {
    "flat":              {},
    "flat-nudges":       {"RANDOM_PUSH": 0.12, "RANDOM_PUSH_PROB": 0.02},
    "slope-up-gentle":   {"SLOPE_FIXED_RP": (0.0, D(5))},
    "slope-up":          {"SLOPE_FIXED_RP": (0.0, D(12))},
    "slope-up-steep":    {"SLOPE_FIXED_RP": (0.0, D(15))},
    "slope-down":        {"SLOPE_FIXED_RP": (0.0, D(-12))},
    "slope-down-steep":  {"SLOPE_FIXED_RP": (0.0, D(-24))},
    "cross-slope":       {"SLOPE_FIXED_RP": (D(5), 0.0)},
    "obstacles-small":   {"RANDOM_TERRAIN": 0.020},
    "obstacles":         {"RANDOM_TERRAIN": 0.035},
    "obstacles-big":     {"RANDOM_TERRAIN": 0.050, "RANDOM_PUSH": 0.30},
    "obstacles-huge":    {"RANDOM_TERRAIN": 0.085, "RANDOM_PUSH": 0.35},
    "rubble":            {"RUBBLE": 0.016, "RUBBLE_N": 540, "RUBBLE_PROB": 1.0},   # rough, near the passable limit
    "rubble-hard":       {"RUBBLE": 0.020, "RUBBLE_N": 560, "RUBBLE_PROB": 1.0},   # denser + taller, near the passable limit
    "slope+obstacles":   {"SLOPE_FIXED_RP": (0.0, D(9)), "RANDOM_TERRAIN": 0.030},
    "carpet":            {"CARPET": 0.011, "CARPET_PROB": 1.0},          # one heightfield, 11mm bumps, floor never shows
    "carpet-rough":      {"CARPET": 0.016, "CARPET_PROB": 1.0},          # taller bumps, near passable limit
    "one-shove":         {"IMPULSE_PUSH": 0.65, "IMPULSE_PUSH_PROB": 0.004},
    "shoves":            {"IMPULSE_PUSH": 0.55, "IMPULSE_PUSH_PROB": 0.012, "RANDOM_PUSH": 0.20},
    "shoves-hard":       {"IMPULSE_PUSH": 1.00, "IMPULSE_PUSH_PROB": 0.018, "RANDOM_PUSH": 0.25},
    "threshold-up":      {"LEDGE_HEIGHT": 0.015, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1},
    "step-up":           {"LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1},
    "step-down":         {"LEDGE_HEIGHT": 0.030, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1},
    "big-ledge":         {"LEDGE_HEIGHT": 0.045, "LEDGE_PROB": 1.0, "LEDGE_DIR": 0},
    "weak-servos":       {"TORQUE_CUTBACK": 0.60, "SLOPE_FIXED_RP": (0.0, D(-12))},
    "gauntlet":          {"SLOPE_FIXED_RP": (D(4), D(9)), "RANDOM_TERRAIN": 0.040,
                          "IMPULSE_PUSH": 0.60, "IMPULSE_PUSH_PROB": 0.012, "RANDOM_PUSH": 0.25},
    "brutal-gauntlet":   {"SLOPE_FIXED_RP": (D(8), D(20)), "RANDOM_TERRAIN": 0.070,
                          "IMPULSE_PUSH": 1.00, "IMPULSE_PUSH_PROB": 0.018, "RANDOM_PUSH": 0.45},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="trained/run20m_ppo")
    ap.add_argument("--latest", action="store_true", help="use the newest trained/checkpoints/*_steps.zip")
    ap.add_argument("--challenge", default="flat", choices=list(CHALLENGES))
    ap.add_argument("--cmd", type=float, default=0.10, help="forward speed command m/s")
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed (1 = ~realtime)")
    ap.add_argument("--dr", default="payload", choices=("payload", "clean", "full"),
                    help="non-challenge DR: payload=deploy config (default), clean=none, full=training")
    ap.add_argument("--gif", nargs="?", const="__auto__", default=None,
                    help="render to a GIF instead of a live window (headless -- always works). "
                         "Optional path; default watch_<challenge>.gif")
    ap.add_argument("--runs", type=int, default=3, help="--gif: episodes to record")
    ap.add_argument("--steps", type=int, default=None,
                    help="steps per episode before the course resets (default 250; "
                         "obstacle-course defaults to 2000 so you can watch a long traverse)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.latest:
        import glob, os
        cks = glob.glob("trained/checkpoints/*_steps.zip")
        if cks:
            args.model = max(cks, key=os.path.getmtime)[:-4]   # newest file, not highest step number
            print(f"--latest -> {args.model}")
        else:
            print("--latest: no checkpoints found, using", args.model)

    if args.list:
        print("challenges:")
        for k in CHALLENGES:
            print(f"  {k}")
        return

    gif_mode = args.gif is not None
    ep_steps = args.steps if args.steps is not None else (
        2000 if args.challenge.startswith(("rubble", "carpet")) else 250)

    import opencat_gym_env as E
    E.GUI_MODE = not gif_mode           # GIF path is headless
    E.ADAPTIVE_PUSH = False
    E.EPISODE_LENGTH = ep_steps         # steps before the course resets
    from opencat_gym_env import OpenCatGymEnv

    # macOS: the env's __init__ calls p.connect(p.GUI). It MUST happen before
    # stable_baselines3/torch is imported, or PyBullet's Metal GUI thread fails
    # silently (sim runs, no window). Same ordering as watch_trained.py.
    env = OpenCatGymEnv()
    env.reset()                 # materialise the GUI window BEFORE torch loads (macOS)
    import pybullet as p
    import numpy as np

    import benchmark_decathlon as DEC   # noqa: E402  (after env on purpose)
    DEC._EXTRA_DR = args.dr
    from stable_baselines3 import PPO    # noqa: E402

    knobs = CHALLENGES[args.challenge]
    model = PPO.load(args.model)
    if not gif_mode:
        p.setRealTimeSimulation(0)
    dt = 3.0 / 240.0

    W, H, FPS, EVERY = 480, 300, 25, 3
    frames = []
    gif_path = (f"watch_{args.challenge}.gif" if args.gif == "__auto__" else args.gif)

    print(f"watch  |  {args.model}  |  challenge={args.challenge}  |  cmd_fwd={args.cmd} m/s  |  dr={args.dr}"
          + (f"  |  -> {gif_path} ({args.runs} runs)" if gif_mode
             else f"  |  speed x{args.speed}   (close the window to stop)") + "\n", flush=True)

    run = 0
    try:
        while (gif_mode and run < args.runs) or (not gif_mode and p.isConnected()):
            DEC._apply(knobs)
            run += 1
            obs, _ = env.reset()
            # macOS Metal sometimes fails to load plane.urdf's checkerboard
            # texture -> black floor. Body 0 is the plane; paint it a solid grey.
            try:
                p.changeVisualShape(0, -1, rgbaColor=[0.82, 0.82, 0.85, 1.0], textureUniqueId=-1)
            except Exception:
                pass
            env.set_command(fwd=args.cmd, yaw=0.0)
            x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
            steps, peak_tilt = 0, 0.0
            while True:
                a, _ = model.predict(obs, deterministic=True)
                obs, _, term, trunc, _ = env.step(a)
                pos, q = p.getBasePositionAndOrientation(env.robot_id)
                if gif_mode:
                    if steps % EVERY == 0:
                        vm = p.computeViewMatrixFromYawPitchRoll(
                            [pos[0], pos[1], pos[2] + 0.03], 0.55, 50, -22, 0, 2)
                        pm = p.computeProjectionMatrixFOV(60, W / H, 0.1, 5)
                        rgb = p.getCameraImage(W, H, vm, pm, renderer=p.ER_TINY_RENDERER)[2]
                        frames.append(np.reshape(rgb, (H, W, 4))[:, :, :3].astype(np.uint8))
                else:
                    p.resetDebugVisualizerCamera(0.45, 50, -22, [pos[0], pos[1], pos[2] + 0.05])
                    if args.speed > 0:
                        time.sleep(dt / args.speed)
                rp = p.getEulerFromQuaternion(q)
                peak_tilt = max(peak_tilt, abs(rp[0]), abs(rp[1]))
                steps += 1
                if term or trunc:
                    break
            x1 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
            print(f"  run {run:3d}: {steps:3d} steps  fwd {x1 - x0:+.2f} m  "
                  f"peak tilt {peak_tilt:.2f} rad  -> {'FELL' if term else 'survived'}", flush=True)
    except (KeyboardInterrupt, p.error):
        pass

    if gif_mode and frames:
        from PIL import Image
        imgs = [Image.fromarray(f) for f in frames]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:],
                     duration=int(1000 / FPS), loop=0, optimize=True)
        print(f"\nwrote {gif_path}  ({len(imgs)} frames, {__import__('os').path.getsize(gif_path)/1e6:.1f} MB)")
        print(f"open it:  open {gif_path}")
    elif not gif_mode:
        print("\nwindow closed.")


if __name__ == "__main__":
    main()
