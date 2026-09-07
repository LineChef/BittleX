"""Obstacle-response eval -- the behaviour the reward curve is blind to.

For each checkpoint, roll out matched-seed episodes on the obstacle-dense course
and, per obstacle *encounter* (vision says something is in the forward cone),
measure what the policy actually does about it:

  decel_ratio    mean forward speed in the ~8 steps before first contact,
                 / this episode's obstacle-free cruise speed.  < 1 => it slowed.
  peak_force_N   largest foot/body-vs-obstacle normal force in the encounter
                 (gentle meet vs slam).
  pitch_std_deg  body-pitch wobble while the obstacle is close (dist_norm<0.3).
  clip_rate      fraction of encounters with any foot-vs-obstacle contact.
  fall_rate      fraction of encounters the robot falls within 25 steps of.
  tall_fall_rate same, restricted to encounters with tall_flag set.

Also splits the env's per-term reward dict into NEAR (obstacle close) vs CLEAR
buckets, so "same ep_rew_mean" still shows which components moved near obstacles.

_scan_terrain is called directly every step, so a vision-BLIND (278-d) checkpoint
is measured on the exact same encounters as a vision (282-d) one -- the metric
doesn't depend on the policy seeing the feature, only on the scene.

  python eval_obstacle_response.py trained/vis_A_on_ppo trained/vis_A_off_ppo --episodes 40
  python eval_obstacle_response.py trained/vis_A_on_ppo --course A --json-out /tmp/resp_A_on.json
"""
import argparse
import json
import os

import numpy as np

# --- course knobs (mirror train_vision_smoke.COURSES); set before importing env
COURSES = {
    "A": dict(RANDOM_TERRAIN="0.06", RANDOM_TERRAIN_PROB="0.9", RANDOM_TERRAIN_MAX_H="0.09",
              OBSTACLE_COUNT="6", OBSTACLE_TALL_FRAC="0.35", OBSTACLE_SPAN_FRAC="0.18",
              LEDGE_HEIGHT="0.028", LEDGE_PROB="0.45", LEDGE_RANDOMIZE="1",
              RUBBLE_PROB="0.30", SLOPE_MAX_DEG="10"),
    "B": dict(RANDOM_TERRAIN="0.025", RANDOM_TERRAIN_PROB="0.35", RANDOM_TERRAIN_MAX_H="0.010",
              OBSTACLE_TALL_FRAC="0.0", OBSTACLE_SPAN_FRAC="0.0",
              RUBBLE_PROB="0.85", SLOPE_MAX_DEG="14"),
    "C": dict(RANDOM_TERRAIN="0.045", RANDOM_TERRAIN_PROB="0.70", RANDOM_TERRAIN_MAX_H="0.07",
              OBSTACLE_COUNT="6", OBSTACLE_TALL_FRAC="0.25", OBSTACLE_SPAN_FRAC="0.12",
              LEDGE_HEIGHT="0.022", LEDGE_PROB="0.35", LEDGE_RANDOMIZE="1",
              RUBBLE_PROB="0.60", SLOPE_MAX_DEG="12"),
}

ap = argparse.ArgumentParser()
ap.add_argument("checkpoints", nargs="+")
ap.add_argument("--course", default="A", choices=list(COURSES))
ap.add_argument("--episodes", type=int, default=40)
ap.add_argument("--seed0", type=int, default=10_000)
ap.add_argument("--json-out", default=None)
args = ap.parse_args()

for k, v in COURSES[args.course].items():
    os.environ["G2E_" + k] = v

import pybullet as p
import opencat_gym_env
opencat_gym_env.DR_EVAL_FULL = True          # force obstacles at reset (dr=1)
PAW_LINKS = [3, 6, 9, 12]
EPISODE_CAP = 250
APPROACH_W = 8                                # steps before contact to average speed over
NEAR = 0.30                                   # dist_norm below this = "obstacle close"
ENTER = 0.45                                  # encounter starts when present & dist_norm < this


def obstacle_bodies(env):
    ignore = {0, env.robot_id}
    for a in ("_payload_id", "_head_id"):
        v = getattr(env, a, None)
        if v is not None:
            ignore.add(v)
    return {p.getBodyUniqueId(i) for i in range(p.getNumBodies())} - ignore


