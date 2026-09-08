"""Phase E-4 harness: run `run20m_ppo` on the obstacle course with the
vision-triggered scripted-skill layer (GaitSelector -> SkillSwitch) in the loop,
vs. the same policy alone. NO training -- everything is frozen.

    python eval_skill_switch.py --episodes 20            # switch ON
    python eval_skill_switch.py --episodes 20 --no-switch # baseline
    python eval_skill_switch.py --episodes 3 --render     # watch it

Mechanism: each control tick, read the env's forward terrain scan -> GaitSelector
-> GaitMode -> SkillSwitch(mode, rl_joint_deg, gait_phase). When the switch hands
back RL joints, step the env normally; when it emits a scripted / blended pose,
set `env._abs_joint_override` (an inert env hook) so those absolute joint targets
drive the sim while obs / physics / reward stay intact.
"""
import argparse
import json
import os
import sys

import numpy as np

# obstacle course (Phase D CFG). TERRAIN_FEATURE stays OFF: `run20m_ppo` is the
# blind 278-d base; vision drives the SKILL SWITCH, not the policy's observation.
# The harness reads the forward scan itself via `env._scan_terrain()`.
_DEFAULTS = {
    "G2E_TERRAIN_FEATURE": "0", "G2E_FAC_NOSTALL": "22", "G2E_FAC_NOSTALL_BONUS": "8",
    "G2E_FAC_IMITATION": "5", "G2E_RANDOM_TERRAIN": "0.06", "G2E_RANDOM_TERRAIN_PROB": "0.90",
    "G2E_RANDOM_TERRAIN_MAX_H": "0.055",   # mostly LOW obstacles -- STEP_OVER territory
    "G2E_OBSTACLE_COUNT": "5", "G2E_OBSTACLE_TALL_FRAC": "0.15",  # a few walls -> HALT
    "G2E_OBSTACLE_SPAN_FRAC": "0.0", "G2E_OBSTACLE_X_HI": "1.0", "G2E_OBSTACLE_Y_SPREAD": "0.12",
    "G2E_LEDGE_HEIGHT": "0.022", "G2E_LEDGE_PROB": "0.45", "G2E_LEDGE_RANDOMIZE": "1",
    "G2E_RUBBLE_PROB": "0.30", "G2E_SLOPE_MAX_DEG": "8",
}
for k, v in _DEFAULTS.items():
    os.environ.setdefault(k, v)

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pybullet as p                                                   # noqa: E402
import opencat_gym_env                                                 # noqa: E402
from stable_baselines3 import PPO                                      # noqa: E402
from opencat_gym_env import (OpenCatGymEnv, RESIDUAL_SCALE_DEG, WKF_REF,  # noqa: E402
                             STAND_POSE, TIME_PHASE_PERIOD)
from pi_pipeline.gait.skill_switch import (SkillSwitch, SkillSwitchConfig,  # noqa: E402
                                          SkillRefs, GaitMode, Source)
from pi_pipeline.vision.gait_selector import GaitSelector, TerrainReading  # noqa: E402

REF_DIR = os.path.join(os.path.dirname(__file__), "reference_gait")


def _load(name):
    return np.load(os.path.join(REF_DIR, name))


def make_switch():
    refs = SkillRefs(
        step_over=_load("tr_ref.npy"),          # trot -- widest foot lift of the built-ins
        inspect=_load("cr_ref.npy"),            # crouch -- pitches the mast down
        stance=WKF_REF.mean(axis=0),            # neutral four-foot pose
    )
    return SkillSwitch(refs, SkillSwitchConfig(
        blend_in_steps=6, blend_out_steps=6, step_over_cycles=1.0,
        play_ticks_per_cycle=48))


def rl_joint_deg(env, action):
    """Mirror the env's residual->joint map, in degrees, BEFORE stepping."""
    ref = STAND_POSE if abs(env._cmd_fwd) < 0.025 else WKF_REF[int(env._phase) % len(WKF_REF)]
    return np.rad2deg(ref + np.asarray(action) * np.deg2rad(RESIDUAL_SCALE_DEG))


def terrain_reading(env):
    raw = env._scan_terrain()                   # [present, dist_norm, bearing_norm, tall]
    return TerrainReading(present=raw[0] > 0.5, dist_norm=float(raw[1]),
                          bearing_norm=float(raw[2]), tall=raw[3] > 0.5)


def _grab(env, w, h):
    pos = p.getBasePositionAndOrientation(env.robot_id)[0]
    _, _, rgb, _, _ = p.getCameraImage(
        w, h,
        viewMatrix=p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[pos[0], pos[1], 0.05], distance=0.55,
            yaw=50, pitch=-28, roll=0, upAxisIndex=2),
        projectionMatrix=p.computeProjectionMatrixFOV(60, w / h, 0.1, 5),
        renderer=p.ER_TINY_RENDERER)
    return np.reshape(rgb, (h, w, 4))[:, :, :3].astype(np.uint8)


