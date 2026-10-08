"""The curriculum probe measures what it claims to (2026-10-08 review): the probed hazard is in every probe episode, probes walk forward, seeds are honoured, and a ledge
on tilted ground lies on the ground (a step-down no longer starts G2 tilted on a level block). Run with the RL venv: pytest test_probe_presence.py."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PROBE = r"""
import os, sys
sys.path.insert(0, ".")
for k in [k for k in os.environ if k.startswith("G2E_")]:
    del os.environ[k]
import g2_profile
g2_profile.set_environ(g2_profile.next_final_env())
import numpy as np, pybullet as p
import opencat_gym_env as E
E.GUI_MODE = False
e = E.OpenCatGymEnv(); e.set_ramp_steps(10e6)
N = 60
def present(cat):
    n_payload = sum(x is not None for x in (e._payload_id, e._head_id, e._rear_id))
    if cat == "ledge":
        return e._ledge_h > 0
    if cat == "slope":
        return bool(e._slope_targeted)
    if cat == "fault":
        return bool(np.any(e._torque_scale < 1.0))      # any cutback, however small
    rough = abs(p.getBasePositionAndOrientation(e._plane_id)[0][0] - 1.4) < 1e-6
    return rough or p.getNumBodies() - 2 - n_payload > 0
out = {}
for force in (False, True):
    for cat in ("terrain", "ledge", "slope", "fault"):
        E.CATEGORY_OVERRIDE, E.CATEGORY_FORCE = {cat: 1.0}, force
        out[(force, cat)] = sum(present(cat) for _ in range(N) if e.reset() is not None) / N
E.CATEGORY_OVERRIDE, E.CATEGORY_FORCE = {}, False
print("PRESENT", {f"{'forced' if f else 'plain'}_{c}": v for (f, c), v in out.items()})
# seeds are honoured: the same seed gives the same course and command
a = []
for _ in range(2):
    e._forced_cmd = None
    e.reset(seed=1234)
    a.append((e._cmd_fwd, e._slope_rp, e._ledge_h, p.getNumBodies()))
print("SEEDED", a[0] == a[1])
cmds = [E.probe_command(s) for s in range(400)]
print("CMDS", min(cmds), max(cmds), E.probe_command(7) == E.probe_command(7))
# a step-down ledge on tilted ground: standing still for 0.5 s, the body barely moves (it dropped ~5 deg, up to 10, when the block was level)
E.LEDGE_DIR = -1
E.RANDOM_PUSH_PROB = E.IMPULSE_PUSH_PROB = 0.0         # no shoves: this measures how the ground sits under G2, not a push
E.CATEGORY_OVERRIDE, E.CATEGORY_FORCE = {"ledge": 1.0, "slope": 1.0}, True
rot = []
for k in range(40):
    e.set_command(fwd=0.0, yaw=0.0)
    e.reset(seed=500 + k)
    if e._ledge_h <= 0 or max(abs(np.array(e._slope_rp))) < np.radians(3):
        continue
    r0 = np.degrees(p.getEulerFromQuaternion(p.getBasePositionAndOrientation(e.robot_id)[1])[:2])
    for _ in range(40):
        e.step(np.zeros(8))
    r1 = np.degrees(p.getEulerFromQuaternion(p.getBasePositionAndOrientation(e.robot_id)[1])[:2])
    rot.append(float(np.abs(r1 - r0).max()))
print("STEPDOWN", len(rot), float(np.median(rot)), float(np.max(rot)))
"""


def _run():
    r = subprocess.run([sys.executable, "-c", PROBE], cwd=HERE, capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-1500:]
    out = {}
    for line in r.stdout.splitlines():
        for key in ("PRESENT", "SEEDED", "CMDS", "STEPDOWN"):
            if line.startswith(key + " "):
                out[key] = line[len(key) + 1:]
    return out


def test_probe_measures_the_hazard_it_names():
    out = _run()
    pres = eval(out["PRESENT"])                                       # noqa: S307 -- our own printout
    for cat in ("terrain", "ledge", "slope", "fault"):
        assert pres[f"forced_{cat}"] == 1.0, (cat, pres)               # every probe episode has the hazard
    assert pres["plain_ledge"] < 0.6                                  # training episodes keep their own chances (the course's shares are unchanged)
    assert out["SEEDED"] == "True"
    lo, hi, same = out["CMDS"].split()
    assert float(lo) >= 0.04 and float(hi) <= 0.15 and same == "True"  # probes walk forward, the same command for the same episode
    n, med, mx = out["STEPDOWN"].split()
    assert int(n) >= 10 and float(med) < 2.0 and float(mx) < 5.0, out["STEPDOWN"]
