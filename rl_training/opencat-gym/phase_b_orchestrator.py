"""Phase B: one training round per new-to-the-curriculum mechanic, unattended.

Each candidate below is OFF by default in opencat_gym_env.py's training
curriculum (confirmed 2026-09-23 -- see docs/rl/hw1-log.md) -- ledges, the two
transition variants, carpet, slide-rug, snag obstacles, and overheat-slope
correlation. Everything else in the ladder (box obstacles, rubble, rough
terrain, plain overheat cutback, targeted slopes) is already trained on by
default / via base1_20m's launch config, so it needs no Phase B round.

Same fresh-run discipline as limp_queue.py (retired, kept only as a record):
one training at a time, never a continuation, early-stop on a cheap check,
full averaged gate before a keep/drop call. Two-part gate per user rule
(2026-09-23): a mechanic must (1) show real improvement on its own skill AND
(2) leave T1.1 (flat, calm) clean -- a regression there disqualifies it
regardless of how well it does on its own cell.

Runs unattended through all candidates (no approval needed between rounds --
only the final 20M consolidation run needs that). Writes one JSON per round
to trained/phase_b_<tag>.json; each round's data should be reviewed and
logged to docs/rl/hw1-log.md as it completes, not silently auto-decided.

    python phase_b_orchestrator.py                  # run every candidate
    python phase_b_orchestrator.py --only b3_transition_step
    python phase_b_orchestrator.py --adopt b1_ledge  # b1_ledge already training: pick up from there
"""
import argparse
import glob
import json
import os
import subprocess
import time

import numpy as np

PY = "../../.venv/bin/python"

# Same launch config as base1_20m (docs/rl/hw1-log.md, Phase A baseline) --
# every Phase B candidate builds on this, plus exactly one new mechanic knob.
BASE = dict(G2E_IMU_HOLD_STEPS="16", G2E_IMU_RATE_ZERO="1", G2E_CMD_PATH="i",
            G2E_CMD_PATH_EXTRA_MS_MAX="4", G2E_BODY_MASS_SCALE="1.12",
            G2E_IMU_BIAS_DEG="2", G2E_JOINT_OFFSET_DEG="2", G2E_SLOPE_TARGET_PROB="0.3",
            G2E_CMD_SEND_EVERY_N="3",   # 2026-09-25: i@27, see run_pipeline.py's BASE comment -- kept
            # in sync here since this file has its own copy of BASE rather than importing it
            G2E_FAC_YAW_TRACK="9.0")   # 2026-09-25: 6.0 -> 9.0, see run_pipeline.py's BASE comment

# (tag, desc, extra G2E_ knobs, probe cell ids from the new 21-cell ladder)
# Training-time probabilities are deliberately lower than the benchmark's
# forced-every-episode eval values -- an occasional mechanic mixed into the
# curriculum, not one that dominates every episode.
CANDIDATES = [
    ("r2_b1_ledge", "ledges (re-test: prior 'made it worse' finding predates the payload-inertia fix)",
        dict(G2E_LEDGE_HEIGHT="0.030", G2E_LEDGE_PROB="0.20", G2E_LEDGE_RANDOMIZE="1"),
        ("T5.1", "T5.2", "T5.3")),
    ("r2_b2_transition", "surface transition, material only",
        dict(G2E_SURFACE_TRANSITION_PROB="0.25"),
        ("T4.1",)),
    ("r2_b3_transition_step", "surface transition + small step (12mm)",
        dict(G2E_SURFACE_TRANSITION_PROB="0.25", G2E_SURFACE_TRANSITION_STEP_M="0.012"),
        ("T4.1", "T4.2")),
    ("r2_b4_carpet", "house carpet (bump + mild grip)",
        dict(G2E_CARPET="0.013", G2E_CARPET_PROB="0.5", G2E_CARPET_SOFT="0.2"),
        ("T10.1",)),
    ("r2_b5_slide_rug", "slick tile / low-friction hard floor (2026-09-24: mechanically this is "
        "just reduced-friction flat ground, no rug-specific modeling -- tile/polished hardwood is "
        "the more accurate real-world analog than a sliding rug; variable names still say RUG_SLIDE_* "
        "pending a clean rename, see docs/rl/hw1-log.md)",
        dict(G2E_RUG_SLIDE_PROB="0.15"),
        ("T10.2",)),
    ("r2_b6_snag", "snag obstacles (thin, lane-spanning)",
        dict(G2E_SNAG_OBSTACLE_PROB="0.20"),
        ("T7.2",)),
    ("r2_b7_torque_slope", "overheat cutback correlated with slope",
        dict(G2E_TORQUE_SLOPE_CORRELATE="1"),
        ("T9.1",)),
]
FLAT_CELL = "T1.1"
EARLY_STEP = 2000000
GATE_STEP = 3000000
# 2026-09-24: was a 5-checkpoint average (2.2M-3.0M) / 3-checkpoint average
# (1.6M-2.0M). Dropped per user instruction after finding real cases in our
# own data where averaging hid a genuine trend AND got fooled by the tail
# checkpoint being a noise outlier (b1_ledge's T5.2: a clean improving trend
# 2.2M->2.8M, 43.8%->25.0% fell, then a jump to 50.0% at 3.0M -- averaging
# produced a number that represented neither the trend nor the final state
# cleanly). Single-checkpoint-at-the-end is simpler and answers the actual
# question ("where is this candidate at the end of its 3M budget"), at the
# cost of being more exposed to noise on any one candidate's number -- an
# accepted tradeoff, not an oversight.
FLAT_REGRESSION_FELL_MAX = 0.15   # T1.1 fell_fraction above this at the gate = disqualifying regression