def run_episode(env, model, switch, selector, max_steps=260, cap=None):
    obs, _ = env.reset()
    if switch is not None:
        switch.reset()
        selector.reset()
    x0 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
    counts = {m: 0 for m in GaitMode}
    src_counts = {s: 0 for s in Source}
    fell = False
    for k in range(max_steps):
        action, _ = model.predict(obs, deterministic=True)
        mode, src = GaitMode.CRUISE, Source.RL
        if switch is not None:
            mode = selector.update(terrain_reading(env))
            gp = (env._phase / TIME_PHASE_PERIOD) % 1.0
            joints, src = switch.update(mode, rl_joint_deg(env, action), gait_phase=gp)
            counts[mode] += 1
            src_counts[src] += 1
            if src is Source.RL:
                obs, _, term, trunc, info = env.step(action)
            else:
                env._abs_joint_override = joints
                obs, _, term, trunc, info = env.step(np.zeros(8, dtype=np.float32))
                env._abs_joint_override = None
        else:
            counts[GaitMode.CRUISE] += 1
            obs, _, term, trunc, info = env.step(action)
        if cap is not None and k % cap["stride"] == 0:
            cap["frames"].append(_grab(env, cap["w"], cap["h"]))
            cap["labels"].append((mode.value, src.value))
        if term or trunc:
            fell = bool(term)
            break
    x1 = p.getBasePositionAndOrientation(env.robot_id)[0][0]
    return {"fell": fell, "fwd_m": x1 - x0, "modes": counts, "srcs": src_counts}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--no-switch", action="store_true", help="baseline: run20m_ppo alone")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default="trained/run20m_ppo")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--gif", default=None, help="write a labelled GIF of the run here")
    ap.add_argument("--gif-stride", type=int, default=3)
    ap.add_argument("--gif-w", type=int, default=440)
    ap.add_argument("--gif-h", type=int, default=300)
    args = ap.parse_args()

    opencat_gym_env.GUI_MODE = args.render
    env = OpenCatGymEnv()
    model = PPO.load(args.model, device="cpu")
    switch = None if args.no_switch else make_switch()
    selector = None if args.no_switch else GaitSelector()

    tag = "SWITCH" if switch else "BASELINE"
    cap = {"frames": [], "labels": [], "stride": args.gif_stride,
           "w": args.gif_w, "h": args.gif_h} if args.gif else None
    fell = 0
    fwd, wall_stop = [], []          # wall_stop[e] True if HALT dominated the episode
    agg_modes = {m: 0 for m in GaitMode}
    for e in range(args.episodes):
        np.random.seed(args.seed + e)
        r = run_episode(env, model, switch, selector, cap=cap)
        fell += r["fell"]
        fwd.append(r["fwd_m"])
        halt_frac = (r["modes"][GaitMode.HALT] / max(1, sum(r["modes"].values()))) if switch else 0.0
        wall_stop.append(halt_frac > 0.5)
        for m, c in r["modes"].items():
            agg_modes[m] += c
        print(f"[{tag} ep {e:2d}] fell={r['fell']!s:5s} fwd={r['fwd_m']:+.2f} m"
              + ("" if switch is None else
                 f"  modes={{ {', '.join(f'{m.value}:{c}' for m,c in r['modes'].items() if c)} }}"))
    env.close()

    walked = [d for d, w in zip(fwd, wall_stop) if not w]
    out = {
        "tag": tag, "episodes": args.episodes, "seed": args.seed,
        "fall_rate": fell / args.episodes,
        "fwd_mean_all": float(np.mean(fwd)),
        "wall_stops": int(sum(wall_stop)),
        "fwd_mean_walked": float(np.mean(walked)) if walked else None,
        "n_walked": len(walked),
        "mode_mix": {m.value: agg_modes[m] for m in GaitMode if agg_modes[m]},
    }
    print(f"\n=== {tag}  {args.episodes} eps ===")
    print(f"fall rate         {out['fall_rate']:.0%}  ({fell}/{args.episodes})")
    print(f"wall-stops        {out['wall_stops']}  (HALT dominated -- correctly refused a wall)")
    print(f"fwd, walked eps   mean {out['fwd_mean_walked']}   (n={out['n_walked']})")
    print(f"fwd, all eps      mean {out['fwd_mean_all']:+.2f} m")
    if switch is not None:
        tot = sum(agg_modes.values()) or 1
        print("mode mix          " + "  ".join(f"{m.value} {c/tot:.0%}" for m, c in agg_modes.items() if c))
    if args.json_out:
        json.dump(out, open(args.json_out, "w"), indent=2)
        print(f"wrote {args.json_out}")

    if cap and cap["frames"]:
        _write_gif(cap, args.gif)


_SRC_DOT = {"rl": (90, 170, 240), "blend": (240, 200, 90), "scripted": (240, 120, 90)}


def _write_gif(cap, path):
    from PIL import Image, ImageDraw
    imgs = []
    for frame, (mode, src) in zip(cap["frames"], cap["labels"]):
        im = Image.fromarray(frame)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, 18], fill=(20, 20, 24))
        d.ellipse([5, 5, 13, 13], fill=_SRC_DOT.get(src, (200, 200, 200)))
        d.text((18, 4), f"{src.upper():8s} {mode}", fill=(235, 235, 235))
        imgs.append(im)
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=int(1000 * cap["stride"] / 50), loop=0, optimize=True)
    print(f"wrote {path}  ({len(imgs)} frames)")


if __name__ == "__main__":
    main()
