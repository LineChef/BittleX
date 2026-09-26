"""Post-run report for the Phase C consolidated policy (2026-09-24): learned vs
scripted, broken out by each mechanic actually trained on, with one GIF per
category showing the learned policy succeeding at it.

Reuses benchmark_gaits.py's learned-vs-scripted _bench()/_render() machinery
and benchmark_decathlon.py's LADDER cell knobs -- this is not a new benchmark,
just the existing one sliced by category and rendered.

    python phase_c_report.py --tag Deployment_CandidateV1   # after the 20M finish + rename
    python phase_c_report.py --tag r2_consolidated --step 10000000   # dry run on a checkpoint
"""
import argparse
import json
import os

import numpy as np

SECTIONS = [
    ("Flat Ground", "flat_ground", ["T1.1"]),
    ("Surface Transitions", "transitions", ["T4.1", "T4.2"]),
    ("Ledges", "ledges", ["T5.1", "T5.2", "T5.3"]),
    ("Snag Obstacles", "snag", ["T7.2"]),
    ("Carpet", "carpet", ["T10.1"]),
]
EPISODES = 20
SEED0 = 1000
GIF_DIR_TEMPLATE = "trained/report_gifs_{tag}"   # per-tag -- a shared fixed dir would let a
    # later report silently overwrite an earlier candidate's GIFs on disk (2026-09-25, caught
    # before it could clobber Deployment_CandidateV1's files with V2's)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="policy tag, e.g. Deployment_CandidateV1 or r2_consolidated")
    ap.add_argument("--step", type=int, default=None,
                    help="load trained/checkpoints/<tag>_<step>_steps instead of trained/<tag>_ppo")
    ap.add_argument("--episodes", type=int, default=EPISODES)
    ap.add_argument("--out", default="trained/phase_c_report.json")
    ap.add_argument("--skip-sections", default="",
                    help="comma-separated section slugs to exclude, e.g. 'carpet' if a mechanic "
                         "was dropped from training and testing it would misrepresent the policy")
    args = ap.parse_args()
    skip = {s.strip() for s in args.skip_sections.split(",") if s.strip()}
    sections = [s for s in SECTIONS if s[1] not in skip]
    if skip:
        print(f"skipping section(s): {skip}")

    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench, ScriptedGait, _render
    from opencat_gym_env import OpenCatGymEnv
    from evaluate_policy import run_episode

    path = f"trained/checkpoints/{args.tag}_{args.step}_steps" if args.step else f"trained/{args.tag}_ppo"
    print(f"loading {path}")
    learned = _load_learned(path)

    gif_dir = GIF_DIR_TEMPLATE.format(tag=args.tag)
    os.makedirs(gif_dir, exist_ok=True)
    cells_all = {c[0]: c for c in B.LADDER}
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    scripted = ScriptedGait(env)

    report = {"tag": args.tag, "step": args.step, "skipped_sections": sorted(skip), "sections": []}
    for name, slug, cell_ids in sections:
        cell_rows = []
        for cid in cell_ids:
            knobs = {k: v for k, v in cells_all[cid][4].items() if not k.startswith("_")}
            desc = cells_all[cid][3]
            B._apply(knobs)
            E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
            E.CMD_SEND_EVERY_N = 3   # match BASE's G2E_CMD_SEND_EVERY_N -- eval must match training (2026-09-25 fix)
            E.EPISODE_LENGTH = 250
            rl, _ = _bench(env, learned, args.episodes, SEED0)
            sc, _ = _bench(env, scripted, args.episodes, SEED0)
            cell_rows.append(dict(cell=cid, desc=desc,
                                  learned_fell=rl["fell_fraction"], learned_speed=rl["forward_speed_mps_mean"],
                                  scripted_fell=sc["fell_fraction"], scripted_speed=sc["forward_speed_mps_mean"],
                                  learned_yaw_rate_rms_deg=rl["yaw_rate_rms_deg_mean"],
                                  scripted_yaw_rate_rms_deg=sc["yaw_rate_rms_deg_mean"],
                                  learned_heading_drift_deg=rl["heading_drift_deg_mean"],
                                  scripted_heading_drift_deg=sc["heading_drift_deg_mean"]))
            print(f"  {cid} ({desc}): learned fell {rl['fell_fraction']:.2f} speed {rl['forward_speed_mps_mean']:.3f} "
                  f"yaw_rms {rl['yaw_rate_rms_deg_mean']:.2f} | scripted fell {sc['fell_fraction']:.2f} "
                  f"speed {sc['forward_speed_mps_mean']:.3f} yaw_rms {sc['yaw_rate_rms_deg_mean']:.2f}")

        # representative GIF: first cell in the section, first seed (of up to 10)
        # where the learned policy doesn't fall -- "successfully demonstrating"
        knobs = {k: v for k, v in cells_all[cell_ids[0]][4].items() if not k.startswith("_")}
        B._apply(knobs)
        E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
        E.CMD_SEND_EVERY_N = 3   # match BASE's G2E_CMD_SEND_EVERY_N -- eval must match training (2026-09-25 fix)
        E.EPISODE_LENGTH = 250
        gif_path = f"{gif_dir}/{slug}.gif"
        gif_seed = None
        for seed in range(SEED0, SEED0 + 10):
            np.random.seed(seed)
            if hasattr(learned, "reset"):
                learned.reset()
            _, _, _, fell, _ = run_episode(env, learned)
            if not fell:
                gif_seed = seed
                break
        if gif_seed is None:
            print(f"  WARNING: no clean (non-fall) episode found in 10 seeds for {slug} -- "
                  f"rendering seed {SEED0} anyway (may show a fall)")
            gif_seed = SEED0
        _render(env, learned, gif_path, seed=gif_seed)

        learned_fell = float(np.mean([r["learned_fell"] for r in cell_rows]))
        learned_speed = float(np.mean([r["learned_speed"] for r in cell_rows]))
        scripted_fell = float(np.mean([r["scripted_fell"] for r in cell_rows]))
        scripted_speed = float(np.mean([r["scripted_speed"] for r in cell_rows]))
        learned_yaw_rate_rms = float(np.mean([r["learned_yaw_rate_rms_deg"] for r in cell_rows]))
        scripted_yaw_rate_rms = float(np.mean([r["scripted_yaw_rate_rms_deg"] for r in cell_rows]))
        report["sections"].append(dict(
            name=name, slug=slug, cells=cell_rows, gif=gif_path, gif_seed=gif_seed,
            learned_fell=learned_fell, learned_speed=learned_speed,
            scripted_fell=scripted_fell, scripted_speed=scripted_speed,
            learned_yaw_rate_rms_deg=learned_yaw_rate_rms,
            scripted_yaw_rate_rms_deg=scripted_yaw_rate_rms,
        ))
    env.close()

    with open(args.out, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
