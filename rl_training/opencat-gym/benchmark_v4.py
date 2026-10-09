"""Benchmark v4 (V3 plan, docs/rl/v3-retrain-plan.md section 3): the decathlon ladder on the shared G2 profile, plus cells that look the way G2 is
actually tested, scored in parallel.

    python benchmark_v4.py --policy trained/<tag>_ppo --json-out out.json [--jobs 6] [--cells all|core|stage:s3_snag|T1.1,N1,...]
                           [--episodes 40] [--hard-scale 1.1] [--levers heading_obs] [--policy scripted]

What changed from benchmark_decathlon.py (BENCH_VERSION 3):
  * the environment comes from g2_profile.scoring_env() (payload, mass, send-every-3rd, IMU path ... all in one place)
  * 40 episodes per cell by default (20-24 carries about +-15 points of noise on a fall rate); the same seeds for every policy
  * fall detection works past 250 steps (evaluate_policy.run_episode called any long episode "not fell")
  * new cells N1-N6 (12.5 s calm walk as G2 is tested, 60 s endurance, stuck FL shoulder, battery sag, constant yaw push, turn tracking)
  * new measures: signed heading change, speed early vs late (slow-down), roll / pitch std, left-right asymmetry of the mean joints (a learned
    one-sided bias like V2.1's), share of commanded joint speed above the servo ceiling
  * --hard-scale F: the hardest rung of each category x F ("T2.2+10%" ...), labelled not comparable with older runs
  * --jobs N: cells are split across N worker processes (greedy by cost), results merged in ladder order
Carpet cell T10.1 is reported, never gated (tag "info"). `gate_cells()` lists the cells that count.

BENCH_VERSION 5 (2026-10-07) adds the DIFFICULTY-LEVEL LADDER (`--ladder`), the benchmark's version of training's difficulty levels:
  * training raises four hazard categories (terrain, ledge, slope, fault) from 0 to 1 as the policy earns it (opencat_gym_env CATEGORY_LEVELS; the Curriculum probe in
    train.py); the ladder scores the finished policy at fixed levels 0.25 / 0.5 / 0.75 / 1.0 of each category (the others at 0) plus a clean floor, in the SAME world
    the final stage trains in (g2_profile.env_for(..., stage="s6_full_strength")), with the SAME measure as the probe (episode score = survived x fraction of the commanded
    distance covered; a fall = peak tilt > 1.3 rad scores 0), the SAME relative score (raw / max(clean floor, 0.30)) and the SAME promotion threshold (LEVEL_UP_SCORE, 0.80)
  * one more rung per category at level 1.0 with G2E_HARD_SCALE 1.10, the hardest world the 20M run trains in
  * result: res["ladder"] = {"cells": [...], "summary": ladder_summary(...)}; summary["categories"][c]["competence"] = the highest level the policy is "ready for" in the
    training sense (the level the curriculum would have reached), contiguous from 0.25
  * the T / N cells are unchanged (a policy scored on version 4 compares cell for cell)
"""
import argparse
import json
import math
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np

import g2_profile

D = math.radians
BENCH_VERSION = 5
STEPS_HZ = 80.0
JOINT_PAIRS = ((0, 2), (1, 3), (4, 6), (5, 7))           # FLsh-FRsh, FLel-FRel, BRhip-BLhip, BRkn-BLkn (URDF order; L-R pairs)
PAIR_NAMES = ("shoulder_FL-FR", "elbow_FL-FR", "hip_BR-BL", "knee_BR-BL")

