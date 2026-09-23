"""Build wkf_contact_ref.npy: where Petoi's scripted wkF walk has each paw down.

Plays the pure scripted walk (zero residual) in the sim on flat ground with the
payload, through the `i` command-timing model the policy trains under, and records, per stride-phase bucket, the probability that each paw
(FL, FR, BR, BL) touches the ground. opencat_gym_env's FAC_CONTACT_IMITATION
compares the learned gait's footfalls against it -- a per-paw target the gait
can't satisfy by moving a limp to a different leg (2026-09-23; every learned
gait so far keeps one paw off the ground most of the time).

    python reference_gait/build_contact_ref.py        (from rl_training/opencat-gym)
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
os.chdir(os.path.join(HERE, ".."))

import opencat_gym_env as E  # noqa: E402
E.GUI_MODE = False
E.DR_EVAL_FULL = True
import benchmark_decathlon as B  # noqa: E402

BUCKETS = 20


def main():
    B._apply({})
    E.ROUGH_TERRAIN, E.TORQUE_CUTBACK, E.ADAPTIVE_PUSH = 0.0, 0.0, False
    E.BODY_MASS_SCALE = 1.12
    # the training control path: joint targets go through the firmware `i` model,
    # which shifts footfalls later in the stride than instant targets would
    E.CMD_PATH = "i"
    E.EPISODE_LENGTH = 700
    env = E.OpenCatGymEnv()
    hits = np.zeros((BUCKETS, 4))
    count = np.zeros(BUCKETS)
    for s in range(6):
        np.random.seed(3000 + s)
        obs, _ = env.reset()
        env.set_command(fwd=0.10, yaw=0.0)
        for t in range(640):
            obs, _, _, _, info = env.step(np.zeros(8))
            if t < 80:
                continue
            # the same contact reading and phase the env's reward term uses
            b = int((info["phase_step0"] % E.TIME_PHASE_PERIOD) / E.TIME_PHASE_PERIOD * BUCKETS) % BUCKETS
            count[b] += 1
            hits[b] += np.asarray(info["paw_contact"], float)
    env.close()
    sched = hits / np.maximum(count, 1)[:, None]
    out = os.path.join(HERE, "wkf_contact_ref.npy")
    np.save(out, sched.astype(np.float32))
    print(f"wrote {out}  shape {sched.shape}")
    print("phase  FL   FR   BR   BL")
    for b in range(BUCKETS):
        print(f"{b / BUCKETS:4.2f}  " + "  ".join(f"{v:.2f}" for v in sched[b]))


if __name__ == "__main__":
    main()
