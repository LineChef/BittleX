"""Cumulative simulation training invested in the walking policy.

Sums the last logged global step of every PPO_* run under
trained/tensorboard_logs/ -- one dir per training session (dead-end experiments,
reverted branches, and bailed runs included; they were all training on this env).

Run it to refresh the number in README.md's "Walking policy" section:

    python training_steps.py
"""
import glob
import os
import sys

from tensorboard.backend.event_processing import event_accumulator

HERE = os.path.dirname(os.path.abspath(__file__))
LOGDIR = os.path.join(HERE, "trained", "tensorboard_logs")


def total_steps(logdir: str = LOGDIR):
    runs = sorted(glob.glob(os.path.join(logdir, "PPO_*")))
    total, counted, per_run = 0, 0, []
    for d in runs:
        try:
            ea = event_accumulator.EventAccumulator(d, size_guidance={"scalars": 0})
            ea.Reload()
            tags = ea.Tags()["scalars"]
            tag = next((t for t in ("time/total_timesteps", "rollout/ep_rew_mean")
                        if t in tags), None)
            if tag is None:
                continue
            steps = ea.Scalars(tag)[-1].step
            total += steps
            counted += 1
            per_run.append((os.path.basename(d), steps))
        except Exception:
            continue
    return total, counted, per_run


if __name__ == "__main__":
    total, n, per_run = total_steps()
    if "--per-run" in sys.argv:
        for name, s in per_run:
            print(f"  {name:12} {s:>13,}")
        print()
    print(f"{total:,} simulation steps across {n} training runs")
    print(f"(~{total/1e6:.0f}M steps)")