# New cells: (id, label, knobs, episodes, steps per episode, extra command (fwd, yaw) or None). "_steps" is the episode length.
N_CELLS = [
    ("N1", "Calm flat walk, 12.5 s (as G2 is tested)", {}, 40, 1000, None),
    ("N2", "Endurance, 60 s", {}, 8, 4800, None),
    ("N3", "FL shoulder stuck at 42 deg (servo 8), 12.5 s",
     {"FAULT_STUCK_PROB": 1.0, "FAULT_STUCK_JOINT": 0, "FAULT_STUCK_DEG": 42.0}, 40, 1000, None),
    ("N4", "Battery sag: all motors 90%, 12.5 s", {"MOTOR_SCALE_ALL": 0.9}, 40, 1000, None),
    ("N5", "Constant yaw push (0..0.3 N*m, random sign), 12.5 s", {"DRIFT_TORQUE": 0.3, "DRIFT_PROB": 1.0}, 40, 1000, None),
    ("N6a", "Turn left at 0.20 rad/s, 6 s", {}, 20, 500, (0.10, 0.20)),
    ("N6b", "Turn right at 0.20 rad/s, 6 s", {}, 20, 500, (0.10, -0.20)),
    # L1 (2026-10-07, the length level, docs/rl/v3-decisions-log.md): a 40 s straight walk under a constant yaw push of +/-0.25 N*m that ALTERNATES by episode (even episodes push right, odd push left), 16 episodes.
    # Reports the heading change per side (heading_even_abs_mean_deg = right pushes, heading_odd_abs_mean_deg = left pushes) and their gap, so a policy that corrects only one direction shows it.
    ("L1", "Long run, 40 s, alternating yaw push +/-0.25 N*m", {"LONG_RUN_PUSH": 0.25}, 16, 3200, None),
    # V5 (2026-10-09, docs/plan-detail/v5-training-plan.md): the side-hill in BOTH directions (T3.2 only tests the right side down; V4 fell 0.26 that way and 0.49 the
    # other way) and the ledge split into up and down (the random-direction T5 cells hide which one fails). Same 3.1 s length as the T cells.
    ("SL10", "Side-hill 10 deg, LEFT side down (T3.2's mirror)", {"SLOPE_FIXED_RP": (-math.radians(10), 0.0)}, 40, None, None),
    ("SR8", "Side-hill 8 deg, right side down", {"SLOPE_FIXED_RP": (math.radians(8), 0.0)}, 40, None, None),
    ("SL8", "Side-hill 8 deg, left side down", {"SLOPE_FIXED_RP": (-math.radians(8), 0.0)}, 40, None, None),
    ("LU15", "Step UP 15 mm", {"LEDGE_HEIGHT": 0.015, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}, 40, None, None),
    ("LD15", "Step DOWN 15 mm", {"LEDGE_HEIGHT": 0.015, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}, 40, None, None),
    ("LU25", "Step UP 25 mm", {"LEDGE_HEIGHT": 0.025, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}, 40, None, None),
    ("LD25", "Step DOWN 25 mm", {"LEDGE_HEIGHT": 0.025, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}, 40, None, None),
    ("LU35", "Step UP 35 mm (V5 training top)", {"LEDGE_HEIGHT": 0.035, "LEDGE_PROB": 1.0, "LEDGE_DIR": 1}, 40, None, None),
    ("LD40", "Step DOWN 40 mm (V5 training top)", {"LEDGE_HEIGHT": 0.040, "LEDGE_PROB": 1.0, "LEDGE_DIR": -1}, 40, None, None),
]
NEW_KNOBS = ("EPISODE_LENGTH", "LEDGE_DIR", "FAULT_STUCK_PROB", "FAULT_STUCK_JOINT", "FAULT_STUCK_DEG", "FAULT_WEAK_PROB", "FAULT_OFFSET_PROB",
             "MOTOR_SCALE_ALL", "MOTOR_SCALE_RAND", "DRIFT_TORQUE", "DRIFT_PROB", "LONG_EP_PROB", "LONG_RUN_PUSH")

# "core" = a fast screen: the cells a screening round is judged on
CORE = ["T1.1", "N1", "N3", "N5", "T2.2", "T3.2", "T5.2", "T7.2", "T8.1", "T9.1", "T10.2"]
STAGE_CELLS = {   # cumulative: what each stage of the chain must keep passing
    "s0_flat": ["T1.1", "T1.2", "N1"],
    "s1_transition": ["T4.1"],
    "s2_step": ["T4.2"],
    "s3_snag": ["T7.2"],
    "s4_ledge": ["T5.1", "T5.2", "T5.3"],
}
INFO_ONLY = {"T10.1"}                                      # carpet: reported, never gated
HARD_SCALE_KEYS = ("LEDGE_HEIGHT", "IMPULSE_PUSH", "RANDOM_PUSH", "TORQUE_CUTBACK", "RUBBLE_MAX_H", "RANDOM_TERRAIN", "SLOPE_FIXED_RP")
HARD_CELLS = ("T2.2", "T3.2", "T5.3", "T6.2", "T7.1", "T8.1", "T9.1", "T11.2")   # the hardest rung of each category


def hard_scaled(knobs, f):
    out = {}
    for k, v in knobs.items():
        if k in HARD_SCALE_KEYS and not k.startswith("_"):
            if isinstance(v, (tuple, list)):
                v = tuple(float(x) * f for x in v)
            elif k == "TORQUE_CUTBACK":
                v = min(0.9, float(v) * f)
            else:
                v = float(v) * f
        out[k] = v
    return out


