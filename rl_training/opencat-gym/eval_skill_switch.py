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
    "G2E_CLIFF_PLATFORM_HW": "0.28",   # edge ~0.28 m ahead -- reachable within an episode
}
for k, v in _DEFAULTS.items():
    os.environ.setdefault(k, v)


def _argv_val(flag, default):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return default


# --cliff-prob has to reach the env module BEFORE it's imported (it reads _g2e
# at import). Peek argv here; argparse registers it too for --help / validation.
os.environ.setdefault("G2E_CLIFF_PROB", _argv_val("--cliff-prob", "0.0"))

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import pybullet as p                                                   # noqa: E402
import opencat_gym_env                                                 # noqa: E402
from stable_baselines3 import PPO                                      # noqa: E402
from opencat_gym_env import (OpenCatGymEnv, RESIDUAL_SCALE_DEG, WKF_REF,  # noqa: E402
                             STAND_POSE, TIME_PHASE_PERIOD)
from pi_pipeline.gait.skill_switch import (SkillSwitch, SkillSwitchConfig,  # noqa: E402
                                          SkillRefs, GaitMode, Source)
from pi_pipeline.vision.gait_selector import GaitSelector, TerrainReading  # noqa: E402
from pi_pipeline.vision.cliff_guard import CliffGuard, CliffAction, EdgeReading  # noqa: E402

# CliffGuard action -> which GaitMode it forces (no turning in this sim, so
# TURN_AWAY / BACK_UP fall back to HALT -- the safe stop).
_CLIFF_TO_MODE = {
    CliffAction.NONE: None,
    CliffAction.SLOW: GaitMode.CAREFUL,
    CliffAction.STOP: GaitMode.HALT,
    CliffAction.BACK_UP: GaitMode.HALT,
    CliffAction.TURN_AWAY_LEFT: GaitMode.HALT,
    CliffAction.TURN_AWAY_RIGHT: GaitMode.HALT,
    CliffAction.FREEZE: GaitMode.HALT,
}

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


_EDGE_RANGE = 0.35        # m look-ahead for the "is there floor?" probes


def edge_reading(env):
    """Downward probe rays ahead of the robot -- more robust than an in-box
    horizontal scan. A probe that finds no floor near the walking surface = a
    drop-off at that point. Mirrors a real camera 'floor vs edge' check."""
    (x, y, z), orn = p.getBasePositionAndOrientation(env.robot_id)
    yaw = p.getEulerFromQuaternion(orn)[2]
    nearest, bearing, present = 1.0, 0.0, False
    for frac in np.linspace(0.06, _EDGE_RANGE, 6):
        for b in (-0.3, 0.0, 0.3):
            px, py = x + frac * np.cos(yaw + b), y + frac * np.sin(yaw + b)
            hit = p.rayTest([px, py, z + 0.05], [px, py, z - 0.40])[0]
            floor = hit[0] >= 0 and hit[0] != env.robot_id and hit[3][2] > z - 0.15
            if not floor:
                present = True
                if frac / _EDGE_RANGE < nearest:
                    nearest, bearing = frac / _EDGE_RANGE, b / 0.5
    return EdgeReading(present=present, dist_norm=nearest, bearing_norm=bearing,
                       confidence=1.0)


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


def _body_xz(env):
    pos = p.getBasePositionAndOrientation(env.robot_id)[0]
    return pos[0], pos[2]


def _body_pitch(env):
    q = p.getBasePositionAndOrientation(env.robot_id)[1]
    return p.getEulerFromQuaternion(q)[1]        # +ve = nose down (this URDF)


