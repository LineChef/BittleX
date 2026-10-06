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
BENCH_VERSION = 4
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
]
NEW_KNOBS = ("EPISODE_LENGTH", "FAULT_STUCK_PROB", "FAULT_STUCK_JOINT", "FAULT_STUCK_DEG", "FAULT_WEAK_PROB", "FAULT_OFFSET_PROB",
             "MOTOR_SCALE_ALL", "MOTOR_SCALE_RAND", "DRIFT_TORQUE", "DRIFT_PROB", "LONG_EP_PROB")

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
    heads, speeds, early, late, roll_s, pitch_s, jm, over, yrms, falls = [], [], [], [], [], [], [], [], [], []
    for rec, pt, steps, fell, _ in eps_list:
        x = np.array(rec["x"])
        yaw = np.unwrap(np.array(rec["yaw"]))
        heads.append(math.degrees(yaw[-1] - yaw[0]))
        speeds.append(float(x[-1]) / (steps / STEPS_HZ))
        n = max(8, min(250, steps // 3))
        early.append(float(x[n - 1] - x[0]) / ((n - 1) / STEPS_HZ))
        late.append(float(x[-1] - x[-n]) / ((n - 1) / STEPS_HZ))
        roll_s.append(float(np.degrees(np.std(rec["roll"]))))
        pitch_s.append(float(np.degrees(np.std(rec["pitch"]))))
        jm.append(np.degrees(np.mean(np.array(rec["joint"]), axis=0)))
        over.append(float(np.mean(pt.get("servo_over", [0.0]))))
        yrms.append(float(np.sqrt(np.mean(np.square(rec["yaw_rate"])))))
        tilt = np.maximum(np.abs(rec["roll"]), np.abs(rec["pitch"]))
        falls.append(bool(tilt.max() > 1.3))
    jm = np.mean(np.array(jm), axis=0)
    asym = [float(jm[a] - jm[b]) for a, b in JOINT_PAIRS]
    h = np.array(heads)
    e, l = float(np.mean(early)), float(np.mean(late))
    return dict(
        n=len(eps_list), fell_fraction=float(np.mean(falls)), speed_mps=float(np.mean(speeds)),
        speed_early_mps=e, speed_late_mps=l, speed_decay=(1.0 - l / e) if e > 1e-6 else 0.0,
        heading_mean_deg=float(h.mean()), heading_abs_mean_deg=float(np.abs(h).mean()), heading_std_deg=float(h.std()),
        yaw_rate_rms=float(np.mean(yrms)), roll_std_deg=float(np.mean(roll_s)), pitch_std_deg=float(np.mean(pitch_s)),
        lr_asym_deg=dict(zip(PAIR_NAMES, asym)), lr_asym_max_deg=float(np.max(np.abs(asym))),
        servo_over_frac=float(np.mean(over)),
        joint_mean_deg=[float(v) for v in jm],
    )


def turn_metrics(eps_list, cmd_yaw):
    """Measured mean yaw rate vs the commanded one (rad/s), averaged over episodes."""
    rates = [float(np.mean(rec["yaw_rate"])) for rec, *_ in eps_list]
    return dict(cmd_yaw=cmd_yaw, yaw_rate_mean=float(np.mean(rates)), yaw_rate_ratio=float(np.mean(rates)) / cmd_yaw if cmd_yaw else 0.0)


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
        extra_env=None):
    """Score `policy` on the selected cells; returns the result dict (and writes it if json_out). Safe to call from another script."""
    g2_profile.set_environ({**g2_profile.scoring_env(*levers), **(extra_env or {})})        # extra_env: a calibration sweep's overrides
    rows = select(cell_table(hard_scale), spec, hard_scale)
    if not rows:
        raise SystemExit(f"no cells match {spec!r}")
    rows.sort(key=lambda r: -cost(r, episodes))
    buckets = [[] for _ in range(max(1, min(jobs, len(rows))))]
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
    if len(jobs_list) == 1:
        results = [_worker(jobs_list[0])]
    else:
        with mp.get_context("spawn").Pool(len(jobs_list)) as pool:
            results = pool.map(_worker, jobs_list)
    cells, gap = [], None
    for out, mg in results:
        cells += out
        gap = mg if mg is not None else gap
    order = {r[0]: i for i, r in enumerate(cell_table(hard_scale))}
    cells.sort(key=lambda c: order[c["id"]])
    res = dict(bench_version=BENCH_VERSION, policy=policy, episodes=episodes, seed=seed, hard_scale=hard_scale, levers=list(levers),
               profile={**g2_profile.scoring_env(*levers), **(extra_env or {})}, mirror_gap=gap, wall_seconds=round(time.time() - t0, 1), cells=cells)
    if json_out:
        os.makedirs(os.path.dirname(os.path.abspath(json_out)), exist_ok=True)
        json.dump(res, open(json_out, "w"), indent=1)
    if not quiet:
        print(f"done in {res['wall_seconds']:.0f} s" + (f"; mirror gap {gap:.4f}" if gap is not None else ""), flush=True)
    return res


def by_id(res):
    return {c["id"]: c for c in res["cells"]}


def table(res, ref=None):
    """A printable comparison of one result (and an optional reference result)."""
    rc = by_id(ref) if ref else {}
    lines = [f"{'cell':8s} {'fell':>6s} {'speed':>7s} {'decay':>6s} {'head':>7s} {'roll':>5s} {'asym':>5s} {'over':>5s}   " + ("| reference fell / head" if ref else "")]
    for c in res["cells"]:
        r = rc.get(c["id"])
        lines.append(f"{c['id']:8s} {c['fell_fraction']:6.0%} {c['speed_mps']:7.3f} {c['speed_decay']:6.2f} {c['heading_mean_deg']:+7.1f} "
                     f"{c['roll_std_deg']:5.1f} {c['lr_asym_max_deg']:5.1f} {c['servo_over_frac']:5.2f}"
                     + (f"   | {r['fell_fraction']:.0%} / {r['heading_mean_deg']:+.1f}" if r else ""))
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
    ap.add_argument("--reference", default=None, help="a previous result JSON to print next to this one")
    a = ap.parse_args()
    res = run(a.policy, a.cells, a.episodes, a.seed, a.jobs, a.hard_scale, tuple(x for x in a.levers.split(",") if x), a.json_out,
              extra_env=dict(kv.split("=", 1) for kv in a.env))
    print(table(res, json.load(open(a.reference)) if a.reference else None))


if __name__ == "__main__":
    main()