def cell_table(hard_scale=None):
    """[(id, label, knobs, episodes, steps or None, cmd or None, tag)] for the whole v4 ladder (decathlon cells + N cells)."""
    import benchmark_decathlon as B
    rows = []
    for cid, tier, skill, label, knobs in B.LADDER:
        eps = knobs.get("_episodes")
        real = {k: v for k, v in knobs.items() if k != "_episodes"}
        tag = "info" if cid in INFO_ONLY else "gate"
        if hard_scale and cid in HARD_CELLS:
            real = hard_scaled(real, hard_scale)
            cid, label = f"{cid}+{round((hard_scale - 1) * 100)}%", f"{label}  [hard x{hard_scale}]"
        rows.append((cid, label, real, eps, None, None, tag))
    for cid, label, knobs, eps, steps, cmd in N_CELLS:
        rows.append((cid, label, knobs, eps, steps, cmd, "gate"))
    return rows


def select(rows, spec, hard_scale=None):
    if spec == "all":
        return rows
    ids = []
    for part in spec.split(","):
        if part == "core":
            ids += CORE
        elif part.startswith("stage:"):
            for st in g2_profile.STAGES:
                ids += STAGE_CELLS.get(st[0], [])
                if st[0] == part.split(":", 1)[1]:
                    break
        else:
            ids.append(part)
    base = lambda c: c.split("+")[0]
    return [r for r in rows if base(r[0]) in ids or r[0] in ids]


def n_episodes(row_eps, episodes):
    """A cell's episode count: its own (cells with more samples than the default carry it) scaled by --episodes / 40, at least 2."""
    return episodes if row_eps is None else max(2, round(row_eps * episodes / 40))


def cost(row, default_eps):
    cid, _, knobs, eps, steps, _, _ = row
    return n_episodes(eps, default_eps) * (steps or 250)


