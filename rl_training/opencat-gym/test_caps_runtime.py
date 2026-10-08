"""Caps move while a run trains, and the report tells too-low from too-high from on-track. Run with the RL venv (pytest test_caps_runtime.py)."""
import os
import subprocess
import sys

import caps_report as C

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = r"""
import os, sys
sys.path.insert(0, ".")
import g2_profile
g2_profile.set_environ(g2_profile.env_for_job({"kind": "final", "tag": "v3_next", "stage": "s6_full_strength", "levers": ["mirror"], "fresh": True}))
os.environ.update({"G2E_SCALE_ALL_HAZARDS": "1", "G2E_LEDGE_PROB": "1.0", "G2E_SLOPE_TARGET_PROB": "0.8"})
import numpy as np
import opencat_gym_env as E
E.GUI_MODE = False
E.CATEGORY_OVERRIDE = {"slope": 1.25, "ledge": 1.25}
e = E.OpenCatGymEnv(); e.set_ramp_steps(5e6)
def worst(n=60):
    up = ledge = 0.0
    for k in range(n):
        np.random.seed(k); e.reset(seed=k)
        up = max(up, -np.degrees(e._slope_rp[1])); ledge = max(ledge, e._ledge_h)
    return up, ledge
before = worst()
e.set_caps({"uphill_deg": 6.0, "ledge_m": 0.01})
after = worst()
e.set_caps({"uphill_deg": 0, "ledge_m": 0})
off = worst()
print("RES", round(before[0], 1), round(before[1], 3), round(after[0], 1), round(after[1], 3), round(off[0], 1), round(off[1], 3))
"""


def test_set_caps_changes_the_next_episodes_without_a_restart():
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=HERE, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-600:]
    b_up, b_led, a_up, a_led, o_up, o_led = [float(x) for x in [l for l in r.stdout.splitlines() if l.startswith("RES")][-1].split()[1:]]
    assert b_up <= 10.01 and b_led <= 0.0201                    # the launch caps (10 deg climb, 2 cm ledge) hold
    assert a_up <= 6.01 and a_led <= 0.0101                     # lowered while running
    assert o_up > 10.5 and o_led > 0.0201                       # removed: the course's own size returns


def _log(scores, level, start=98304):
    lines = []
    for i, s in enumerate(scores):
        lines.append(f"[probe] steps {start + i * 98304}  clean-floor score 0.88 (cap 1.00); relative score by category (raw) -> new level: terrain 1.00 (0.90) -> 1.00  "
                     f"ledge {s:.2f} ({0.9 * s:.2f}) -> {level:.2f}  slope {s:.2f} ({0.9 * s:.2f}) -> {level:.2f}  fault 1.00 (0.90) -> 1.00")      # relative (raw): the verdicts read the relative score
    return lines


def test_report_verdicts():
    caps = {"sidehill_deg": 10.0, "uphill_deg": 12.0, "ledge_m": 0.02}
    # the level is past where the caps bind and every probe is good: the caps are too low
    v = C.verdicts(C.parse(_log([0.9] * 8, 1.0)), caps)
    assert v["uphill_deg"]["verdict"] == "CAP TOO LOW" and C.suggest("uphill_deg", 12.0, "CAP TOO LOW") == 14.0
    # the caps bind and the policy keeps failing: too high
    v = C.verdicts(C.parse(_log([0.3, 0.4, 0.3, 0.5, 0.45, 0.3], 1.0)), caps)
    assert v["ledge_m"]["verdict"] == "CAP TOO HIGH" and C.suggest("ledge_m", 0.02, "CAP TOO HIGH") == 0.015
    # the level has not reached where the cap binds: the ramp, not the cap, limits difficulty
    v = C.verdicts(C.parse(_log([0.9] * 8, 0.3)), caps)
    assert v["sidehill_deg"]["verdict"] == "ON TRACK" and v["ledge_m"]["verdict"] == "ON TRACK"
    # too few probes to judge
    assert C.verdicts(C.parse(_log([0.9] * 3, 1.0)), caps)["ledge_m"]["verdict"] == "TOO EARLY"
    # a cap never moves above the course's own design size
    assert C.suggest("uphill_deg", 24.0, "CAP TOO LOW") == 24.0 and C.suggest("ledge_m", 0.037, "CAP TOO LOW") == 0.037


def test_verdicts_read_the_relative_score_and_the_runs_own_course():
    caps = {"uphill_deg": 12.0}
    # relative 0.85 (raw 0.77): the curriculum counts these as good probes, so the report must too
    v = C.verdicts(C.parse(_log([0.85] * 8, 1.0)), caps)
    assert v["uphill_deg"]["verdict"] == "CAP TOO LOW"
    # the next fresh final tilts the ground up to 10 deg x 1.10: a 10 deg descent cap binds from level ~0.91, not 0.65 (the old 14 deg course)
    nom = C.nominal_for("no_such_tag")
    assert abs(nom["downhill_deg"] - 11.0) < 1e-6 and nom["uphill_deg"] == 24.0 and nom["ledge_m"] == 0.035
    v = C.verdicts(C.parse(_log([0.9] * 8, 0.8)), {"downhill_deg": 10.0}, nom)
    assert v["downhill_deg"]["verdict"] == "ON TRACK" and abs(v["downhill_deg"]["binding_level"] - 10 / 11) < 1e-6
