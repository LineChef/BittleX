"""Parametrised vision-in-the-loop smoke.

Trains short PPO runs with the forward terrain feature (opencat_gym_env
TERRAIN_FEATURE) ON vs OFF across a few obstacle-course variants, so the *lift*
from vision can be compared per course -- which course does perception-in-the-
loop actually matter for. Wraps train.py with G2E_* env overrides (read by
opencat_gym_env._g2e); checkpoints land at trained/vis_<course>_<on|off>_ppo.zip
and TensorBoard logs under trained/tensorboard_logs/ as usual.

  python train_vision_smoke.py --course A --vision on  --steps 3e6
  python train_vision_smoke.py --all --steps 3e6     # 3 courses x on/off, sequential (~2.5 h)

Courses:
  A  obstacle-dense   -- sharp boxes back, ~35% tall (go-around) + ~18% lane-
                         spanning (unavoidable), ledges on, rubble low. Vision
                         should help most here.
  B  rubble (control) -- the built "new course": rounded rubble most episodes,
                         wide slopes, few sharp boxes. Vision has little to sense.
  C  hybrid           -- moderate everything.
"""
import argparse
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(HERE, "..", "..", ".venv", "bin", "python")

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


def run(course, vision, steps, obs_reward=False, from_ckpt=None, tag=None):
    tag = tag or f"vis_{course}_{vision}"
    env = dict(os.environ)
    for k, v in COURSES[course].items():
        env["G2E_" + k] = v
    env["G2E_TERRAIN_FEATURE"] = "1" if vision == "on" else "0"
    if obs_reward:
        env["G2E_OBSTACLE_REWARD"] = "1"
    shown = "  ".join(f"{k}={v}" for k, v in sorted(env.items()) if k.startswith("G2E_"))
    cmd = [PY, os.path.join(HERE, "train.py"), "--tag", tag, "--steps", str(steps)]
    if from_ckpt:
        cmd += ["--from", from_ckpt]
    print(f"\n=== {tag}   steps={steps}   from={from_ckpt or 'scratch'} ===\n  {shown}\n", flush=True)
    subprocess.run(cmd, cwd=HERE, env=env, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--course", choices=list(COURSES))
    ap.add_argument("--vision", choices=["on", "off"])
    ap.add_argument("--steps", type=float, default=3e6)
    ap.add_argument("--all", action="store_true", help="all 3 courses x on/off, sequential")
    ap.add_argument("--obs-reward", action="store_true", help="enable G2E_OBSTACLE_REWARD (gated obstacle-response terms)")
    ap.add_argument("--from", dest="from_ckpt", default=None, help="finetune from this checkpoint (e.g. the grafted 282-d policy)")
    ap.add_argument("--tag", default=None, help="override the auto tag")
    a = ap.parse_args()
    steps = int(a.steps)
    if a.all:
        for c in ("A", "B", "C"):
            for v in ("off", "on"):
                run(c, v, steps)
    elif a.course and a.vision:
        run(a.course, a.vision, steps, obs_reward=a.obs_reward,
            from_ckpt=a.from_ckpt, tag=a.tag)
    else:
        ap.error("give --course and --vision, or --all")


if __name__ == "__main__":
    main()