def run(checkpoint, want_terrain):
    from stable_baselines3 import PPO
    model = PPO.load(checkpoint)
    obs_dim = model.observation_space.shape[0]
    _extra = obs_dim - opencat_gym_env.SIZE_OBSERVATION
    opencat_gym_env.TERRAIN_FEATURE = (_extra >= 4)
    opencat_gym_env.GOAL_MODE = (_extra >= 7)   # 4 terrain + 3 goal
    from opencat_gym_env import OpenCatGymEnv
    env = OpenCatGymEnv()

    # obstacle-free cruise baseline: same policy, boxes/rubble/ledges off
    _keep = {k: getattr(opencat_gym_env, k) for k in
             ("RANDOM_TERRAIN_PROB", "RUBBLE_PROB", "LEDGE_HEIGHT")}
    for k in _keep:
        setattr(opencat_gym_env, k, 0.0)
    _cru = []
    for e in range(4):
        np.random.seed(args.seed0 + 900 + e)
        o, _ = env.reset()
        for _ in range(EPISODE_CAP):
            a, _ = model.predict(o, deterministic=True)
            o, _, term, trunc, _ = env.step(a)
            _cru.append(p.getBaseVelocity(env.robot_id)[0][0])
            if term or trunc:
                break
    cruise_free = float(np.mean(_cru))
    for k, v in _keep.items():
        setattr(opencat_gym_env, k, v)

    encounters = []
    ep_falls = 0
    rterms_near, rterms_clear = {}, {}
    for e in range(args.episodes):
        np.random.seed(args.seed0 + e)
        obs, _ = env.reset()
        rid = env.robot_id
        boxes = obstacle_bodies(env)
        cruise_v, step = [], 0
        enc = None                                  # current open encounter
        fell_step = None
        while True:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(action)
            step += 1
            vx = p.getBaseVelocity(rid)[0][0]
            pitch = p.getEulerFromQuaternion(p.getBasePositionAndOrientation(rid)[1])[1]
            present, dist_n, bearing_n, tall = env._scan_terrain()
            hitforce = 0.0
            for link in PAW_LINKS + [-1]:
                for c in p.getContactPoints(bodyA=rid, linkIndexA=link):
                    if c[2] in boxes:
                        hitforce = max(hitforce, c[9])
            bucket = rterms_near if (present and dist_n < NEAR) else (
                rterms_clear if not present else None)
            if bucket is not None:
                for k, v in info.items():
                    if k.startswith("r_"):
                        bucket.setdefault(k, []).append(float(v))
            if (not present) or dist_n > 0.75:      # obstacle-free OR still far => cruise baseline
                cruise_v.append(vx)

            if present and dist_n < ENTER and enc is None:
                enc = dict(start=step, tall=bool(tall), vlog=[], pitchlog=[],
                           peak=0.0, contact_step=None)
            if enc is not None:
                enc["vlog"].append(vx)
                if dist_n < NEAR:
                    enc["pitchlog"].append(pitch)
                enc["peak"] = max(enc["peak"], hitforce)
                if hitforce > 0 and enc["contact_step"] is None:
                    enc["contact_step"] = step
                if (not present) or terminated or step - enc["start"] > 60:
                    enc["end"] = step
                    encounters.append(enc)
                    enc = None

            if terminated and fell_step is None and step < EPISODE_CAP:
                fell_step = step
            if terminated or truncated:
                break
        if fell_step is not None:
            ep_falls += 1
            for en in encounters:
                if en.get("end", en["start"]) >= fell_step - 25 and "fell" not in en:
                    en["fell"] = True
        for en in encounters:
            if "cruise" not in en:
                en["cruise"] = cruise_free

    # ---- aggregate ----
    def agg(sel):
        rows = [en for en in encounters if sel(en)]
        if not rows:
            return None
        decel = []
        for en in rows:
            cs = en["contact_step"] or en["end"]
            w = en["vlog"][max(0, cs - en["start"] - APPROACH_W): max(1, cs - en["start"])]
            if w and en["cruise"] == en["cruise"] and en["cruise"] > 1e-4:
                decel.append(float(np.mean(w)) / en["cruise"])
        return dict(
            n=len(rows),
            decel_ratio=round(float(np.mean(decel)), 3) if decel else None,
            peak_force_N=round(float(np.mean([en["peak"] for en in rows])), 1),
            pitch_std_deg=round(float(np.mean([np.std(en["pitchlog"]) for en in rows
                                               if en["pitchlog"]]) * 180 / np.pi), 2),
            clip_rate=round(float(np.mean([en["contact_step"] is not None for en in rows])), 3),
            fall_rate=round(float(np.mean([en.get("fell", False) for en in rows])), 3),
        )

    out = dict(
        checkpoint=checkpoint, obs_dim=obs_dim,
        vision_policy=bool(opencat_gym_env.TERRAIN_FEATURE),
        episodes=args.episodes, ep_fall_rate=round(ep_falls / args.episodes, 3),
        n_encounters=len(encounters),
        all=agg(lambda en: True),
        tall=agg(lambda en: en["tall"]),
        low=agg(lambda en: not en["tall"]),
        reward_near={k: round(float(np.mean(v)), 2) for k, v in sorted(rterms_near.items())},
        reward_clear={k: round(float(np.mean(v)), 2) for k, v in sorted(rterms_clear.items())},
    )
    env.close()
    return out


def fmt(o):
    print(f"\n### {o['checkpoint']}   obs={o['obs_dim']}  vision_policy={o['vision_policy']}")
    print(f"    episode fall rate {o['ep_fall_rate']}   encounters {o['n_encounters']}")
    for name in ("all", "tall", "low"):
        a = o[name]
        if a:
            print(f"    {name:4s} n={a['n']:3d}  decel={a['decel_ratio']}  "
                  f"peakF={a['peak_force_N']}N  pitchStd={a['pitch_std_deg']}deg  "
                  f"clip={a['clip_rate']}  fall={a['fall_rate']}")


results = [run(c, None) for c in args.checkpoints]
for o in results:
    fmt(o)
if len(results) == 2:
    a, b = results
    print(f"\n=== {os.path.basename(a['checkpoint'])}  vs  {os.path.basename(b['checkpoint'])} "
          f"(near-obstacle) ===")
    keys = sorted(set(a["reward_near"]) | set(b["reward_near"]))
    for k in keys:
        va, vb = a["reward_near"].get(k, 0.0), b["reward_near"].get(k, 0.0)
        if abs(va - vb) > 0.5:
            print(f"    {k:20s} {va:8.2f}  {vb:8.2f}   d={va - vb:+.2f}")
if args.json_out:
    with open(args.json_out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nwrote {args.json_out}")