# ------------------------------------------------------------------------------------------------ metrics
def v4_metrics(eps_list):
    """eps_list: [(rec, per_term, steps, fell, recovered)] from benchmark_gaits._bench."""
    heads, speeds, early, late, roll_s, pitch_s, jm, over, yrms, falls, clear = [], [], [], [], [], [], [], [], [], [], []
    ep_falls = []                                # per fallen episode: when and which way (2026-10-08 report: how each policy falls)
    path_s, path_e, path_l = [], [], []          # speed ALONG THE PATH (distance walked / time), which a drifting walk does not lose, unlike progress along the start direction
    for rec, pt, steps, fell, _ in eps_list:
        x = np.array(rec["x"])
        xy = np.hypot(np.diff(x), np.diff(np.array(rec["y"], dtype=float))) if rec.get("y") is not None and len(rec["y"]) == len(x) else np.abs(np.diff(x))
        yaw = np.unwrap(np.array(rec["yaw"]))
        heads.append(math.degrees(yaw[-1] - yaw[0]))
        speeds.append(float(x[-1]) / (steps / STEPS_HZ))
        n = max(8, min(250, steps // 3))
        early.append(float(x[n - 1] - x[0]) / ((n - 1) / STEPS_HZ))
        late.append(float(x[-1] - x[-n]) / ((n - 1) / STEPS_HZ))
        path_s.append(float(xy.sum()) / (steps / STEPS_HZ))
        path_e.append(float(xy[:n - 1].sum()) / ((n - 1) / STEPS_HZ))
        path_l.append(float(xy[-(n - 1):].sum()) / ((n - 1) / STEPS_HZ))
        roll_s.append(float(np.degrees(np.std(rec["roll"]))))
        pitch_s.append(float(np.degrees(np.std(rec["pitch"]))))
        jm.append(np.degrees(np.mean(np.array(rec["joint"]), axis=0)))
        over.append(float(np.mean(pt.get("servo_over", [0.0]))))
        yrms.append(float(np.sqrt(np.mean(np.square(rec["yaw_rate"])))))
        if rec.get("foot_z"):                    # swing clearance: the 90th percentile of each paw's height over the episode, mm, averaged over the four paws (a lever must not lower it)
            clear.append(float(np.mean([np.percentile(np.array(fz), 90) for fz in rec["foot_z"] if len(fz)])) * 1000.0)
        tilt = np.maximum(np.abs(rec["roll"]), np.abs(rec["pitch"]))
        falls.append(bool(tilt.max() > 1.3))
        if falls[-1]:
            i = int(np.argmax(tilt > 1.3))
            r_, p_ = float(rec["roll"][i]), float(rec["pitch"][i])
            way = ("sideways, left side down" if r_ < 0 else "sideways, right side down") if abs(r_) >= abs(p_) else ("forward, nose down" if p_ > 0 else "backward, nose up")
            ep_falls.append({"ep": len(falls) - 1, "t_s": round(i / STEPS_HZ, 2), "way": way})
    jm = np.mean(np.array(jm), axis=0)
    asym = [float(jm[a] - jm[b]) for a, b in JOINT_PAIRS]
    h = np.array(heads)
    ev, od = (np.abs(h[0::2]), np.abs(h[1::2]))                       # alternating-sign cells (L1): even episodes = push right, odd = push left
    e, l = float(np.mean(early)), float(np.mean(late))
    pe, pl = float(np.mean(path_e)), float(np.mean(path_l))
    return dict(
        n=len(eps_list), fell_fraction=float(np.mean(falls)), speed_mps=float(np.mean(speeds)),
        speed_early_mps=e, speed_late_mps=l, speed_decay=(1.0 - l / e) if e > 1e-6 else 0.0,      # progress along the START direction: a walk that drifts sideways "decays" without slowing down
        path_speed_mps=float(np.mean(path_s)), path_speed_early_mps=pe, path_speed_late_mps=pl, path_decay=(1.0 - pl / pe) if pe > 1e-6 else 0.0,      # distance walked along the path / time
        heading_mean_deg=float(h.mean()), heading_abs_mean_deg=float(np.abs(h).mean()), heading_std_deg=float(h.std()),
        heading_even_abs_mean_deg=float(ev.mean()) if len(ev) else 0.0, heading_odd_abs_mean_deg=float(od.mean()) if len(od) else 0.0,
        heading_sign_gap_deg=abs(float(ev.mean()) - float(od.mean())) if len(ev) and len(od) else 0.0,
        yaw_rate_rms=float(np.mean(yrms)), roll_std_deg=float(np.mean(roll_s)), pitch_std_deg=float(np.mean(pitch_s)),
        lr_asym_deg=dict(zip(PAIR_NAMES, asym)), lr_asym_max_deg=float(np.max(np.abs(asym))),
        servo_over_frac=float(np.mean(over)),
        foot_clear_p90_mm=float(np.mean(clear)) if clear else 0.0,
        joint_mean_deg=[float(v) for v in jm],
        ep_fell=[bool(f) for f in falls], ep_speed=[round(float(v), 4) for v in speeds], ep_falls=ep_falls,      # per episode, for paired comparisons (same seeds for every policy)
    )


def turn_metrics(eps_list, cmd_yaw):
    """Measured mean yaw rate vs the commanded one (rad/s), averaged over episodes."""
    rates = [float(np.mean(rec["yaw_rate"])) for rec, *_ in eps_list]
    return dict(cmd_yaw=cmd_yaw, yaw_rate_mean=float(np.mean(rates)), yaw_rate_ratio=float(np.mean(rates)) / cmd_yaw if cmd_yaw else 0.0)



# ------------------------------------------------------------------------------------------------ difficulty-level ladder
LADDER_CATS = ("terrain", "ledge", "slope", "fault")        # opencat_gym_env.CATS
LADDER_LEVELS = (0.25, 0.5, 0.75, 1.0)
LADDER_HARD_LEVEL = 1.0                                     # the hard rung: this level with G2E_HARD_SCALE
LADDER_HARD_SCALE = 1.10                                    # g2_profile.FINAL_EXTRA
LADDER_UP = 0.80                                            # = LEVEL_UP_SCORE in g2_profile.RECIPE: a level counts as reached at a relative score >= this
LADDER_BASE_FLOOR = 0.30                                    # train.py Curriculum: rel = raw / max(base, 0.30)
LADDER_EPISODES = 20
LADDER_VERSION = 2          # 2: hazard forced present, forward commands, seeds honoured, fixed shove size (2026-10-08 review); 1 = everything scored before
LADDER_STAGE = "fresh final: s0_flat + FULL_COURSE"          # the world the next 20M trains in (2026-10-08 review: it was the old staged plan's s6_full_strength course, without the caps)


def ladder_env(world_levers=(), obs_levers=(), hard=False):
    """The G2E_* settings of the ladder's world: the base recipe + calibration + the kept levers' settings + the final stage's course (everything the training probe
    sees), with only the observation-changing levers a policy needs (heading_obs) set per policy. hard=True adds the final run's +10% hardest levels."""
    levers = [l for l in world_levers if l not in g2_profile.OBS_LEVERS]
    env = dict(g2_profile.env_for(*levers, stage="s0_flat", extra=dict(g2_profile.FULL_COURSE)))
    # training-only settings, and the caps (a lever such as `frontier` removes them, so leaving them would score policies on different courses): one fixed ladder for every policy
    for k in [k for k in env if k.startswith(("G2E_MIRROR", "G2E_RAMP", "G2E_CAP_") + g2_profile.TRAINER_ONLY_PREFIXES)]:
        del env[k]
    for name in obs_levers:
        if name in g2_profile.OBS_LEVERS:
            env.update(g2_profile.LEVERS[name])
    if hard:
        env.update(g2_profile.FINAL_EXTRA)
    return env


def ladder_cell_list(hard):
    """[(category or None, level)]: the clean floor, then each category at each level (the hard group: only the top level)."""
    cells = [(None, 0.0)]
    cells += [(c, LADDER_HARD_LEVEL if hard else l) for c in LADDER_CATS for l in ((LADDER_HARD_LEVEL,) if hard else LADDER_LEVELS)]
    return cells


def _ladder_worker(job):
    """Score ladder cells in a fresh process, the way train.py's Curriculum probes: deterministic policy, the env's own random commands, CATEGORY_OVERRIDE pinning one
    category at a level (the others 0), generic randomization at full strength. job = dict(policy, env, cells=[(cat, level)], episodes, seed, hard)."""
    for k in [k for k in os.environ if k.startswith("G2E_")]:
        del os.environ[k]
    os.environ.update({k: str(v) for k, v in job["env"].items()})
    import opencat_gym_env as E
    E.GUI_MODE = False
    import pybullet as pb
    from benchmark_gaits import ScriptedGait, _load_learned
    env = E.OpenCatGymEnv()
    env.set_ramp_steps(1e12)
    if job["policy"] == "scripted":
        E.CMD_SEND_EVERY_N = 1
        model = ScriptedGait(env)
    else:
        model = _load_learned(job["policy"])
    out = []
    for cat, level in job["cells"]:
        E.CATEGORY_OVERRIDE = {cat: float(level)} if cat else {"terrain": 0.0}
        E.CATEGORY_FORCE = bool(cat)          # LADDER_VERSION 2 (2026-10-08 review): like the curriculum probe, the hazard is in every episode, the walk is forward,
        t0 = time.time()                      # episode k has the same seed and command for every level and policy, and the shove size is fixed (it used to adapt to the policy's falls)
        scores, falls, speeds = [], [], []
        for k in range(job["episodes"]):
            if hasattr(model, "reset"):
                model.reset()
            env.set_command(fwd=E.probe_command(job["seed"] + k), yaw=0.0)
            env._push_curr, env._ep_outcomes = 1.0, []
            obs, _ = env.reset(seed=job["seed"] + k)
            x0 = pb.getBasePositionAndOrientation(env.robot_id)[0][0]
            peak, steps = 0.0, 0
            while True:
                act, _ = model.predict(obs, deterministic=True)
                obs, _r, te, tr, _i = env.step(act)
                steps += 1
                rr, pp, _y = pb.getEulerFromQuaternion(pb.getBasePositionAndOrientation(env.robot_id)[1])
                peak = max(peak, abs(rr), abs(pp))
                if te or tr:
                    break
            fell = peak > 1.3
            scores.append(0.0 if fell else env._episode_score())
            falls.append(fell)
            speeds.append((pb.getBasePositionAndOrientation(env.robot_id)[0][0] - x0) / (steps / STEPS_HZ))
        E.CATEGORY_OVERRIDE = {}
        E.CATEGORY_FORCE = False
        env._forced_cmd = None
        out.append(dict(category=cat, level=level, ladder_version=LADDER_VERSION, hard=bool(job["hard"]), episodes=job["episodes"], score=float(np.mean(scores)),
                        fell_fraction=float(np.mean(falls)), speed_mps=float(np.mean(speeds)), seconds=round(time.time() - t0, 1)))
        print(f"  [{os.getpid()}] ladder {cat or 'clean'} {level:.2f}{' hard' if job['hard'] else ''}: score {np.mean(scores):.2f}  fell {np.mean(falls):.0%}", flush=True)
    return out


def ladder_summary(cells):
    """Per category: the relative score at each level and the competence (the highest level reached contiguously from 0.25 with relative score >= LADDER_UP), the way the
    training curriculum judges a category; plus the hard rung. cells = res["ladder"]["cells"]."""
    base = {h: next((c["score"] for c in cells if c["category"] is None and c["hard"] == h), None) for h in (False, True)}
    base_n = base[False]
    cats = {}
    for cat in LADDER_CATS:
        rows = sorted([c for c in cells if c["category"] == cat and not c["hard"]], key=lambda c: c["level"])
        rel = {c["level"]: min(1.0, c["score"] / max(base_n or 0.0, LADDER_BASE_FLOOR)) for c in rows}
        comp = 0.0
        for c in rows:
            if rel[c["level"]] >= LADDER_UP:
                comp = c["level"]
            else:
                break
        hard = next((c for c in cells if c["category"] == cat and c["hard"]), None)
        cats[cat] = dict(competence=comp, rel=rel, fell={c["level"]: c["fell_fraction"] for c in rows}, score={c["level"]: c["score"] for c in rows},
                         hard_rel=(min(1.0, hard["score"] / max(base[True] if base[True] is not None else (base_n or 0.0), LADDER_BASE_FLOOR)) if hard else None),
                         hard_fell=(hard["fell_fraction"] if hard else None))
    return dict(clean_score=base_n, clean_score_hard=base[True], up=LADDER_UP, categories=cats,
                mean_competence=float(np.mean([v["competence"] for v in cats.values()])))


def _dispatch(job):
    return ("ladder", _ladder_worker(job)) if job.get("ladder") else ("cells", _worker(job))

# ------------------------------------------------------------------------------------------------ worker
def _worker(job):
    """Score a list of cells in a fresh process (spawn): own env, own policy copy. job = dict(policy, cells, episodes, seed, hard_scale)."""
    import evaluate_policy
    evaluate_policy.EPISODE_CAP = 10 ** 9                       # run_episode's "fell = terminated and steps < 250" must not hide long-cell falls
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import ScriptedGait, _load_learned
    from opencat_gym_env import OpenCatGymEnv

    E.ADAPTIVE_PUSH = False
    defaults = {k: getattr(E, k) for k in NEW_KNOBS if hasattr(E, k)}
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    if job["policy"] == "scripted":
        E.CMD_SEND_EVERY_N = 1                                  # the open-loop wkF run sends a command every tick
        model = ScriptedGait(env)
    else:
        model = _load_learned(job["policy"])
    rows = {r[0]: r for r in cell_table(job["hard_scale"])}
    out = []
    for cid in job["cells"]:
        _, label, knobs, eps, steps, cmd, tag = rows[cid]
        for k, v in defaults.items():
            setattr(E, k, v)
        B._apply({k: v for k, v in knobs.items()})
        E.EPISODE_LENGTH = steps or defaults.get("EPISODE_LENGTH", 250)
        env.set_command(fwd=(cmd[0] if cmd else 0.10), yaw=(cmd[1] if cmd else 0.0))
        n = n_episodes(eps, job["episodes"])
        t0 = time.time()
        eps_list = _episodes(env, model, n, job["seed"], evaluate_policy.run_episode)
        m = v4_metrics(eps_list)
        if cmd:
            m["turn"] = turn_metrics(eps_list, cmd[1])
        out.append(dict(id=cid, label=label, tag=tag, knobs={k: (list(v) if isinstance(v, tuple) else v) for k, v in knobs.items()},
                        episodes=n, steps=steps or 250, seconds=round(time.time() - t0, 1), **m))
        print(f"  [{os.getpid()}] {cid}: fell {m['fell_fraction']:.0%}  speed {m['speed_mps']:.3f}  heading {m['heading_mean_deg']:+.0f} deg  "
              f"({time.time() - t0:.0f} s)", flush=True)
    mg = None
    if job["policy"] != "scripted" and job.get("mirror_gap"):
        mg = _mirror_gap(env, model, E)
    return out, mg


def _episodes(env, model, n, seed0, run_episode):
    """The raw per-episode records (benchmark_gaits._bench keeps only summaries). Episode e uses seed seed0 + e, the same course for every policy."""
    env._reflex_on = False
    out = []
    for e in range(n):
        np.random.seed(seed0 + e)
        if hasattr(model, "reset"):
            model.reset()
        out.append(run_episode(env, model))
    return out


def _mirror_gap(env, model, E):
    """RMS mirror asymmetry of the policy (action units) over observations from calm walking (mirror.mirror_gap)."""
    import mirror
    B_ok = True
    try:
        import benchmark_decathlon as B
        B._apply({})
        E.EPISODE_LENGTH = 400
        env.set_command(fwd=0.10, yaw=0.0)
        obs_list = []
        for ep in range(4):
            obs, _ = env.reset(seed=900 + ep)
            for _ in range(400):
                obs_list.append(obs)
                act, _ = model.predict(obs, deterministic=True)
                obs, _r, te, tr, _i = env.step(act)
                if te or tr:
                    break
        return mirror.mirror_gap(model, np.array(obs_list))
    except Exception as e:  # noqa: BLE001 - e.g. a heading-less obs size the mirror module does not know
        print(f"  mirror gap not computed: {e}", flush=True)
        return None


# ------------------------------------------------------------------------------------------------ driver
def run(policy, spec="all", episodes=40, seed=1000, jobs=1, hard_scale=None, levers=(), json_out=None, mirror_gap=True, quiet=False,
        extra_env=None, ladder=False, ladder_levers=(), ladder_episodes=LADDER_EPISODES):
    """Score `policy` on the selected cells; returns the result dict (and writes it if json_out). Safe to call from another script."""
    g2_profile.set_environ({**g2_profile.scoring_env(*levers), **(extra_env or {})})        # extra_env: a calibration sweep's overrides
    rows = [] if spec in ("ladder", "none") else select(cell_table(hard_scale), spec, hard_scale)
    if not rows and not (ladder or spec == "ladder"):
        raise SystemExit(f"no cells match {spec!r}")
    ladder = ladder or spec == "ladder"
    rows.sort(key=lambda r: -cost(r, episodes))
    n_ladder = (2 if jobs >= 3 else 1) if ladder else 0           # worker processes reserved for the ladder
    buckets = [[] for _ in range(max(1, min(max(1, jobs - n_ladder), len(rows)))) ] if rows else []
    load = [0] * len(buckets)
    for r in rows:                                              # greedy: biggest cell to the emptiest worker
        i = load.index(min(load))
        buckets[i].append(r[0])
        load[i] += cost(r, episodes)
    t0 = time.time()
    if not quiet:
        print(f"benchmark v4: {len(rows)} cells, {episodes} eps default, {len(buckets)} worker(s), policy {policy}", flush=True)
    jobs_list = [dict(policy=policy, cells=b, episodes=episodes, seed=seed, hard_scale=hard_scale, mirror_gap=(i == 0 and mirror_gap))
                 for i, b in enumerate(buckets)]
    if ladder:                                      # the clean floor + 4 categories x 4 levels, and the hard rung group, split over the reserved workers
        lad = [(False, c) for c in ladder_cell_list(False)] + [(True, c) for c in ladder_cell_list(True)]
        groups = [[] for _ in range(max(1, n_ladder))]
        for i, item in enumerate(lad):
            groups[i % len(groups)].append(item)
        for g in groups:
            for hard in (False, True):
                cells_g = [c for h, c in g if h == hard]
                if cells_g:
                    jobs_list.append(dict(ladder=True, policy=policy, hard=hard, cells=cells_g, episodes=ladder_episodes, seed=seed,
                                          env={**ladder_env(ladder_levers, levers, hard), **(extra_env or {})}))
    if len(jobs_list) == 1:
        results = [_dispatch(jobs_list[0])]
    else:
        with mp.get_context("spawn").Pool(len(jobs_list)) as pool:
            results = pool.map(_dispatch, jobs_list)
    cells, gap, lad_cells = [], None, []
    for kind, payload in results:
        if kind == "ladder":
            lad_cells += payload
            continue
        out, mg = payload
        cells += out
        gap = mg if mg is not None else gap
    order = {r[0]: i for i, r in enumerate(cell_table(hard_scale))}
    cells.sort(key=lambda c: order[c["id"]])
    res = dict(bench_version=BENCH_VERSION, policy=policy, episodes=episodes, seed=seed, hard_scale=hard_scale, levers=list(levers),
               profile={**g2_profile.scoring_env(*levers), **(extra_env or {})}, mirror_gap=gap, wall_seconds=round(time.time() - t0, 1), cells=cells)
    if ladder:
        lad_cells.sort(key=lambda c: (c["hard"], c["category"] or "", c["level"]))
        res["ladder"] = dict(world_levers=list(ladder_levers), stage=LADDER_STAGE, episodes=ladder_episodes, levels=list(LADDER_LEVELS), hard_scale=LADDER_HARD_SCALE,
                             cells=lad_cells, summary=ladder_summary(lad_cells))
    if json_out:
        os.makedirs(os.path.dirname(os.path.abspath(json_out)), exist_ok=True)
        json.dump(res, open(json_out, "w"), indent=1)
    if not quiet:
        print(f"done in {res['wall_seconds']:.0f} s" + (f"; mirror gap {gap:.4f}" if gap is not None else ""), flush=True)
    return res


def by_id(res):
    return {c["id"]: c for c in res["cells"]}


def table(res, ref=None):
    """A printable comparison of one result (and an optional reference result). speed / decay are progress along the START direction (a walk that curves away loses them);
    path / pdecay are distance walked along the path (scored results from before 2026-10-09 have no path columns: nan)."""
    rc = by_id(ref) if ref else {}
    lines = [f"{'cell':8s} {'fell':>6s} {'speed':>7s} {'path':>6s} {'decay':>6s} {'pdecay':>6s} {'head':>7s} {'roll':>5s} {'asym':>5s} {'over':>5s}   " + ("| reference fell / head" if ref else "")]
    for c in res["cells"]:
        r = rc.get(c["id"])
        lines.append(f"{c['id']:8s} {c['fell_fraction']:6.0%} {c['speed_mps']:7.3f} {c.get('path_speed_mps', float('nan')):6.3f} {c['speed_decay']:6.2f} {c.get('path_decay', float('nan')):6.2f} {c['heading_mean_deg']:+7.1f} "
                     f"{c['roll_std_deg']:5.1f} {c['lr_asym_max_deg']:5.1f} {c['servo_over_frac']:5.2f}"
                     + (f"   | {r['fell_fraction']:.0%} / {r['heading_mean_deg']:+.1f}" if r else ""))
    return "\n".join(lines)


def ladder_table(sm):
    lines = [f"difficulty ladder (relative score; clean floor {sm['clean_score']:.2f}; '>' marks a level reached at >= {sm['up']:.2f}):",
             f"{'category':9s} " + " ".join(f"{l:>6.2f}" for l in LADDER_LEVELS) + f" {'hard':>6s}  competence"]
    for cat, v in sm["categories"].items():
        lines.append(f"{cat:9s} " + " ".join(f"{v['rel'].get(l, float('nan')):>6.2f}" for l in LADDER_LEVELS)
                     + f" {v['hard_rel'] if v['hard_rel'] is not None else float('nan'):>6.2f}  {v['competence']:.2f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", required=True, help="trained/<tag>_ppo (no .zip) or 'scripted'")
    ap.add_argument("--json-out", required=True)
    ap.add_argument("--cells", default="all")
    ap.add_argument("--episodes", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1000)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--hard-scale", type=float, default=None)
    ap.add_argument("--levers", default="", help="comma list of observation-changing levers the policy was trained with (heading_obs)")
    ap.add_argument("--env", action="append", default=[], metavar="G2E_KEY=VALUE",
                    help="override a profile setting for this run (repeatable), e.g. --env G2E_SERVO_RATE_LIMIT_DEG_S=0")
    ap.add_argument("--ladder", action="store_true", help="also score the difficulty-level ladder (training's levels per hazard category, v5)")
    ap.add_argument("--ladder-levers", default="", help="comma list of the levers the final recipe keeps (the ladder world's course settings)")
    ap.add_argument("--ladder-episodes", type=int, default=LADDER_EPISODES)
    ap.add_argument("--reference", default=None, help="a previous result JSON to print next to this one")
    a = ap.parse_args()
    res = run(a.policy, a.cells, a.episodes, a.seed, a.jobs, a.hard_scale, tuple(x for x in a.levers.split(",") if x), a.json_out,
              extra_env=dict(kv.split("=", 1) for kv in a.env), ladder=a.ladder, ladder_levers=tuple(x for x in a.ladder_levers.split(",") if x),
              ladder_episodes=a.ladder_episodes)
    if res["cells"]:
        print(table(res, json.load(open(a.reference)) if a.reference else None))
    if "ladder" in res:
        print(ladder_table(res["ladder"]["summary"]))


if __name__ == "__main__":
    main()
