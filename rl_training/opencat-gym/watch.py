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
    "slope+obstacles":   {"SLOPE_FIXED_RP": (0.0, D(9)), "RANDOM_TERRAIN": 0.030},
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
    ap.add_argument("--challenge", default="flat", choices=list(CHALLENGES))
    ap.add_argument("--cmd", type=float, default=0.10, help="forward speed command m/s")
    ap.add_argument("--speed", type=float, default=1.0, help="playback speed (1 = ~realtime)")
    ap.add_argument("--dr", default="payload", choices=("payload", "clean", "full"),
                    help="non-challenge DR: payload=deploy config (default), clean=none, full=training")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        print("challenges:")
        for k in CHALLENGES:
            print(f"  {k}")
        return

    import opencat_gym_env as E
    E.GUI_MODE = True
    E.ADAPTIVE_PUSH = False
    import benchmark_decathlon as DEC
    DEC._EXTRA_DR = args.dr

    from opencat_gym_env import OpenCatGymEnv
    from stable_baselines3 import PPO
    import pybullet as p

    knobs = CHALLENGES[args.challenge]
    env = OpenCatGymEnv()
    model = PPO.load(args.model)
    p.setRealTimeSimulation(0)
    dt = 3.0 / 240.0

    print(f"watch  |  {args.model}  |  challenge={args.challenge}  |  cmd_fwd={args.cmd} m/s"
          f"  |  dr={args.dr}  |  speed x{args.speed}\nclose the window to stop.\n", flush=True)
    run = 0
    try:
        while p.isConnected():
            DEC._apply(knobs)
            run += 1
            obs, _ = env.reset()
            env.set_command(fwd=args.cmd, yaw=0.0)
            x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
            steps, peak_tilt = 0, 0.0
            while True:
                a, _ = model.predict(obs, deterministic=True)
                obs, _, term, trunc, _ = env.step(a)
                pos, q = p.getBasePositionAndOrientation(env.robot_id)
                p.resetDebugVisualizerCamera(0.45, 50, -22, [pos[0], pos[1], pos[2] + 0.05])
                rp = p.getEulerFromQuaternion(q)
                peak_tilt = max(peak_tilt, abs(rp[0]), abs(rp[1]))
                steps += 1
                if args.speed > 0:
                    time.sleep(dt / args.speed)
                if term or trunc:
                    break
            x1 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
            print(f"  run {run:3d}: {steps:3d} steps  fwd {x1 - x0:+.2f} m  "
                  f"peak tilt {peak_tilt:.2f} rad  -> {'FELL' if term else 'survived'}", flush=True)
    except (KeyboardInterrupt, p.error):
        pass
    print("\nwindow closed.")


if __name__ == "__main__":
    main()
