"""The two floor slabs of a surface-transition episode stay on one plane when the ground is tilted (found 2026-10-08: they used to be rotated about their own centres, so any
tilt left a wall at the junction, 11 cm at 3 deg and 29 cm at 8 deg). Run with the RL venv: pytest test_surface_transition_junction.py."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PROBE = r'''
import os, sys
sys.path.insert(0, ".")
import g2_profile as G
G.set_environ(G.env_for("mirror", stage="s6_full_strength"))
os.environ["G2E_SURFACE_TRANSITION_PROB"] = "1.0"
os.environ["G2E_SLOPE_TARGET_PROB"] = "0"
os.environ["G2E_SLOPE_MAX_DEG"] = "0"
os.environ["G2E_SURFACE_TRANSITION_STEP_M"] = "0.0"
for k in ("G2E_ROUGH_TERRAIN_PROB", "G2E_RUBBLE_PROB", "G2E_SNAG_OBSTACLE_PROB", "G2E_LEDGE_PROB", "G2E_RANDOM_TERRAIN"):
    os.environ[k] = "0"                      # only the two slabs: a random rough floor or an obstacle at the junction is not a seam
import numpy as np, pybullet as p
import opencat_gym_env as E
def top(x, y=0.0):
    r = p.rayTest([x, y, 1.0], [x, y, -1.0])[0]
    return None if r[0] < 0 else 1.0 - 2.0 * r[2]
worst = 0.0
for roll, pitch in ((0, 0), (0, 3), (0, 8), (0, -12), (0, 24), (6, 0), (10, 5)):
    E.SLOPE_FIXED_RP = (np.deg2rad(roll), np.deg2rad(pitch))
    np.random.seed(3)
    env = E.OpenCatGymEnv(); env.reset()
    tx = E.SURFACE_TRANSITION_X
    for y in (-0.2, 0.0, 0.2):
        a, b = top(tx - 0.02, y), top(tx + 0.02, y)
        if a is not None and b is not None:
            worst = max(worst, abs(b - a))
    env.close()
print("WORST_STEP", round(worst, 4))
'''


def test_junction_has_no_wall_at_any_tilt():
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=HERE, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-800:]
    worst = float([l for l in r.stdout.splitlines() if l.startswith("WORST_STEP")][-1].split()[1])
    assert worst < 0.02, f"a {worst * 100:.1f} cm step at the junction"      # 12 mm of real step is added elsewhere; the slab seam itself must be flush (a tilt adds a few mm over the 4 cm sampling gap)
