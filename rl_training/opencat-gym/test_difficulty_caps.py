"""The top-threshold caps (user rule, 2026-10-08): with caps set, no training episode exceeds them at any level; with none set, nothing changes. Run with the RL venv."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = r"""
import os, sys
sys.path.insert(0, ".")
import g2_profile
g2_profile.set_environ(g2_profile.env_for("mirror", stage="s6_full_strength"))
os.environ.update({"G2E_SCALE_ALL_HAZARDS": "1", "G2E_ADAPTIVE_LEVEL": "1", "G2E_CATEGORY_LEVELS": "1", "G2E_LEVEL_START": "0", "G2E_LEDGE_PROB": "1.0", "G2E_SLOPE_TARGET_PROB": "0.6"})
os.environ.update(CAPS)
import numpy as np
import opencat_gym_env as E
E.GUI_MODE = False
E.CATEGORY_OVERRIDE = {"slope": 1.25, "ledge": 1.25, "terrain": 0.0}
e = E.OpenCatGymEnv(); e.set_ramp_steps(5e6)
roll = up = down = ledge = 0.0
for k in range(80):
    np.random.seed(k); e.reset(seed=k)
    r, pt = e._slope_rp
    roll = max(roll, abs(np.degrees(r))); up = max(up, -np.degrees(pt)); down = max(down, np.degrees(pt)); ledge = max(ledge, e._ledge_h + 0.11 * max(0.0, np.tan(pt)))
print("MAX", round(roll, 2), round(up, 2), round(down, 2), round(ledge, 4))
"""


def run(caps):
    r = subprocess.run([sys.executable, "-c", "CAPS = %r\n" % caps + PROBE], cwd=HERE, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-600:]
    return [float(x) for x in [l for l in r.stdout.splitlines() if l.startswith("MAX")][-1].split()[1:]]


def test_caps_hold_at_the_top_level_and_off_means_unchanged():
    roll, up, down, ledge = run({})
    assert up > 24 or roll > 15 or ledge > 0.04                         # uncapped, the top level really does exceed these
    roll, up, down, ledge = run({"G2E_CAP_SIDEHILL_DEG": "9", "G2E_CAP_UPHILL_DEG": "14", "G2E_CAP_DOWNHILL_DEG": "12", "G2E_CAP_LEDGE_M": "0.03"})
    assert roll <= 9.01 and up <= 14.01 and down <= 12.01 and ledge <= 0.0301, (roll, up, down, ledge)
