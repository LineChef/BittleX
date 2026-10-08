"""A recorded training episode replays exactly: same terrain, same random shoves, same actions -> same length and final reward (run with the RL venv: pytest test_episode_replay.py)."""
import glob
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

RECORD = r'''
import os, sys
import g2_profile as G
G.set_environ(G.env_for("mirror", stage="s6_full_strength"))
os.environ["G2E_LEVEL_EXTERNAL"] = "1"
import numpy as np
import opencat_gym_env as E
from episode_recorder import RecordingWrapper
env = RecordingWrapper(E.OpenCatGymEnv(), directory=sys.argv[1], every=1, keep=10)
env.unwrapped.set_ramp_steps(3_000_000)
env.unwrapped.set_category_levels({"terrain": 0.8, "ledge": 0.8, "slope": 0.8, "fault": 0.8})
rng = np.random.RandomState(5)
for _ in range(3):
    env.reset()
    for _ in range(2000):
        out = env.step(rng.uniform(-0.3, 0.3, 8))
        if out[2] or out[3]:
            break
'''


def test_recorded_episodes_replay_with_a_matching_outcome(tmp_path):
    d = str(tmp_path / "eps")
    r = subprocess.run([PY, "-c", RECORD, d], cwd=HERE, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-800:]
    files = sorted(glob.glob(os.path.join(d, "ep_*.npz")))
    assert len(files) == 3
    w = subprocess.run([PY, "watch_training.py", d, "--headless"], cwd=HERE, capture_output=True, text=True, timeout=600)
    assert w.returncode == 0, w.stderr[-800:]
    assert w.stdout.count("REPLAY MATCHES the recording") == 3, w.stdout[-1500:]