def run_episode(env, model, switch, selector, cliff=None, max_steps=260, cap=None,
                careful_scale=True, fwd_cmd=None):
    obs, _ = env.reset()
    if switch is not None:
        switch.reset()
        selector.reset()
    if cliff is not None:
        cliff.reset()
    cliff_ep = bool(getattr(env, "_cliff_this_ep", False))
    base_cmd = float(fwd_cmd) if fwd_cmd is not None else float(env._cmd_fwd)
    x0, _ = _body_xz(env)
    counts = {m: 0 for m in GaitMode}
    src_counts = {s: 0 for s in Source}
    z_by_src = {s: [] for s in Source}             # body height while each source drives
    pitch_by_src = {s: [] for s in Source}         # body pitch (nose-down +) per source
    enc = []                                       # per obstacle encounter
    cur = None
    fell = False
    for k in range(max_steps):
        if fwd_cmd is not None:
            env._cmd_fwd = base_cmd                  # hold a fixed march command (E-4c)
        action, _ = model.predict(obs, deterministic=True)
        mode, src = GaitMode.CRUISE, Source.RL
        rd = terrain_reading(env) if switch is not None else None
        cliff_act = None
        if switch is not None:
            mode = selector.update(rd)
            if cliff is not None:                        # cliff reflex preempts the terrain selector
                cliff_act = cliff.update(edge_reading(env))
                forced = _CLIFF_TO_MODE.get(cliff_act)
                if forced is not None:
                    mode = forced
            gp = (env._phase / TIME_PHASE_PERIOD) % 1.0
            joints, src = switch.update(mode, rl_joint_deg(env, action), gait_phase=gp)
            counts[mode] += 1
            src_counts[src] += 1
            if careful_scale:
                env._cmd_fwd = base_cmd * switch.speed_scale
            if src is Source.RL:
                obs, _, term, trunc, info = env.step(action)
            else:
                env._abs_joint_override = joints
                obs, _, term, trunc, info = env.step(np.zeros(8, dtype=np.float32))
                env._abs_joint_override = None
        else:
            counts[GaitMode.CRUISE] += 1
            obs, _, term, trunc, info = env.step(action)

        bx, bz = _body_xz(env)
        z_by_src[src].append(bz)
        pitch_by_src[src].append(_body_pitch(env))

        # obstacle-encounter tracking (switch runs only; needs the scan reading)
        if rd is not None:
            if rd.present and cur is None:
                cur = {"x0": bx, "tall": rd.tall, "modes": {m: 0 for m in GaitMode},
                       "zmin": bz, "zmax": bz, "steps": 0}
            if cur is not None:
                cur["modes"][mode] += 1
                cur["zmin"] = min(cur["zmin"], bz)
                cur["zmax"] = max(cur["zmax"], bz)
                cur["steps"] += 1
                if not rd.present:
                    cur["passed_m"] = bx - cur["x0"]
                    enc.append(cur)
                    cur = None
        if cap is not None and k % cap["stride"] == 0:
            cap["frames"].append(_grab(env, cap["w"], cap["h"]))
            cap["labels"].append((mode.value, src.value))
        if term or trunc:
            fell = bool(term)
            break
    if cur is not None:
        cur["passed_m"] = _body_xz(env)[0] - cur["x0"]
        enc.append(cur)
    x1, bz = _body_xz(env)
    # went off the drop-off = terminated by the platform-fall check, OR ended the
    # episode with the body at/below the platform surface (dangling half-off).
    fell_at_edge = bool(cliff_ep and (fell or bz < 0.03))
    return {"fell": fell, "fwd_m": x1 - x0, "modes": counts, "srcs": src_counts,
            "z_by_src": z_by_src, "pitch_by_src": pitch_by_src, "encounters": enc,
            "cliff_ep": cliff_ep, "fell_at_edge": fell_at_edge}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--no-switch", action="store_true", help="baseline: run20m_ppo alone")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--seeds", default=None,
                    help="comma list of seed offsets to pool, e.g. 0,10,20,30,40 (sweep)")
    ap.add_argument("--model", default="trained/run20m_ppo")
    ap.add_argument("--cliff-prob", default="0.0",
                    help="frac of episodes on a finite platform (drop-off). Switch arm "
                         "runs CliffGuard on the edge scan; baseline is blind to it.")
    ap.add_argument("--fwd-cmd", type=float, default=None,
                    help="force a fixed forward command each tick (e.g. 0.12) instead of "
                         "the env's sampled/resampled command -- for E-4c, march at the edge")
    ap.add_argument("--max-steps", type=int, default=260)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--gif", default=None, help="write a labelled GIF of the run here")
    ap.add_argument("--gif-stride", type=int, default=3)
    ap.add_argument("--gif-w", type=int, default=440)
    ap.add_argument("--gif-h", type=int, default=300)
    args = ap.parse_args()

    opencat_gym_env.GUI_MODE = args.render
    opencat_gym_env.DR_EVAL_FULL = True    # every episode at full DR (obstacles, cliff,
                                          # slopes) from episode 0 -- not a training ramp
    env = OpenCatGymEnv()
    model = PPO.load(args.model, device="cpu")
    switch = None if args.no_switch else make_switch()
    selector = None if args.no_switch else GaitSelector()
    cliff = CliffGuard() if (switch and float(args.cliff_prob) > 0) else None

    tag = "SWITCH" if switch else "BASELINE"
    cap = {"frames": [], "labels": [], "stride": args.gif_stride,
           "w": args.gif_w, "h": args.gif_h} if args.gif else None
    offsets = [int(s) for s in args.seeds.split(",")] if args.seeds else [0]

    fell = 0
    fwd, wall_stop = [], []
    agg_modes = {m: 0 for m in GaitMode}
    z_src = {s: [] for s in Source}
    pitch_src = {s: [] for s in Source}
    enc_step, enc_nostep = [], []        # per-encounter passed_m, split by whether STEP_OVER fired
    cliff_eps = edge_falls = 0
    for base in offsets:
        for e in range(args.episodes):
            np.random.seed(args.seed + base + e)
            r = run_episode(env, model, switch, selector, cliff=cliff, cap=cap,
                            max_steps=args.max_steps, fwd_cmd=args.fwd_cmd)
            fell += r["fell"]
            cliff_eps += r["cliff_ep"]
            edge_falls += r["fell_at_edge"]
            fwd.append(r["fwd_m"])
            halt_frac = (r["modes"][GaitMode.HALT] / max(1, sum(r["modes"].values()))) if switch else 0.0
            wall_stop.append(halt_frac > 0.5)
            for m, c in r["modes"].items():
                agg_modes[m] += c
            for s in Source:
                z_src[s].extend(r.get("z_by_src", {}).get(s, []))
                pitch_src[s].extend(r.get("pitch_by_src", {}).get(s, []))
            for en in r.get("encounters", []):
                if en["modes"][GaitMode.HALT] > 0.5 * en["steps"]:
                    continue                      # wall stop -- not a traverse
                (enc_step if en["modes"][GaitMode.STEP_OVER] > 0 else enc_nostep).append(en["passed_m"])
            print(f"[{tag} s{args.seed+base}+{e:2d}] fell={r['fell']!s:5s} fwd={r['fwd_m']:+.2f} m"
                  + ("" if switch is None else
                     f"  {', '.join(f'{m.value}:{c}' for m,c in r['modes'].items() if c)}"))
    env.close()

    n = len(fwd)
    walked = [d for d, w in zip(fwd, wall_stop) if not w]
    def _ms(a): return (float(np.mean(a)), float(np.std(a))) if a else (None, None)
    fw_m, fw_s = _ms(walked)
    out = {
        "tag": tag, "episodes_per_seed": args.episodes, "seed_offsets": offsets, "n_episodes": n,
        "fall_rate": fell / n,
        "cliff_episodes": cliff_eps,
        "edge_falls": edge_falls,
        "edge_fall_rate": (edge_falls / cliff_eps) if cliff_eps else None,
        "wall_stops": int(sum(wall_stop)),
        "fwd_walked_mean": fw_m, "fwd_walked_std": fw_s, "n_walked": len(walked),
        "fwd_all_mean": float(np.mean(fwd)),
        "mode_mix": {m.value: agg_modes[m] for m in GaitMode if agg_modes[m]},
        "encounter_passed_m_with_stepover": _ms(enc_step),
        "encounter_passed_m_no_stepover": _ms(enc_nostep),
        "n_enc_stepover": len(enc_step), "n_enc_nostep": len(enc_nostep),
        "body_z_mean_by_source": {s.value: (_ms(z_src[s])[0]) for s in Source if z_src[s]},
        "body_pitch_mean_by_source": {s.value: (_ms(pitch_src[s])[0]) for s in Source if pitch_src[s]},
    }
    print(f"\n=== {tag}  {n} eps ({len(offsets)} seed offsets x {args.episodes}) ===")
    print(f"fall rate            {out['fall_rate']:.0%}  ({fell}/{n})")
    if cliff_eps:
        print(f"EDGE falls           {edge_falls}/{cliff_eps} drop-off episodes"
              f"  ({out['edge_fall_rate']:.0%})")
    print(f"wall-stops           {out['wall_stops']}/{n}")
    print(f"fwd, walked eps      {fw_m:.3f} +/- {fw_s:.3f} m  (n={len(walked)})")
    if switch is not None:
        tot = sum(agg_modes.values()) or 1
        print("mode mix             " + "  ".join(f"{m.value} {c/tot:.0%}" for m, c in agg_modes.items() if c))
        es_m, es_s = _ms(enc_step); en_m, en_s = _ms(enc_nostep)
        print(f"encounter passed_m   with STEP_OVER: {es_m} +/-{es_s} (n={len(enc_step)})   "
              f"without: {en_m} +/-{en_s} (n={len(enc_nostep)})")
        print("body-z by source     " + "  ".join(
            f"{s.value} {out['body_z_mean_by_source'][s.value]:.3f}"
            for s in Source if s.value in out["body_z_mean_by_source"]))
        print("body-pitch by source " + "  ".join(
            f"{s.value} {out['body_pitch_mean_by_source'][s.value]:+.3f}"
            for s in Source if s.value in out["body_pitch_mean_by_source"]))
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