def log(msg):
    print(f"[phaseB {time.strftime('%I:%M %p')}] {msg}", flush=True)


def training(tag):
    return subprocess.run(["pgrep", "-f", f"train.py --tag {tag}"], capture_output=True).returncode == 0


def any_training():
    return subprocess.run(["pgrep", "-f", "train.py --tag"], capture_output=True).returncode == 0


def ckpt(tag, step):
    return f"trained/checkpoints/{tag}_{step}_steps.zip"


def stop(tag):
    subprocess.run(["pkill", "-f", f"train.py --tag {tag}"])
    while training(tag):
        time.sleep(2)


def wait_for(tag, step):
    while not os.path.exists(ckpt(tag, step)):
        if not training(tag):
            return False
        time.sleep(20)
    time.sleep(15)          # let the checkpoint finish writing
    return True


def _clean_stale(tag):
    """Remove a tag's leftover files IF it never finished (no <tag>_ppo.zip) --
    e.g. checkpoints/console.log from a run that was killed mid-training for a
    methodology fix. start_run.sh's tag-collision guard would otherwise refuse
    to launch a fresh attempt under the same tag, and that refusal isn't a y/N
    prompt `yes y` can answer -- it's a hard failure that silently looked like
    "no result, skip" (2026-09-24: this ate r2_b1_ledge and r2_b2_transition's
    first attempts). Never touches a tag that actually completed."""
    if os.path.exists(f"trained/{tag}_ppo.zip"):
        return
    stale = glob.glob(f"trained/checkpoints/{tag}_*_steps.zip") + \
        [p for p in (f"trained/{tag}_console.log",) if os.path.exists(p)]
    if stale:
        log(f"{tag}: cleaning {len(stale)} stale file(s) from an incomplete previous attempt")
        for f in stale:
            os.remove(f)


def launch(tag, extra):
    if any_training():
        raise SystemExit("another training is running -- not starting a second one")
    _clean_stale(tag)
    # dict(os.environ, **BASE, **extra) raises TypeError if BASE and extra share a key --
    # a dict LITERAL with the same unpacking lets later keys win instead (2026-09-26,
    # same fix as run_pipeline.py's launch(), found there first).
    env = {**os.environ, **BASE, **extra}
    # start_run.sh can raise up to two separate y/N prompts (lingering GUI
    # viewer, then uncommitted changes) -- `yes y` answers as many as show up,
    # not just the first one (2026-09-24: a single `echo y` silently lost
    # b4_carpet when a g2watch-checkpoint viewer happened to be open).
    r = subprocess.run(f"yes y | ./start_run.sh {tag} --steps 20e6", shell=True, env=env,
                       capture_output=True, text=True)
    log(f"launched {tag}: {r.stdout.strip().splitlines()[0] if r.stdout.strip() else r.stderr.strip()[-200:]}")
    time.sleep(3)
    if not training(tag):
        raise SystemExit(f"{tag} failed to start -- check the output above / trained/{tag}_console.log")


def probe(tag, step, cells):
    """Score one checkpoint on the flat cell + this candidate's probe cells,
    learned gait only (no scripted -- candidates are compared to each other
    and to the flat baseline, not re-deriving the scripted numbers each time)."""
    import opencat_gym_env as E
    E.GUI_MODE = False
    import benchmark_decathlon as B
    from benchmark_gaits import _load_learned, _bench
    from opencat_gym_env import OpenCatGymEnv

    m = _load_learned(f"trained/checkpoints/{tag}_{step}_steps")
    env = OpenCatGymEnv()
    env.set_command(fwd=0.10, yaw=0.0)
    row = {"tag": tag, "step": step}
    cells_all = {c[0]: c for c in B.LADDER}
    for cid in (FLAT_CELL,) + tuple(c for c in cells if c != FLAT_CELL):
        knobs = {k: v for k, v in cells_all[cid][4].items() if not k.startswith("_")}
        B._apply(knobs)
        E.IMU_HOLD_STEPS, E.IMU_RATE_ZERO, E.CMD_PATH = 16, True, "i"
        E.CMD_SEND_EVERY_N = 3   # match BASE's G2E_CMD_SEND_EVERY_N -- eval must match training (2026-09-25 fix)
        E.EPISODE_LENGTH = 250
        s, _ = _bench(env, m, 16, 1000)
        row[cid] = dict(fell=round(s["fell_fraction"], 4), speed=round(s["forward_speed_mps_mean"], 4))
    env.close()
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt", default=None)
    ap.add_argument("--only", default=None, help="run just this one candidate tag")
    args = ap.parse_args()
    candidates = [c for c in CANDIDATES if c[0] == args.only] if args.only else CANDIDATES
    start = [c[0] for c in candidates].index(args.adopt) if args.adopt else 0

    # Merge into whatever's already on disk by tag, never blindly overwrite --
    # 2026-09-24: a bare `results = []` + full-list dump would wipe out every
    # other candidate's already-recorded result on a single-tag --only re-run.
    order = [c[0] for c in CANDIDATES]
    existing = {r["tag"]: r for r in json.load(open("trained/phase_b_summary.json"))} \
        if os.path.exists("trained/phase_b_summary.json") else {}

    def save(tag, row):
        existing[tag] = row
        ordered = [existing[t] for t in order if t in existing]
        json.dump(ordered, open("trained/phase_b_summary.json", "w"), indent=1)

    for tag, desc, extra, cells in candidates[start:]:
        log(f"--- {tag}: {desc}")
        if not training(tag):
            launch(tag, extra)
        if not wait_for(tag, EARLY_STEP):
            log(f"{tag} stopped before {EARLY_STEP} -- skipping")
            continue
        early_row = probe(tag, EARLY_STEP, cells)
        flat_fell = early_row[FLAT_CELL]["fell"]
        skill_fell = float(np.mean([early_row[c]["fell"] for c in cells]))
        log(f"{tag} early (at {EARLY_STEP}): T1.1 fell {flat_fell:.2f}, skill cells fell {skill_fell:.2f}")
        if flat_fell > FLAT_REGRESSION_FELL_MAX and skill_fell > 0.9:
            stop(tag)
            log(f"{tag} EARLY STOP: flat-ground regressed AND no learning signal on its own skill yet")
            save(tag, dict(tag=tag, desc=desc, stopped_early=True,
                            flat_fell=round(float(flat_fell), 3), skill_fell=round(float(skill_fell), 3)))
            continue
        if not wait_for(tag, GATE_STEP):
            log(f"{tag} stopped before {GATE_STEP} -- skipping")
            continue
        stop(tag)
        log(f"{tag} stopped at {GATE_STEP}; running the gate (single checkpoint, no averaging)")
        gate_row = probe(tag, GATE_STEP, cells)
        with open(f"trained/phase_b_{tag}.json", "w") as f:
            json.dump([gate_row], f, indent=1)
        flat_fell_g = float(gate_row[FLAT_CELL]["fell"])
        flat_speed_g = float(gate_row[FLAT_CELL]["speed"])
        skill_fell_g = float(np.mean([gate_row[c]["fell"] for c in cells]))
        res = dict(tag=tag, desc=desc, stopped_early=False,
                   flat_fell=round(flat_fell_g, 3), flat_speed=round(flat_speed_g, 3),
                   skill_fell=round(skill_fell_g, 3),
                   flat_clean=flat_fell_g <= FLAT_REGRESSION_FELL_MAX)
        save(tag, res)
        log(f"{tag} gate: {json.dumps(res)}  (full per-checkpoint data: trained/phase_b_{tag}.json)")
    log("Phase B queue finished, nothing training. Review trained/phase_b_summary.json "
        "and trained/phase_b_<tag>.json, then log findings to docs/rl/hw1-log.md.")


if __name__ == "__main__":
    main()
